"""Дооценка оставшихся диалогов DEV с соблюдением лимита 15 RPM (Free Tier)."""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import ROOT_DIR
from app.core.db import SessionLocal
from app.features.checklists.service import get_active
from app.features.evaluations.models import Evaluation
from app.features.evaluations.service import evaluate


def main():
    with open(ROOT_DIR / "results" / "dev" / "results.json", encoding="utf-8") as f:
        current = json.load(f)

    failed_ids = [r["conversation_id"] for r in current["results"] if r["status"] == "error"]
    print(f"Всего диалогов со статусом error из-за 15 RPM: {len(failed_ids)}")
    if not failed_ids:
        print("Все 65 диалогов уже имеют статус 'ok'!")
        return 0

    with SessionLocal() as db:
        checklist = get_active(db)
        checklist_id = checklist.id

    print(f"Используется чек-лист ID={checklist_id} (версия {checklist.version})")
    print("Начинаем последовательную оценку с паузой 5с между запросами...")

    for i, cid in enumerate(failed_ids, 1):
        print(f"  [{i}/{len(failed_ids)}] Оценка {cid}...", end=" ", flush=True)
        try:
            with SessionLocal() as db:
                ev = evaluate(db, cid, checklist_id=checklist_id)
                print(f"OK (score: {ev.total_score}, cost: ~${ev.cost_usd:.5f})")
        except Exception as exc:
            print(f"ERR: {exc}")
        if i < len(failed_ids):
            time.sleep(5)

    print("\nСбор актуальных ID для всех 65 диалогов DEV...")
    with open(ROOT_DIR / "docs" / "invoke.json", encoding="utf-8") as f:
        inv = json.load(f)
    all_dev_ids = [r["conversation_id"] for r in inv["data"]["records"]]

    final_eval_ids = []
    with SessionLocal() as db:
        for cid in all_dev_ids:
            latest = (
                db.query(Evaluation)
                .filter(Evaluation.conversation_id == cid, Evaluation.checklist_id == checklist_id)
                .order_by(Evaluation.created_at.desc())
                .first()
            )
            if latest:
                final_eval_ids.append(latest.id)

    print(f"Найдено {len(final_eval_ids)} актуальных оценок из {len(all_dev_ids)}.")
    out_dir = Path(__file__).resolve().parents[1] / "data" / "exports" / "dev-full"
    out_dir.mkdir(parents=True, exist_ok=True)
    id_file = out_dir / "evaluation-ids.json"
    with open(id_file, "w", encoding="utf-8") as f:
        json.dump(final_eval_ids, f, indent=2)
    print(f"Сохранен файл ID: {id_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

