"""CPU implicit ALS, fold-in and validated, versioned local artifacts."""

import hashlib
import io
import json
import logging
import os
import tempfile
import zipfile
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import uuid4

import numpy as np
from implicit.cpu.als import AlternatingLeastSquares
from scipy.sparse import csr_matrix
from threadpoolctl import threadpool_limits

from app.recsys.types import Domain, HistoryRating, UserHistory, history_ids, positive_confidence

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AlsParameters:
    factors: int = 64
    regularization: float = 0.05
    iterations: int = 20
    random_state: int = 42
    num_threads: int = 4

    def __post_init__(self) -> None:
        for value in (self.factors, self.iterations, self.random_state, self.num_threads):
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError("Розмірність, ітерації, seed та потоки ALS мають бути цілими")
        if self.factors < 1 or self.iterations < 1 or self.num_threads < 1:
            raise ValueError("Параметри ALS мають бути додатними")
        if not np.isfinite(self.regularization) or self.regularization <= 0:
            raise ValueError("Регуляризація ALS має бути додатною і скінченною")
        if self.random_state < 0:
            raise ValueError("Seed ALS має бути невід'ємним")


def build_interaction_matrix(
    user_ids: list[int], item_ids: list[int], ratings: Iterable[tuple[int, HistoryRating]],
) -> csr_matrix:
    users, items = {value: i for i, value in enumerate(user_ids)}, {
        value: i for i, value in enumerate(item_ids)
    }
    if len(users) != len(user_ids) or len(items) != len(item_ids):
        raise ValueError("ID у відображеннях ALS мають бути унікальними")
    values: dict[tuple[int, int], float] = {}
    for user_id, rating in ratings:
        if user_id not in users or rating.item_id not in items:
            raise ValueError("Взаємодія посилається на невідомий ID")
        key = users[user_id], items[rating.item_id]
        confidence = positive_confidence(rating)
        if confidence:
            values[key] = confidence
        else:
            values.pop(key, None)
    rows, columns, data = [], [], []
    for (row, column), confidence in sorted(values.items()):
        rows.append(row)
        columns.append(column)
        data.append(confidence)
    return csr_matrix((data, (rows, columns)), shape=(len(users), len(items)), dtype=np.float32)


class AlsRecommender:
    def __init__(
        self, model: AlternatingLeastSquares, user_items: csr_matrix,
        user_ids: list[int], item_ids: list[int], parameters: AlsParameters,
    ) -> None:
        self.model, self.user_items, self.parameters = model, user_items, parameters
        self.user_ids, self.item_ids = user_ids, item_ids
        self.user_index = {value: index for index, value in enumerate(user_ids)}
        self.item_index = {value: index for index, value in enumerate(item_ids)}
        if len(self.user_index) != len(user_ids) or len(self.item_index) != len(item_ids):
            raise ValueError("Дублікати ID в артефакті ALS")
        if user_items.shape != (len(user_ids), len(item_ids)):
            raise ValueError("Розміри матриці ALS не відповідають відображенням ID")
        user_items.check_format(full_check=True)
        if not user_items.has_canonical_format:
            raise ValueError("CSR-матриця ALS має містити впорядковані унікальні індекси")
        for factors, count in ((model.user_factors, len(user_ids)),
                               (model.item_factors, len(item_ids))):
            if factors.shape != (count, parameters.factors) or not np.isfinite(factors).all():
                raise ValueError("Некоректні фактори ALS")
        if not np.isfinite(user_items.data).all() or (user_items.data <= 0).any():
            raise ValueError("Некоректні значення довіри в матриці ALS")
        self.inactive_items = set(np.flatnonzero(user_items.getnnz(axis=0) == 0).tolist())

    def history_row(self, user: UserHistory) -> csr_matrix:
        values = {}
        for rating in user.ratings:
            if rating.item_id not in self.item_index:
                continue
            index = self.item_index[rating.item_id]
            value = positive_confidence(rating)
            if value:
                values[index] = value
            else:
                values.pop(index, None)
        columns = sorted(values)
        return csr_matrix(
            ([values[index] for index in columns], ([0] * len(columns), columns)),
            shape=(1, len(self.item_ids)), dtype=np.float32,
        )

    def recommend(
        self, user: UserHistory, k: int, exclude: set[int],
    ) -> list[tuple[int, float]]:
        if k <= 0:
            return []
        row = self.history_row(user)
        if row.nnz == 0:
            return []
        blocked = self.inactive_items | {
            self.item_index[value] for value in exclude | history_ids(user)
            if value in self.item_index
        }
        available = len(self.item_ids) - len(blocked)
        if available <= 0:
            return []
        index = self.user_index.get(user.user_id)
        known = index is not None and (row != self.user_items[index]).nnz == 0
        ids, scores = self.model.recommend(
            index if known else 0, row, N=min(k, available),
            filter_already_liked_items=True, filter_items=sorted(blocked),
            recalculate_user=not known,
        )
        results = [
            (self.item_ids[int(item)], float(score))
            for item, score in zip(ids, scores, strict=True)
            if 0 <= item < len(self.item_ids) and item not in blocked and np.isfinite(score)
            and score > np.finfo(np.float32).min
        ]
        return sorted(results, key=lambda pair: (-pair[1], pair[0]))


def train_als(
    user_ids: list[int], item_ids: list[int], ratings: Iterable[tuple[int, HistoryRating]],
    parameters: AlsParameters | None = None,
) -> AlsRecommender:
    parameters = parameters or AlsParameters()
    matrix = build_interaction_matrix(user_ids, item_ids, ratings)
    if not matrix.nnz:
        raise ValueError("Немає позитивних взаємодій для навчання ALS")
    with threadpool_limits(limits=1, user_api="blas"):
        model = AlternatingLeastSquares(**asdict(parameters))
        model.fit(matrix, show_progress=False)
    return AlsRecommender(model, matrix, user_ids, item_ids, parameters)


def save_model(recommender: AlsRecommender, directory: Path, domain: Domain) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    artifact_id = uuid4().hex
    temporary = []
    try:
        with tempfile.NamedTemporaryFile(dir=directory, suffix=".npz.part", delete=False) as stream:
            binary = Path(stream.name)
            temporary.append(binary)
            np.savez_compressed(
                stream, artifact_id=artifact_id, domain=domain,
                user_factors=recommender.model.user_factors,
                item_factors=recommender.model.item_factors,
                user_ids=np.asarray(recommender.user_ids, dtype=np.int64),
                item_ids=np.asarray(recommender.item_ids, dtype=np.int64),
                data=recommender.user_items.data, indices=recommender.user_items.indices,
                indptr=recommender.user_items.indptr,
                parameters=json.dumps(asdict(recommender.parameters), sort_keys=True),
            )
            stream.flush()
            os.fsync(stream.fileno())
        maps = {
            "format_version": 1, "artifact_id": artifact_id, "domain": domain,
            "sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
            "user_ids": recommender.user_ids, "item_ids": recommender.item_ids,
            "parameters": asdict(recommender.parameters),
        }
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=directory, suffix=".json.part", delete=False,
        ) as stream:
            manifest = Path(stream.name)
            temporary.append(manifest)
            json.dump(maps, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        binary.replace(directory / f"als_{domain}.npz")
        manifest.replace(directory / f"als_{domain}_maps.json")
    finally:
        for path in temporary:
            path.unlink(missing_ok=True)


def load_model(directory: Path, domain: Domain) -> AlsRecommender:
    maps = json.loads((directory / f"als_{domain}_maps.json").read_text(encoding="utf-8"))
    if maps["format_version"] != 1 or maps["domain"] != domain:
        raise ValueError("Непідтримуваний формат або домен артефакту ALS")
    path = directory / f"als_{domain}.npz"
    # Read once: a concurrent publication cannot change the checked bytes before parsing.
    binary = path.read_bytes()
    if hashlib.sha256(binary).hexdigest() != maps["sha256"]:
        raise ValueError("Файли ALS не узгоджені або пошкоджені")
    parameters = AlsParameters(**maps["parameters"])
    with np.load(io.BytesIO(binary), allow_pickle=False) as saved:
        if (str(saved["artifact_id"]) != maps["artifact_id"]
                or str(saved["domain"]) != domain
                or not np.array_equal(saved["user_ids"], maps["user_ids"])
                or not np.array_equal(saved["item_ids"], maps["item_ids"])
                or json.loads(str(saved["parameters"])) != maps["parameters"]):
            raise ValueError("Метадані ALS не відповідають моделі")
        with threadpool_limits(limits=1, user_api="blas"):
            model = AlternatingLeastSquares(**asdict(parameters))
        model.user_factors, model.item_factors = saved["user_factors"], saved["item_factors"]
        matrix = csr_matrix((saved["data"], saved["indices"], saved["indptr"]),
                            shape=(len(maps["user_ids"]), len(maps["item_ids"])))
    return AlsRecommender(model, matrix, maps["user_ids"], maps["item_ids"], parameters)


def load_available_models(directory: Path, *, strict: bool = False) -> dict[str, AlsRecommender]:
    models = {}
    for domain in ("movie", "book"):
        paths = [directory / f"als_{domain}.npz", directory / f"als_{domain}_maps.json"]
        if not any(path.exists() for path in paths):
            continue
        try:
            models[domain] = load_model(directory, domain)
        except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile, EOFError) as exc:
            if strict:
                raise ValueError(f"Не вдалося завантажити ALS для домену {domain}") from exc
            logger.warning("ALS для %s недоступна: %s", domain, exc)
    return models
