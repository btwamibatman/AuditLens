# Launchpad

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

The root `.env.example` documents all supported settings. The default database is local SQLite. For PostgreSQL, set `DATABASE_URL` to a SQLAlchemy URL such as `postgresql+psycopg://user:password@localhost:5432/app` and start PostgreSQL separately.

Do not commit `.env`, API keys, local databases, or uploaded files.

## Template notes

- GitHub template repositories create a new repository from the committed starter files, without copying this repository's commit history.
- The reference CRUD feature is intentionally small and demonstrates request validation, persistence, filtering, and Vue forms.
- Optional modules can be removed from both the backend and frontend if a project does not need them.
