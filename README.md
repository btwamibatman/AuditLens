# AuditLens

Reusable full-stack starter for turning a new idea into a working app. It includes a Vue 3 + TypeScript frontend, a FastAPI backend, database migrations, and optional examples for authentication, AI, and file uploads.

Use **Use this template** on GitHub to create a new repository. The included CRUD screen is a reference feature: rename it or replace it with your domain.

## Stack

- Vue 3 Single-File Components (`.vue`), TypeScript, Vite
- FastAPI, Pydantic, SQLAlchemy 2, Alembic
- SQLite by default; PostgreSQL can be configured
- Docker Compose for a single-container deployment

## Quick start

Requirements: Node.js 20.19+, Python 3.11+, and Git. From the repository root:

```bash
npm run setup
npm run dev
```

Open <http://localhost:5173>. The API runs at <http://localhost:8000>; interactive docs are at <http://localhost:8000/api/docs>.

`npm run setup` creates the Python environment, installs dependencies, copies `.env.example` to `.env`, applies migrations, and installs frontend packages. You can also run the frontend and API separately with `npm run dev:web` and `npm run dev:api`.

## Make it yours

1. Set `APP_NAME` and environment values in `.env`.
2. Rename or replace `backend/app/features/items` and the example CRUD view in `frontend/src/App.vue`.
3. Add backend features under `backend/app/features/<feature>` and register their router in `backend/app/api.py`.
4. Add Vue screens and components under `frontend/src`; keep API calls in small modules and send them through `frontend/src/lib/api.ts`.
5. Generate and apply schema changes with `npm run db:revision -- "describe_change"` and `npm run db:migrate`.

The starter keeps its core small. Auth, AI, and uploads are optional backend features; enable them in `.env` with `ENABLE_AUTH`, `ENABLE_AI`, or `ENABLE_UPLOADS`. Their example UI appears when the corresponding feature is enabled.

## Useful commands

```bash
npm run db:migrate     # Apply database migrations
npm run db:revision -- "add_records"
npm run db:seed        # Add sample records
npm run lint           # Ruff and Vue/TypeScript type checks
npm run test           # Backend tests
npm run build          # Type-check and build the Vue frontend
npm run start          # Build frontend and serve the app with FastAPI
docker compose up --build
```

## Project layout

```text
backend/app/core/          Settings, DB session, common schemas and errors
backend/app/features/      Feature modules: CRUD example, auth, AI, uploads
backend/migrations/        Alembic schema history
frontend/src/App.vue       Example shell and feature screens
frontend/src/lib/api.ts    Shared typed HTTP client
frontend/src/styles/       Design tokens and global CSS
scripts/                   Cross-platform setup and development commands
```

## Configuration

### Evaluation capacity

`LLM_BATCH_CONCURRENCY` is the shared limit for simultaneous evaluations in one backend
process, including single requests and batch workers (default 4). It is read at startup;
restart the backend after changing it. Only one batch can run in that process at a time.

| Request | Success | Busy response |
| --- | --- | --- |
| `POST /api/evaluations` | `201`, completed evaluation | `429`, code `evaluation_busy` |
| `POST /api/evaluations/batch` | `202`, job ID | `409`, code `batch_already_running` |

Busy responses use the existing `{detail, code}` error object. Show `detail` and allow
a later manual retry; do not automatically repeat AI requests. A rejected single
request creates no evaluation and makes no model call. A second batch is rejected
before another worker pool is created. An accepted batch waits for capacity using
only its fixed worker threads; its records are not marked failed because slots are busy.
Status and other API requests remain available while the provider is waiting.

Run one server worker and one application instance for this guarantee. The production
start commands explicitly use `--workers 1`. Separate CLI processes, server workers,
or replicas have independent limits; do not run an evaluation CLI alongside the server
and expect them to share capacity. This is not a distributed queue. Batch progress
still lives in memory and is lost on restart, while committed evaluations remain in
the database. Overall AI deadlines, cancellation, and automatic recovery are separate
work; this limit does not interrupt a hung provider call.

### Official CQA results export

Export saved database evaluations with `python -m app.features.evaluations.export` from
the `backend` directory. Supply the original dataset JSON and a UTF-8 JSON array of the
exact saved evaluation IDs selected for one run, including failed evaluations. Select
one checklist ID and version and explicitly choose the original AI results or final
reviewed results. For example:

```bash
python -m app.features.evaluations.export --kind dev --group DEV \
  --dataset ../docs/invoke.json --evaluation-ids ./evaluation-ids.json \
  --checklist-id 1 --checklist-version 1 --source ai \
  --team 'Team name' --model-mode external_api
```

Use `--kind prod` and the original control dataset and group ID for PROD. Replace the
checklist ID and version in the example with the values of the selected evaluations.
`--source ai` exports the original model result; `--source final` explicitly exports the
result after any appeal decisions. Identify reviewed results as reviewed when sharing
them. `--model-mode` describes the actual model deployment (`local`, `external_api`, or
`hybrid`); a human review does not change an external API model into a hybrid model.

The export refuses incomplete or mismatched datasets, missing or duplicate evaluations,
incompatible checklist snapshots, mock-model evaluations, invalid evidence and scores.
Only verified quotes that still occur in the source transcript become evidence turns.
For omitted actions, a valid checked range becomes the corresponding 1-based turns,
including client, bot and system messages; no quote is invented. N/A still requires a
verified quote and a nonempty reason. These checks do not establish semantic relevance:
both model rationales and reviewer decisions still need quality review.
It writes `results/dev/results.json` or `results/prod/results.json` atomically only after
validation. DEV requires 65 records and PROD 10. No evaluations or model calls are made
by the export command. Keep the evaluation ID selection as the record of the chosen run:
the existing database does not store a batch run identifier.

The command only reads saved evaluations. It neither evaluates missing conversations
nor creates official results from test data. A failed export preserves an existing file.
The older batch JSON/CSV files under `backend/data/exports/` are diagnostic exports and
do not replace these official files.


The root `.env.example` documents all supported settings. The default database is local SQLite. For PostgreSQL, set `DATABASE_URL` to a SQLAlchemy URL such as `postgresql+psycopg://user:password@localhost:5432/app` and start PostgreSQL separately.

Do not commit `.env`, API keys, local databases, or uploaded files.

## Template notes

- GitHub template repositories create a new repository from the committed starter files, without copying this repository's commit history.
- The reference CRUD feature is intentionally small and demonstrates request validation, persistence, filtering, and Vue forms.
- Optional modules can be removed from both the backend and frontend if a project does not need them.
