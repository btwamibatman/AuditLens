# Launchpad — инструкция на русском

Launchpad — стартовый full-stack шаблон: Vue 3 + TypeScript на фронтенде и FastAPI на бэкенде. Это каркас для новых приложений, а не готовый таск-трекер. Экран CRUD служит примером: замени его сущностью своего проекта.

## Быстрый запуск

Нужны Node.js 20.19+, Python 3.11+ и Git. В корне репозитория:

```powershell
npm run setup
npm run dev
```

Откройте `http://localhost:5173`. API работает на `http://localhost:8000`, документация Swagger — `http://localhost:8000/api/docs`.

`npm run setup` создаёт Python-окружение, устанавливает зависимости, копирует `.env.example` в `.env`, применяет миграции и устанавливает пакеты Vue.

## Создание проекта из шаблона GitHub

На странице Launchpad нажмите **Use this template → Create a new repository**. Выберите имя и видимость нового репозитория. GitHub создаст проект из текущих файлов, без истории коммитов Launchpad.

Для локального старта:

```powershell
git clone https://github.com/<ваш-аккаунт>/<ваш-репозиторий>.git
cd <папка-проекта>
npm run setup
npm run dev
```

## Что поменять в новом проекте

1. В `.env` поменяйте `APP_NAME`, при необходимости настройки базы и feature flags.
2. Замените пример `items` на предметную область проекта: backend-модуль находится в `backend/app/features/items`, Vue-экран — в `frontend/src/App.vue`.
3. Новую бизнес-логику добавляйте отдельным модулем в `backend/app/features/<название>` и подключайте router в `backend/app/api.py`.
4. Vue-страницы и компоненты создавайте в `frontend/src` как `.vue` Single-File Components. Общий HTTP-клиент уже есть в `frontend/src/lib/api.ts`.
5. После изменений моделей создайте миграцию и примените её:

```powershell
npm run db:revision -- "описание_изменения"
npm run db:migrate
```

## Опциональные примеры

По умолчанию auth, AI и загрузка файлов отключены. Включите нужные модули в `.env`:

```dotenv
ENABLE_AUTH=true
ENABLE_AI=true
AI_BASE_URL=https://api.openai.com/v1
AI_API_KEY=...
AI_MODEL=...
ENABLE_UPLOADS=true
```

AI API совместим с OpenAI API; можно указать endpoint другого совместимого провайдера. Auth требует настроенного `SECRET_KEY`. Для локального диска загрузок используется `UPLOAD_DIR`.

## Команды

```powershell
npm run dev        # Frontend и API вместе
npm run dev:web    # Только Vite/Vue
npm run dev:api    # Только FastAPI
npm run db:migrate # Применить миграции
npm run db:seed    # Добавить демонстрационные записи
npm run lint       # Ruff и проверка типов Vue/TypeScript
npm run test       # Backend-тесты
npm run build      # Проверка типов и production-сборка Vue
npm run start      # Собрать frontend и раздавать через FastAPI
```

Docker:

```powershell
docker compose up --build
```

Не коммитьте `.env`, секреты, локальную базу, загруженные файлы и `node_modules`.
