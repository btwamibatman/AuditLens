import time

from app.features.evaluations.v1 import data
from app.features.evaluations.v1.prompt import build_prompt
from app.features.evaluations.v1.provider import Provider, ProviderError
from app.features.evaluations.v1.validation import InvalidEvaluation, calculate, validate


def error_result(conversation_id: str, message: str) -> dict:
    return {
        "conversation_id": conversation_id,
        "status": "error",
        "criteria": [],
        "score": None,
        "error": message,
    }


def evaluate(conversation_id: str, provider: Provider) -> tuple[dict, int]:
    try:
        conversation = data.load_conversation(conversation_id)
        if conversation is None:
            return error_result(conversation_id, "Conversation not found"), 404
        checklist = data.load_checklist()
        prompt = build_prompt(conversation, checklist)
    except (OSError, ValueError, KeyError, TypeError):
        return error_result(conversation_id, "Unable to load dataset or checklist"), 500
    for attempt in range(3):
        try:
            criteria = validate(
                provider.evaluate(prompt), checklist, len(conversation["transcript"])
            )
            return {
                "conversation_id": conversation_id,
                "status": "ok",
                "criteria": criteria,
                "score": calculate(criteria, checklist),
            }, 200
        except InvalidEvaluation as exc:
            error = ProviderError(f"Invalid evaluation: {exc}", retryable=True)
        except ProviderError as exc:
            error = exc
        if not error.retryable or attempt == 2:
            return error_result(conversation_id, str(error)), 504 if error.timeout else 502
        time.sleep(0.2 * (2**attempt))
    raise AssertionError("unreachable")
