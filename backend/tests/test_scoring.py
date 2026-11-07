from app.features.checklists.defaults import default_checklist_config
from app.features.checklists.schemas import ScoringRules
from app.features.evaluations.prompt import build_response_schema, build_system_instruction
from app.features.evaluations.schemas import CriterionResult
from app.features.evaluations.scoring import compute_totals, round_score


def crit(cid, weight, score, *, smax=1, status="scored", section=None, critical=False, viol=False):
    return CriterionResult(
        criterion_id=cid,
        name=cid,
        section=section,
        answer_type="binary" if smax == 1 else "scale",
        weight=weight,
        scale_min=0,
        scale_max=smax,
        is_critical=critical,
        status=status,
        score=score if status == "scored" else None,
        critical_violation=viol,
    )


def test_weighted_total_with_scale():
    res = compute_totals([crit("a", 50, 1), crit("b", 50, 1, smax=2)], ScoringRules())
    assert res.total == 75  # 50*1 + 50*0.5


def test_na_weight_is_redistributed():
    res = compute_totals(
        [crit("a", 25, 1), crit("b", 25, 0), crit("c", 50, None, status="na")], ScoringRules()
    )
    a, b, c = res.criteria
    assert a.effective_weight == 50 and b.effective_weight == 50 and c.effective_weight == 0
    assert res.total == 50


def test_critical_zeroes_total_but_keeps_original():
    res = compute_totals(
        [crit("a", 50, 1), crit("b", 50, 0, critical=True, viol=True)], ScoringRules()
    )
    assert res.has_critical_error and res.critical_criteria == ["b"]
    assert res.total_before_critical == 50 and res.total == 0


def test_flag_only_policy_keeps_total():
    rules = ScoringRules(critical_policy="flag_only")
    res = compute_totals([crit("a", 50, 1), crit("b", 50, 0, critical=True, viol=True)], rules)
    assert res.has_critical_error and res.total == 50


def test_sections_and_rounding():
    res = compute_totals(
        [crit("a", 1, 1, section="S"), crit("b", 2, 0, section="S"), crit("c", 1, 1, section="T")],
        ScoringRules(rounding_digits=1),
    )
    s = {x.section: x.score for x in res.sections}
    assert s == {"S": 33.3, "T": 100.0}
    assert round_score(2.5, ScoringRules()) == 3  # half_up, не банковское


def test_all_na_gives_none_total():
    res = compute_totals([crit("a", 10, None, status="na")], ScoringRules())
    assert res.total is None


def test_prompt_is_built_from_config():
    cfg = default_checklist_config()
    cfg.criteria[0].name = "СОВЕРШЕННО НОВЫЙ КРИТЕРИЙ"
    text = build_system_instruction(cfg, cfg.active_criteria)
    assert "СОВЕРШЕННО НОВЫЙ КРИТЕРИЙ" in text
    schema = build_response_schema(cfg.active_criteria)
    enum = schema["properties"]["criteria"]["items"]["properties"]["criterion_id"]["enum"]
    assert enum == [c.id for c in cfg.active_criteria]
