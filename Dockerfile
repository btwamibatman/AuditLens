FROM node:22-alpine AS frontend-builder
WORKDIR /app/frontend

COPY frontend/package*.json ./
RUN npm ci --no-audit

COPY frontend ./
RUN npm run build

FROM python:3.12-slim AS runner

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PORT=8000

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY backend/pyproject.toml ./backend/
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -e ./backend

COPY backend/ ./backend/
COPY checklist.json ./checklist.json
COPY docs/invoke.json ./docs/invoke.json
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

EXPOSE 8000

WORKDIR /app/backend

CMD ["sh", "-c", "python -m alembic upgrade head && python -m app.seed && python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
