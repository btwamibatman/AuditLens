"""Автоматический прогон контрольного пакета диалогов (PROD / TEST)."""

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT_DIR / "backend"
os.environ["DATABASE_URL"] = f"sqlite:///{(BACKEND_DIR / 'data' / 'app.db').resolve()}"
sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import get_settings  # noqa: E402
from app.core.db import SessionLocal  # noqa: E402
from app.features.checklists.service import get_active  # noqa: E402
from app.features.conversations.schemas import ConversationRecord  # noqa: E402
from app.features.conversations.service import upsert_records  # noqa: E402
from app.features.evaluations.export import _convert, write_atomic  # noqa: E402
from app.features.evaluations.service import evaluate  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="Прогон контрольного пакета PROD")
    parser.add_argument(
        "--file", default=None, help="Путь к выданному файлу с контрольным пакетом"
    )
    parser.add_argument(
        "--url", default=None, help="URL API организаторов для скачивания набора (если дали ссылку)"
    )
    parser.add_argument(
        "--delay", type=float, default=5, help="Пауза между запросами (сек, по умолчанию 4.5)"
    )
    parser.add_argument(
        "--team", default="Revenant", help="Название команды (по умолчанию Revenant)"
    )
    parser.add_argument(
        "--kind", default="prod", choices=["prod", "dev"], help="Тип набора (prod или dev)"
    )
    args = parser.parse_args()

    if not args.file and not args.url:
        print("❌ ОШИБКА: Укажите либо --file <путь_к_файлу>, либо --url <ссылка_api>")
        sys.exit(1)

    if args.url:
        import urllib.request

        print(f"Скачивание датасета по ссылке: {args.url}...")
        docs_dir = ROOT_DIR / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)
        file_path = docs_dir / "prod_downloaded.json"
        req = urllib.request.Request(args.url, headers={"User-Agent": "AuditLens/1.0"})
        with urllib.request.urlopen(req) as resp:
            file_path.write_bytes(resp.read())
        print(f"✓ Сохранено в: {file_path}")
    else:
        file_path = Path(args.file)
        if not file_path.is_absolute():
            file_path = ROOT_DIR / file_path

    if not file_path.exists():
        print(f"❌ ОШИБКА: Файл не найден: {file_path}")
        print("Проверьте правильность пути и повторите запуск.")
        sys.exit(1)

    print("=" * 65)
    print(f"🚀 СТАРТ ПРОГОНА КОНТРОЛЬНОГО ПАКЕТА: {file_path.name}")
    print("=" * 65)

    dataset_raw = json.loads(file_path.read_text(encoding="utf-8"))
    data_section = dataset_raw.get("data", dataset_raw)
    records = data_section.get("records", [])
    group_id = data_section.get("dataset_group_id", "PROD")
    total = len(records)

    if total == 0:
        print("❌ ОШИБКА: В файле не найдено записей диалогов (records пуст)")
        sys.exit(1)

    settings = get_settings()
    print(f"✓ Загружено записей: {total}")
    print(f"✓ Группа датасета: {group_id}")
    print(f"✓ Модель: {settings.gemini_model} (thinking: {settings.gemini_thinking_level})")
    print(f"✓ Команда: {args.team}")
    print(f"✓ Безопасный интервал: {args.delay} с (защита от 15 RPM)\n")

    with SessionLocal() as db:
        print("1. Сохранение диалогов в базу данных...")
        parsed_records = [ConversationRecord.model_validate(r) for r in records]
        upsert_records(db, group_id, parsed_records)
        print(f"   ✓ Диалоги сохранены с группой '{group_id}'")

        checklist = get_active(db)
        print(f"2. Активный чек-лист: ID={checklist.id}, v={checklist.version} ({checklist.name})")

        print(f"\n3. Оценка {total} диалогов через Gemini API:")
        evaluations = []
        errors = 0

        for i, rec in enumerate(records, 1):
            cid = rec["conversation_id"]
            print(f"   [{i}/{total}] {cid}...", end=" ", flush=True)

            success = False
            for attempt in range(1, 4):
                try:
                    t0 = time.time()
                    ev = evaluate(db, cid, checklist_id=checklist.id)
                    elapsed = time.time() - t0
                    if ev.status == "done":
                        crit = " [CRITICAL]" if ev.has_critical_error else ""
                        print(f"OK (балл: {ev.total_score:.2f}{crit}, {elapsed:.1f}с)")
                        evaluations.append(ev)
                        success = True
                        break
                    else:
                        print(f"FAIL: {ev.error}")
                        break
                except Exception as exc:
                    err_msg = str(exc)
                    if "429" in err_msg and attempt < 3:
                        print(f"[429 retry {attempt + 1}]...", end=" ", flush=True)
                        time.sleep(15)
                    else:
                        print(f"ОШИБКА: {exc}")
                        break

            if not success:
                errors += 1

            if i < total:
                time.sleep(args.delay)

        print("\n" + "=" * 65)
        print(f"Итог оценки: успешно {len(evaluations)} из {total} (ошибок: {errors})")

        if evaluations:
            out_dir = ROOT_DIR / "results" / args.kind
            out_dir.mkdir(parents=True, exist_ok=True)
            out_file = out_dir / "results.json"

            payload = {
                "schema_version": "1.0",
                "team_name": args.team.strip(),
                "model": {"mode": "external_api", "name": settings.gemini_model},
                "results": [],
            }

            for rec in records:
                cid = rec["conversation_id"]
                matching_ev = next((e for e in evaluations if e.conversation_id == cid), None)
                if matching_ev and matching_ev.status == "done":
                    payload["results"].append(_convert(matching_ev, rec["transcript"], "final"))

            write_atomic(payload, out_file)
            print("✓ Официальный файл успешно создан:")
            print(f"  👉 {out_file}")
            print(f"  Записано результатов: {len(payload['results'])} диалогов")
            print("=" * 65)
            print("ГОТОВО К СДАЧЕ ОРГАНИЗАТОРАМ!")


if __name__ == "__main__":
    main()
