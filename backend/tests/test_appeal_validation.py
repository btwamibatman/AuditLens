from copy import deepcopy

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.db import Base, import_all_models
from app.core.errors import AppError
from app.features.appeals import service
from app.features.appeals.schemas import AppealCreate, AppealReview
from app.features.checklists.models import Checklist
from app.features.conversations.schemas import ConversationRecord
from app.features.conversations.service import upsert_records
from app.features.evaluations.service import evaluate


@pytest.fixture
def saved_evaluation():
    engine = create_engine("sqlite://")
    import_all_models()
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        upsert_records(
            db,
            "TEST",
            [
                ConversationRecord(
                    conversation_id="appeal-check",
                    transcript=[{"speaker": "operator", "text": "Hello, my name is Alex."}],
                )
            ],
        )
        yield db, evaluate(db, "appeal-check")
    engine.dispose()


def appeal(db, evaluation, criterion):
    return service.create_appeal(
        db,
        AppealCreate(
            evaluation_id=evaluation.id,
            criterion_id=criterion,
            comment="Please review",
        ),
    )


@pytest.mark.parametrize(
    "criterion,changes",
    [
        ("consultation", {"new_score": 13}),
        ("contact", {"new_score": 2}),
        ("contact", {"new_is_na": True}),
        ("consultation", {}),
        ("discovery", {"new_is_na": True, "new_score": 0}),
        ("discovery", {"new_is_na": True, "new_critical_violation": True}),
        ("contact", {"new_score": 1, "new_critical_violation": True}),
        ("critical", {"new_score": 1, "new_critical_violation": False}),
        ("critical", {"new_score": 0, "new_critical_violation": True}),
    ],
)
def test_invalid_decision_leaves_appeal_and_evaluation_unchanged(
    saved_evaluation, criterion, changes
):
    db, ev = saved_evaluation
    pending = appeal(db, ev, criterion)
    original = deepcopy(ev.final_result)
    with pytest.raises(AppError):
        service.review_appeal(
            db,
            pending.id,
            AppealReview(
                decision="change",
                reviewer_comment="Reviewed",
                **changes,
            ),
        )
    # Even a later commit must not accidentally save a partially applied decision.
    db.commit()
    db.expire_all()
    assert pending.status == "pending" and pending.decision is None
    assert pending.reviewer_comment is None
    assert ev.final_result == original and ev.ai_result == original


def test_review_uses_snapshot_instead_of_edited_live_checklist(saved_evaluation):
    db, ev = saved_evaluation
    checklist = db.get(Checklist, ev.checklist_id)
    changed = deepcopy(checklist.config)
    changed["criteria"][3]["scale_levels"].append({"value": 13, "description": "New level"})
    checklist.config = changed
    db.commit()
    pending = appeal(db, ev, "consultation")
    with pytest.raises(AppError, match="Invalid score"):
        service.review_appeal(
            db,
            pending.id,
            AppealReview(
                decision="change",
                reviewer_comment="Reviewed",
                new_score=13,
            ),
        )


def test_valid_review_recalculates_and_preserves_ai_result(saved_evaluation):
    db, ev = saved_evaluation
    original = deepcopy(ev.ai_result)
    pending = appeal(db, ev, "consultation")
    service.review_appeal(
        db,
        pending.id,
        AppealReview(
            decision="change",
            reviewer_comment="Correct next step",
            new_score=15,
        ),
    )
    assert ev.total_score == 15 and ev.ai_result == original
    assert pending.status == "overturned"
    with pytest.raises(AppError, match="already been reviewed"):
        service.review_appeal(
            db,
            pending.id,
            AppealReview(
                decision="confirm",
                reviewer_comment="Again",
            ),
        )


def test_na_can_be_removed_and_critical_does_not_zero_total(saved_evaluation):
    db, ev = saved_evaluation
    pending = appeal(db, ev, "discovery")
    service.review_appeal(
        db,
        pending.id,
        AppealReview(
            decision="change",
            reviewer_comment="Request clear",
            new_is_na=True,
        ),
    )
    pending = appeal(db, ev, "discovery")
    service.review_appeal(
        db,
        pending.id,
        AppealReview(
            decision="change",
            reviewer_comment="Clarification was needed",
            new_score=1,
        ),
    )
    criterion = next(c for c in ev.final_result["criteria"] if c["criterion_id"] == "discovery")
    assert criterion["na_reason"] == "" and ev.total_score == 15
    pending = appeal(db, ev, "critical")
    service.review_appeal(
        db,
        pending.id,
        AppealReview(
            decision="change",
            reviewer_comment="Violation confirmed",
            new_score=1,
            new_critical_violation=True,
        ),
    )
    assert ev.total_score == 15 and ev.has_critical_error


def test_confirm_preserves_final_result(saved_evaluation):
    db, ev = saved_evaluation
    original = deepcopy(ev.final_result)
    pending = appeal(db, ev, "contact")
    service.review_appeal(
        db,
        pending.id,
        AppealReview(
            decision="confirm",
            reviewer_comment="AI was correct",
        ),
    )
    assert pending.status == "confirmed" and ev.final_result == original
