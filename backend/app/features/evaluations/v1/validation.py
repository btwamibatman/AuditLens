import math


class InvalidEvaluation(ValueError):
    pass


def validate(payload: object, checklist: dict, turn_count: int) -> list[dict]:
    if not isinstance(payload, dict) or not isinstance(payload.get("criteria"), list):
        raise InvalidEvaluation("criteria must be an array")
    rules = {rule["id"]: rule for rule in checklist["criteria"]}
    seen = set()
    for item in payload["criteria"]:
        if not isinstance(item, dict) or not isinstance(item.get("criterion_id"), str):
            raise InvalidEvaluation("invalid criterion")
        criterion_id = item["criterion_id"]
        if criterion_id not in rules or criterion_id in seen:
            raise InvalidEvaluation(f"unknown or duplicate criterion: {criterion_id}")
        seen.add(criterion_id)
        if "value" not in item or not any(
            (
                (type(item["value"]) is type(allowed))
                or (type(item["value"]) in (int, float) and type(allowed) in (int, float))
            )
            and item["value"] == allowed
            for allowed in rules[criterion_id]["allowed"]
        ):
            raise InvalidEvaluation(f"invalid value for {criterion_id}")
        if not isinstance(item.get("rationale"), str) or not item["rationale"].strip():
            raise InvalidEvaluation(f"missing rationale for {criterion_id}")
        evidence = item.get("evidence_turns")
        if not isinstance(evidence, list) or any(
            type(index) is not int or not 1 <= index <= turn_count for index in evidence
        ):
            raise InvalidEvaluation(f"invalid evidence_turns for {criterion_id}")
    if seen != rules.keys():
        raise InvalidEvaluation("missing criteria")
    return [
        {key: item[key] for key in ("criterion_id", "value", "rationale", "evidence_turns")}
        for item in payload["criteria"]
    ]


def calculate(criteria: list[dict], checklist: dict) -> dict:
    rules = {rule["id"]: rule for rule in checklist["criteria"]}
    numerator = denominator = 0.0
    critical = None
    for item in criteria:
        value = item["value"]
        rule = rules[item["criterion_id"]]
        if item["criterion_id"] == "critical":
            critical = value
        elif value is not None:
            maximum = max((v for v in rule["allowed"] if type(v) is int), default=1)
            numerator += rule["weight"] * (int(value) if type(value) is bool else value / maximum)
            denominator += rule["weight"]
    if not denominator or type(critical) is not bool:
        raise InvalidEvaluation("score cannot be calculated")
    final = math.floor(10000 * numerator / denominator + 0.5) / 100
    if not 0 <= final <= 100:
        raise InvalidEvaluation("score out of range")
    return {"final_score": final, "critical_flag": critical}
