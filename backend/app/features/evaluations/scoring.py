"""Детерминированный подсчёт итогов. LLM выставляет только баллы по критериям — математика здесь.

Правила:
* normalized = (score - min) / (max - min)
* вес N/A-критериев перераспределяется пропорционально между применимыми:
  effective_weight = weight / sum(weights применимых) * total_scale
* total = sum(normalized * effective_weight), затем округление по правилам чек-листа
* грубая ошибка (critical_violation у is_critical критерия) отмечается отдельно;
  при policy=zero_total итог обнуляется, при flag_only — только флаг
Функция чистая: её же используем для пересчёта после решения по апелляции.
"""

from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal

from app.features.checklists.schemas import ScoringRules
from app.features.evaluations.schemas import CriterionResult, EvaluationResult, SectionResult

_ROUNDING = {"half_up": ROUND_HALF_UP, "floor": ROUND_FLOOR, "ceil": ROUND_CEILING}


def round_score(value: float, rules: ScoringRules) -> float:
    if rules.rounding == "none":
        return value
    quant = Decimal(1).scaleb(-rules.rounding_digits)  # 1, 0.1, 0.01 ...
    rounded = Decimal(str(value)).quantize(quant, rounding=_ROUNDING[rules.rounding])
    return float(rounded)


def _normalized(c: CriterionResult) -> float:
    span = c.scale_max - c.scale_min
    score = min(max(c.score if c.score is not None else c.scale_min, c.scale_min), c.scale_max)
    return (score - c.scale_min) / span


def compute_totals(
    criteria: list[CriterionResult], rules: ScoringRules, summary: str = ""
) -> EvaluationResult:
    scored = [c for c in criteria if c.status == "scored"]
    total_weight = sum(c.weight for c in scored)

    for c in criteria:
        if c.status != "scored" or total_weight == 0:
            c.normalized, c.effective_weight, c.points = None, 0.0, 0.0
            continue
        c.normalized = round(_normalized(c), 6)
        c.effective_weight = round(c.weight / total_weight * rules.total_scale, 4)
        c.points = round(c.normalized * c.effective_weight, 4)

    total_raw = sum(c.points for c in scored) if total_weight > 0 else None

    # Секции: процент внутри секции (со своим перераспределением N/A)
    sections: list[SectionResult] = []
    for name in dict.fromkeys(c.section for c in criteria if c.section):
        sec = [c for c in scored if c.section == name]
        weight = sum(c.weight for c in sec)
        if weight == 0:
            sections.append(SectionResult(section=name, score=None, points=0, max_points=0))
            continue
        pct = sum(_normalized(c) * c.weight for c in sec) / weight * 100
        sections.append(
            SectionResult(
                section=name,
                score=round_score(pct, rules),
                points=round(sum(c.points for c in sec), 4),
                max_points=round(sum(c.effective_weight for c in sec), 4),
            )
        )

    critical = [c.criterion_id for c in criteria if c.is_critical and c.critical_violation]
    total_before = round_score(total_raw, rules) if total_raw is not None else None
    total = total_before
    if critical and rules.critical_policy == "zero_total":
        total = 0.0

    return EvaluationResult(
        criteria=criteria,
        sections=sections,
        total_raw=round(total_raw, 4) if total_raw is not None else None,
        total_before_critical=total_before,
        total=total,
        has_critical_error=bool(critical),
        critical_criteria=critical,
        summary=summary,
    )
