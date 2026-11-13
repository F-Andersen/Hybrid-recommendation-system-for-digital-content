# Гібридна рекомендаційна система цифрового контенту

Дипломний проєкт: «Інформаційна технологія персоналізованого рекомендаційного аналізу цифрового контенту на основі гібридних алгоритмів машинного навчання».

Вебплатформа з каталогом фільмів і книг, яка рекомендує, що подивитися або почитати. Рекомендації будує гібрид класичних ML-алгоритмів (колаборативна фільтрація ALS + контентна схожість на ембедингах BGE-M3), а локальна мовна модель Qwen3 8B (через Ollama) переранжовує кандидатів під конкретного користувача і пояснює кожну рекомендацію людською мовою. Платні API не використовуються — усе працює локально.

Повна специфікація для реалізації: [docs/IMPLEMENTATION.md](docs/IMPLEMENTATION.md).

## Як це працює

```
оцінки та перегляди користувача
        │
        ├─► ALS (implicit)            → top-200 кандидатів за схожістю поведінки
        ├─► контент (BGE-M3, pgvector) → top-200 кандидатів за схожістю змісту
        │
        ▼
  гібридне злиття оцінок  → top-30
        │
        ▼
  Qwen3 8B (Ollama)       → top-10 + пояснення «чому саме це»
```

1. **Колаборативна фільтрація (ALS).** Матриця «користувач × об'єкт» розкладається на латентні фактори; рекомендуються об'єкти, які вподобали користувачі зі схожою поведінкою.
2. **Контентна модель.** Опис кожного об'єкта (назва, жанри, теги, анотація) перетворюється на вектор BGE-M3 (1024 виміри). Профіль користувача — зважене середнє векторів оцінених ним об'єктів; найближчі вектори шукає pgvector.
3. **Гібрид.** Нормалізовані оцінки двох моделей зливаються з вагою α, яка залежить від кількості оцінок користувача (новачок — більше контенту, досвідчений — більше ALS).
4. **LLM.** Qwen3 отримує профіль смаків і 30 кандидатів, повертає впорядкований top-10 з поясненнями у форматі JSON. Якщо модель недоступна або відповіла некоректно — показується гібридний список без пояснень.

## Стек

| Шар | Технології |
|---|---|
| Інтерфейс | Next.js (App Router) + TypeScript |
| Backend | Python 3.11 + FastAPI, SQLAlchemy 2, Alembic |
| База даних | PostgreSQL 17 + pgvector |
| ML | implicit (ALS), scikit-learn, NumPy/SciPy, pandas |
| Локальний ШІ | Ollama: `qwen3:8b` (генерація), `bge-m3` (ембединги) |
| Розгортання | Docker Compose |

## Зв'язки між сервісами

```
 Браузер
    │ http://localhost:3000
    ▼
┌──────────────┐  /api/* (rewrite)  ┌──────────────┐  SQL :5432   ┌────────────────────┐
│ web (Next.js)│ ─────────────────► │ api (FastAPI)│ ───────────► │ db (Postgres +     │
│ :3000        │                    │ :8000        │              │ pgvector)          │
└──────────────┘                    └──────┬───────┘              └────────────────────┘
                                           │ HTTP :11434
                                           ▼
                                    ┌──────────────┐
                                    │ Ollama (хост)│  qwen3:8b, bge-m3
                                    └──────────────┘
```

- Браузер звертається лише до `web`; запити `/api/*` Next.js проксіює на `api` (без CORS, сесія в httpOnly-cookie).
- `api` — єдиний сервіс, що говорить із базою та з Ollama.
- Ollama запускається нативно на Windows (доступ до GPU), контейнер `api` бачить його як `http://host.docker.internal:11434`.
- Навчені моделі ALS лежать в іменованому томі `artifacts` (`/app/artifacts` у контейнері) і завантажуються в пам'ять `api` під час старту. Сирі датасети — у томі `rawdata` (`/app/data`).
- Bind-монтувань теки проєкту немає: Docker Desktop не монтує шляхи, де назва теки довша за 255 байт, а довгі кириличні назви саме такі. Код вшивається в образ, у режимі розробки його синхронізує `docker compose watch`.

## Вимоги

- Windows 10/11 з Docker Desktop (WSL2).
- [Ollama](https://ollama.com/download) для Windows.
- Відеокарта з 8 ГБ VRAM (рекомендовано). На CPU працює, але пояснення генеруються повільно (десятки секунд).
- ~15 ГБ вільного місця (моделі ≈ 6,5 ГБ, дані, образи).

## Швидкий старт

Стан реалізації: етап 0 (каркас) готовий; скрипти даних і моделей з'являться на етапах 1–3.

Завантажити моделі:

```bash
ollama pull qwen3:8b
```

```bash
ollama pull bge-m3
```

Створити файл налаштувань (замінити `JWT_SECRET` і `ADMIN_TOKEN`; якщо порти 3000/8000/5433 зайняті — змінити `*_HOST_PORT`) і запустити сервіси:

```bash
cp .env.example .env
```

```bash
docker compose up -d --build
```

Під час розробки — синхронізація коду в контейнери (backend перезавантажується сам, frontend перезбирається):

```bash
docker compose watch
```

Тести й лінтер backend:

```bash
docker compose exec api pytest
```

```bash
docker compose exec api ruff check .
```

Застосувати міграції, завантажити дані, порахувати ембединги, навчити ALS:

```bash
docker compose exec api alembic upgrade head
```

```bash
docker compose exec api python -m scripts.download_data
```

```bash
docker compose exec api python -m scripts.import_movielens
```

```bash
docker compose exec api python -m scripts.import_bookcrossing
```

```bash
docker compose exec api python -m scripts.enrich_openlibrary
```

```bash
docker compose exec api python -m scripts.build_embeddings
```

```bash
docker compose exec api python -m scripts.train_als
```

Відкрити http://localhost:3000 (головна сторінка показує стан усіх компонентів). Документація API: http://localhost:8000/docs. Порти — з `WEB_HOST_PORT` і `API_HOST_PORT`.

## Змінні середовища (`.env`)

| Змінна | Значення за замовчуванням | Призначення |
|---|---|---|
| `WEB_HOST_PORT` / `API_HOST_PORT` / `DB_HOST_PORT` | `3000` / `8000` / `5433` | порти на хості |
| `ADMIN_TOKEN` | — (згенерувати) | заголовок `X-Admin-Token` для `/admin/*` |
| `DATABASE_URL` | `postgresql+psycopg://recsys:recsys@db:5432/recsys` | підключення `api` до бази |
| `OLLAMA_BASE_URL` | `http://host.docker.internal:11434` | адреса Ollama |
| `LLM_MODEL` | `qwen3:8b` | модель для переранжування й пояснень |
| `EMBED_MODEL` | `bge-m3` | модель ембедингів (1024 виміри) |
| `JWT_SECRET` | — (згенерувати) | підпис токенів сесії |
| `API_INTERNAL_URL` | `http://api:8000` | куди Next.js проксіює `/api/*` |
| `ARTIFACTS_DIR` | `/app/artifacts` | навчені моделі ALS |
| `DATA_DIR` | `/app/data` | сирі датасети |

## Дані

| Джерело | Що беремо | Примітка |
|---|---|---|
| [MovieLens](https://grouplens.org/datasets/movielens/) | `ml-latest-small` для розробки, `ml-1m` для експериментів | оцінки 0.5–5, є часові мітки, жанри, теги |
| [Book-Crossing](https://grouplens.org/datasets/book-crossing/) | оцінки книг, метадані за ISBN | оцінки 1–10, 0 = неявна взаємодія; часових міток немає |
| [Open Library](https://openlibrary.org/developers/api) | анотації, тематики, обкладинки | збагачення лише відфільтрованих книг, з кешем |

Датасети завантажуються скриптом у том `rawdata` і в репозиторій не потрапляють.

## Наукова частина

Порівнюються моделі: популярність (базова лінія), контентна, колаборативна (ALS), гібридна, гібридна + LLM-переранжування. Метрики: Precision@K, Recall@K, NDCG@K для K ∈ {5, 10, 20}.

```bash
docker compose exec api python -m scripts.evaluate --domain movie
```

```bash
docker compose exec api python -m scripts.evaluate --domain book
```

Результати зберігаються в томі `artifacts` (`/app/artifacts/eval/`: CSV + графіки) і відображаються на сторінці `/evaluation`. Скопіювати на диск для диплома:

```bash
docker compose cp api:/app/artifacts/eval ./eval-results
```

## Структура репозиторію

```
├── docker-compose.yml
├── .env.example
├── README.md
├── CLAUDE.md                  правила для Claude Code
├── docs/IMPLEMENTATION.md     повна специфікація й етапи
├── backend/
│   ├── app/                   FastAPI: api/, core/, db/, recsys/, llm/
│   ├── scripts/               імпорт даних, ембединги, навчання, оцінювання
│   ├── alembic/               міграції
│   └── tests/
└── frontend/                  Next.js (src/app, src/lib)
```
