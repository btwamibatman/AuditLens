# Регламент запуска и сдачи результатов

> Подробное техническое руководство. Краткий обзор проекта — в [README](../README.md).
> Требования к формату — в `docs/CQA_Student_Guide_Appendix_Results.pdf`.

## Лимиты бесплатного тарифа Gemini

На Free Tier у `gemini-3.5-flash-lite` действует лимит **15 запросов в минуту**. При
`LLM_BATCH_CONCURRENCY=4` полный DEV-прогон упёрся в лимит: 26 из 65 оценок получили
`429` и были сохранены как ошибки. Для бесплатного ключа перед batch задайте в `.env`
`LLM_BATCH_CONCURRENCY=1` (или 2) и перезапустите процесс. Невалидный ответ модели
вызывает один повторный запрос, поэтому на диалог может уйти больше одного вызова.

Если часть оценок всё же упала по лимиту, их можно досчитать последовательно:

```bash
cd backend
.venv/Scripts/python.exe scripts/complete_dev_evaluation.py
```

Скрипт берёт `status: "error"` из текущего `results/dev/results.json`, оценивает эти
диалоги с паузой 4.5 с и сохраняет в `backend/data/exports/dev-full/evaluation-ids.json`
**последнюю** оценку каждого DEV-диалога для того же чек-листа. Перед экспортом
убедитесь, что в БД нет посторонних более поздних оценок этих диалогов.
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
