import json

from app.core.config import ROOT_DIR

DATASET_PATH = ROOT_DIR / "docs" / "invoke.json"
CHECKLIST_PATH = ROOT_DIR / "checklist.json"
IDS = {
    "contact",
    "discovery",
    "identification",
    "consultation",
    "empathy",
    "dialogue",
    "closure",
    "critical",
}


def load_conversation(conversation_id: str) -> dict | None:
    data = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    if data.get("isSuccess") is not True:
        raise ValueError("Dataset is not available")
    return next(
        (r for r in data["data"]["records"] if r["conversation_id"] == conversation_id), None
    )


def load_checklist() -> dict:
    checklist = json.loads(CHECKLIST_PATH.read_text(encoding="utf-8"))
    rules = checklist["criteria"]
    if len(rules) != 8 or {rule["id"] for rule in rules} != IDS:
        raise ValueError("Checklist must contain all eight criteria exactly once")
    for rule in rules:
        if not rule.get("allowed") or not rule.get("instructions") or rule["weight"] < 0:
            raise ValueError("Invalid checklist criterion")
    return checklist
