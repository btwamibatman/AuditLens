from app.core.db import Base, SessionLocal, engine, import_all_models
from app.features.appeals import service as appeals_service
from app.features.appeals.schemas import AppealCreate, AppealReview
from app.features.checklists import service as checklists_service
from app.features.checklists.schemas import ChecklistConfig
from app.features.conversations import service as conv_service
from app.features.conversations.schemas import ConversationRecord
from app.features.evaluations import service as eval_service

RECORD = ConversationRecord(
    conversation_id="t-ru-001",
    channel="agent chat",
    language="RU",
    transcript=[
        {"timestamp": "00:01", "speaker": "bot", "text": "Здравствуйте! Чем могу помочь?"},
        {"timestamp": "00:05", "speaker": "client", "text": "Не пришёл вывод средств"},
        {"timestamp": "00:20", "speaker": "operator", "text": "Добрый день, меня зовут Алия."},
    ],
    audio_url=None,
)


def setup_module():
    import_all_models()
    Base.metadata.create_all(engine)


def test_checklist_default_and_update():
    with SessionLocal() as db:
        active = checklists_service.get_active(db)
        assert active.is_active and len(active.config["criteria"]) == 8

        cfg_dict = dict(active.config)
        cfg_dict["criteria"][-1] = {
            "id": "new_rule",
            "name": "Новый критерий",
            "description": "Оператор предложил полезную ссылку",
            "weight": 5,
            "answer_type": "binary",
        }
        cfg = ChecklistConfig.model_validate(cfg_dict)
        from app.features.checklists.schemas import ChecklistUpdate

        upd = checklists_service.update_checklist(db, active.id, ChecklistUpdate(config=cfg))
        assert upd.version >= 2
        assert upd.config["criteria"][-1]["id"] == "new_rule"


def test_conversation_and_evaluation_flow():
    with SessionLocal() as db:
        imp = conv_service.upsert_records(db, "TEST", [RECORD])
        assert imp.total == 1

        ev = eval_service.evaluate(db, "t-ru-001")
        assert ev.status == "done"
        assert ev.model == "mock"
        assert ev.total_score is not None

        crit = ev.final_result["criteria"]
        assert len(crit) == 8
        first_ev = crit[0]["evidence"][0]
        assert first_ev["message_index"] == 2
        assert first_ev["verified"] is True
        assert first_ev["timestamp"] == "00:20"


def test_appeal_and_review_flow():
    with SessionLocal() as db:
        conv_service.upsert_records(db, "TEST", [RECORD])
        ev = eval_service.evaluate(db, "t-ru-001")

        appeal = appeals_service.create_appeal(
            db,
            AppealCreate(
                evaluation_id=ev.id,
                criterion_id="contact",
                comment="Оператор поздоровался в 00:20",
            ),
        )
        assert appeal.status == "pending"

        rev_appeal, rev_ev = appeals_service.review_appeal(
            db,
            appeal.id,
            AppealReview(
                decision="change",
                reviewer_comment="Принято проверяющим",
                new_score=1,
                new_is_na=False,
            ),
        )
        assert rev_appeal.status == "overturned"
        target = next(c for c in rev_ev.final_result["criteria"] if c["criterion_id"] == "contact")
        assert target["source"] == "reviewer"
        assert target["score"] == 1
