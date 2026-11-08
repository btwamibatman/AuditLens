# AuditLens · Система контроля качества коммуникаций (CQA)

AuditLens — веб-приложение для автоматизированной и проверяемой оценки качества работы операторов поддержки (чаты и звонки на RU, KZ, EN) по настраиваемому чек-листу с привязкой к репликам транскрипта, контуром апелляций и строгим экспортом результатов в формате организаторов.

## Стек

- **Backend:** Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, `google-genai` (Gemini Interactions API)
- **Frontend:** Vue 3 + TypeScript, Vite
- **БД:** SQLite по умолчанию (`backend/data/app.db`), опционально PostgreSQL

## Быстрый старт

Требования: Node.js 20.19+, Python 3.11+ (рекомендуется `uv`), Git. Из корня репозитория:

```bash
npm run setup
npm run dev
```

- Фронтенд: <http://localhost:5173>
- API: <http://localhost:8000> (Swagger: <http://localhost:8000/api/docs>)

`npm run setup` создаёт виртуальное окружение Python, устанавливает зависимости, копирует `.env.example` в `.env` (если файла ещё нет), применяет миграции БД, гарантирует наличие стартового чек-листа CQA из 8 критериев и устанавливает пакеты фронтенда.

## Основные команды

```bash
npm run dev            # Запуск backend + frontend в режиме разработки
npm run db:migrate     # Применить миграции БД (включая обновление стартового чек-листа)
npm run db:seed        # Убедиться, что стартовый чек-лист CQA создан
npm run lint           # Проверка Ruff (backend) и типизации Vue/TypeScript (frontend)
npm run test           # Полный прогон backend-тестов (pytest, без платных AI-вызовов)
npm run build          # Сборка фронтенда
npm run start          # Сборка фронтенда и запуск единого сервера FastAPI (--workers 1)
docker compose up --build
```

## Настройка окружения (`.env`)

Все переменные документированы в `.env.example`. **Никогда не коммитьте `.env` и API-ключи.**

- `LLM_PROVIDER`: `gemini` (реальная оценка через Gemini Interactions API) или `mock` (офлайн-заглушка для отладки интерфейса и автотестов; для официальной сдачи не допускается). Если `GEMINI_API_KEY` пуст, приложение автоматически переключается в `mock` и явно предупреждает об этом в логах и карточке оценки.
- `GEMINI_API_KEY`: ключ API Gemini (задаётся только локально в `.env`).
- `GEMINI_MODEL`: по умолчанию `gemini-3.6-flash`.
- `GEMINI_THINKING_LEVEL`: `minimal` | `low` | `medium` | `high` (по умолчанию `medium`).
- `LLM_TIMEOUT_SECONDS`: общий бюджет времени на одну оценку в секундах (по умолчанию `120`), включая сетевые повторы и повтор при невалидном JSON. Внутренние скрытые повторы SDK отключены (`attempts=1`), чтобы исключить неконтролируемое умножение платных вызовов. При истечении времени оценка получает статус `failed`, освобождает рабочий слот и сохраняет ошибку (с явным примечанием, если принудительная отмена запроса на стороне провайдера не гарантирована).
- `LLM_MAX_RETRIES`: максимальное число транспортных попыток в рамках общего дедлайна (по умолчанию `3`).
- `LLM_BATCH_CONCURRENCY`: общий лимит одновременно выполняемых оценок в одном процессе (по умолчанию `4`).
- `LLM_PRICE_INPUT_PER_1M` / `LLM_PRICE_OUTPUT_PER_1M`: тарифы (по умолчанию `$1.50` / `$7.50` за 1M токенов, где `thought_tokens` тарифицируются как выход без двойного учёта). **Важно:** отображаемая в UI, API и отчётах стоимость (`cost_usd`) является **расчётной** по настройкам проекта (с учётом всех фактически потраченных попыток и ретраев), а не выпиской биллинга провайдера.
- `DATASET_API_URL`: ссылка на внешний API организаторов для синхронизации наборов по `group_id`.
  Храните подписанную ссылку целиком в `.env`: при запросе заменяется только `group_id`,
  остальные параметры (включая подпись) сохраняются. URL не печатается в HTTPX-логах
  запроса набора и сообщениях об ошибках API.

## Сценарий работы

1. **Загрузка диалогов (`F1` / `/api/conversations`):**
   - Синхронизация по `group_id` (`POST /api/conversations/sync?group_id=DEV`) при заданном `DATASET_API_URL`.
   - Либо ручной импорт JSON-файла (`docs/invoke.json`) через UI или `POST /api/conversations/import`. Повторяющиеся `conversation_id` внутри одного набора отклоняются до частичного сохранения; повторный импорт обновляет записи без дублей.
2. **Чек-лист и версионирование (`F4` / `/api/checklists`):**
   - Базовый чек-лист содержит 8 критериев ТЗ (`contact`, `discovery`, `identification`, `consultation`, `empathy`, `dialogue`, `closure`, `critical`).
   - Любое изменение критериев через UI или `PUT /api/checklists/{id}` увеличивает `version`.
   - Каждая оценка сохраняет `checklist_snapshot` и `checklist_version` на момент запуска: редактирование чек-листа не меняет прошлые оценки и не смешивает правила внутри уже запущенного пакетного прогона (`batch`).
3. **Оценка и доказательства (`F2` / `/api/evaluations`):**
   - Одиночная оценка (`POST /api/evaluations`) или пакетный запуск (`POST /api/evaluations/batch`).
   - Ответ модели проходит строгую структурную валидацию: полнота критериев, допустимые ступени шкалы, правила N/A (обязательна подтверждённая цитата и причина), дословная проверка цитат в транскрипте (`verified=true`), проверка границ `checked_range` и непротиворечивость `critical`.
   - Грубая ошибка (`critical`) выставляет флаг `has_critical_error` (`critical_flag`), но не обнуляет итоговый балл.
   - Для звонков инструкции адаптируют коммуникацию к устной речи по предоставленному транскрипту: логика разговора, понятность формулировок и явно обозначенные ожидания/паузы. Аудиоссылка не означает, что модель прослушала запись; дикция, темп и интонация по тексту не оцениваются. Разница timestamps не доказывает тишину, а ISO-время не преобразуется в позицию записи. Сохраняются настроенные критерии, шкалы, веса и условия N/A; отсутствие аудио само по себе не даёт N/A.
4. **Апелляция и пересмотр (`F3` / `/api/appeals`):**
   - По любому критерию завершённой оценки можно подать апелляцию (`POST /api/appeals`) и принять решение проверяющего (`POST /api/appeals/{id}/review`: `confirm` или `change` с обязательным комментарием).
   - При `change` новые значения проверяются по `checklist_snapshot` конкретной оценки; исходный `ai_result` сохраняется неизменным, а `final_result` и итоговый балл пересчитываются атомарно.

## Управление нагрузкой (`LLM_BATCH_CONCURRENCY`)

`LLM_BATCH_CONCURRENCY` — общий предел одновременных оценок в одном процессе сервера (одиночные запросы + рабочие потоки `batch`, по умолчанию `4`). Одновременно допускается только один активный `batch`.

| Запрос | Успех | При занятости |
| --- | --- | --- |
| `POST /api/evaluations` | `201`, готовая оценка | `429`, код `evaluation_busy` |
| `POST /api/evaluations/batch` | `202`, `job_id` | `409`, код `batch_already_running` |

Прогресс активного `batch` хранится в памяти процесса (`GET /api/evaluations/batch/{job_id}`). При перезапуске сервера оперативный прогресс `job_id` очищается (возвращается `404` с пояснением), но все завершённые и неуспешные оценки сохранены в БД и доступны через `GET /api/evaluations` (с фильтрацией по `dataset_group`, `checklist_id`, `checklist_version`), а недооценённые диалоги можно досчитать с флагом `only_missing=true`.

## Официальный экспорт результатов (`results.json`)

### Получить набор → выполнить batch → выгрузить результаты

После `npm run setup` задайте в `.env` `DATASET_API_URL`, `LLM_PROVIDER=gemini` и
`GEMINI_API_KEY`. Команды ниже выполняются **из корня проекта**; `scripts/py.mjs`
выбирает Python проекта, загружает `.env` и запускает модуль с рабочим каталогом
`backend/`. Поэтому пути `data/exports/...` относятся к `backend/data/exports/`.
Каждому запуску нужна новая папка: существующая `--output-dir` не перезаписывается.

1. Получить DEV и сохранить исходный ответ API (без вызова модели):

```bash
node scripts/py.mjs -m app.features.evaluations.batch --sync --sync-only --group DEV --output-dir data/exports/dev-source
```

2. Выполнить batch по загруженной группе с выбранным чек-листом:

```bash
node scripts/py.mjs -m app.features.evaluations.batch --group DEV --checklist 1 --output-dir data/exports/dev-run
```

`--checklist 1` — пример; укажите нужный ID (без этого флага используется активный).
Снимок ID/версии фиксируется перед выбором целей и используется всеми оценками запуска.
Команда выводит ID/версию чек-листа, путь `evaluation-ids.json` и необработанные диалоги.
В `evaluation-ids.json` лежит только массив ID, созданных этим batch, включая сохранённые
ошибочные оценки. Файл атомарно обновляется по ходу выполнения и после завершения.
`run.json` рядом сохраняет версию чек-листа, полноту охвата и необработанные ID.
`diagnostic.json`/`.csv` — диагностические файлы, не официальная сдача.
Без `--output-dir` автоматически создаётся уникальная папка в `backend/data/exports/`.

3. Передать сохранённые файлы и **напечатанные batch ID/версию** существующему экспортёру
(ниже пример для чек-листа `1`, версии `1`):

```bash
node scripts/py.mjs -m app.features.evaluations.export --kind dev --group DEV --dataset data/exports/dev-source/dataset.json --evaluation-ids data/exports/dev-run/evaluation-ids.json --checklist-id 1 --checklist-version 1 --source ai --team "AuditLens" --model-mode external_api
```

Для контрольного набора используйте его **точный произвольный ID**, а не строку `PROD`:

```bash
node scripts/py.mjs -m app.features.evaluations.batch --sync --sync-only --group "control-42" --output-dir data/exports/control-source
node scripts/py.mjs -m app.features.evaluations.batch --group "control-42" --checklist 1 --output-dir data/exports/control-run
node scripts/py.mjs -m app.features.evaluations.export --kind prod --group "control-42" --dataset data/exports/control-source/dataset.json --evaluation-ids data/exports/control-run/evaluation-ids.json --checklist-id 1 --checklist-version 1 --source ai --team "AuditLens" --model-mode external_api
```

`control-42` заменяется выданным ID во всех трёх командах. Можно совместить получение
и оценку: `batch --sync --group ...` сохранит `dataset.json` и `evaluation-ids.json`
в одной папке. Это уже запускает модель; `--sync-only` её не вызывает.

Если хотя бы одна оценка завершилась ошибкой, batch возвращает код `1`, но файл ID
всё равно сохраняется. Ошибочная оценка считается обработанным диалогом и включается
в официальный экспорт как `status: "error"`. Отсутствующая сохранённая оценка —
необработанный диалог. Команды batch и export запускайте отдельными шагами: код `1`
сам по себе не означает, что полный файл из успешных и ошибочных оценок нельзя сдать.

При `--limit` или `--only-missing` CLI выводит `INCOMPLETE`, если текущий запуск не
покрывает весь набор. Старые оценки автоматически не добавляются. Если всё уже оценено,
`--only-missing` сохраняет пустой список и не вызывает модель. Для цельного прогона
запустите batch без этих флагов в новой папке. Даже сообщение `Coverage complete`
означает только охват: окончательно ID, исходные транскрипты, модель, снимок чек-листа
и баллы проверяет экспортёр. DEV требует ровно 65 записей, контроль — 10; неполная
выборка не создаёт и не заменяет официальный `results.json`.

Последовательность проверена офлайн через те же CLI `main()` на временной SQLite:
сохранение исходного ответа API, batch с успешной и ошибочной оценками, экспорт
точного списка, отказ для `--limit`/`--only-missing` и сохранение прежнего результата.
Это проверка процесса; платные прогоны и оценка качества модели здесь не выполнялись.

### Контракт существующего экспортёра

Экспорт сохранённых в БД оценок в официальный формат организаторов выполняется CLI-командой `python -m app.features.evaluations.export` из каталога `backend/`. Команда не делает вызовов к LLM и атомарно записывает `results/dev/results.json` (ровно 65 записей) или `results/prod/results.json` (ровно 10 записей) только после полной валидации:

```bash
python -m app.features.evaluations.export --kind dev --group DEV \
  --dataset ../docs/invoke.json --evaluation-ids ./evaluation-ids.json \
  --checklist-id 1 --checklist-version 1 --source ai \
  --team "AuditLens" --model-mode external_api
```

- `--source ai` выгружает исходную оценку модели (`ai_result`), `--source final` — финальную оценку после решений по апелляциям (`final_result`).
- `--model-mode` отражает способ размещения модели (`local`, `external_api`, `hybrid`). Оценки, полученные в режиме `mock`, к официальной выгрузке не допускаются.
- Номера реплик во внутреннем формате хранятся с `0`, а при экспорте в `evidence_turns` ровно один раз преобразуются в 1-based нумерацию по полному исходному транскрипту (включая `client`, `operator`, `bot`, `system`). Неуспешные оценки (`status="failed"`) выгружаются как `status: "error"` с `criteria: []`, `score: null` и текстом ошибки.
