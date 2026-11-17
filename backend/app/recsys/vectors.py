"""Validate and normalize vectors before they enter storage or ranking."""

import numpy as np
from numpy.typing import NDArray

EMBEDDING_DIMENSION = 1024


def normalize_vectors(
    vectors: object, expected_count: int | None = None,
) -> NDArray[np.float32]:
    try:
        matrix = np.asarray(vectors, dtype=np.float32)
    except (TypeError, ValueError) as exc:
        raise ValueError("Ембединги мають бути числовою матрицею") from exc
    if matrix.ndim == 1 and matrix.size == 0:
        matrix = matrix.reshape(0, EMBEDDING_DIMENSION)
    if matrix.ndim != 2 or matrix.shape[1] != EMBEDDING_DIMENSION:
        raise ValueError(f"Очікується матриця ембедингів із {EMBEDDING_DIMENSION} вимірами")
    if expected_count is not None and len(matrix) != expected_count:
        raise ValueError("Кількість ембедингів не відповідає кількості текстів")
    if not np.isfinite(matrix).all():
        raise ValueError("Ембединг містить нечислові або нескінченні значення")
    norms = np.linalg.norm(matrix.astype(np.float64), axis=1, keepdims=True)
    if (norms == 0).any():
        raise ValueError("Отримано нульовий ембединг")
    return (matrix / norms).astype(np.float32)
