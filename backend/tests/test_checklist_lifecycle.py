import importlib.util
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import Base, get_db, import_all_models
from app.features.checklists.defaults import DEFAULT_CHECKLIST_NAME, default_checklist_config
from app.features.checklists.models import Checklist
from app.features.checklists.schemas import ChecklistConfig
from app.features.conversations.schemas import ConversationRecord
from app.features.conversations.service import upsert_records
from app.features.evaluations.models import Evaluation
from app.main import app

LEGACY_DEFAULT_CHECKLIST: dict = {
    "explanation_language": "ru",
    "evaluator_notes": (
        "Компания — онлайн-брокер (Freedom Broker). Клиенты обращаются по счетам, "
        "пополнению/выводу средств, торговле, документам и тарифам. Оценивается только работа "
        "живого оператора (speaker=operator). Реплики бота и системные события — контекст: если "
        "бот уже выполнил действие (например, приветствие или идентификацию), это не "
        "засчитывается оператору, но может делать критерий N/A, если правило N/A "
        "это предусматривает."
    ),
    "scoring": {
        "total_scale": 100,
        "rounding": "half_up",
        "rounding_digits": 0,
        "critical_policy": "zero_total",
    },
    "criteria": [
        {
            "id": "greeting",
            "name": "Приветствие и представление",
            "section": "Открытие",
            "description": (
                "Оператор в первой своей реплике вежливо приветствует клиента и представляется "
                "(имя и/или компания)."
            ),
            "weight": 10,
            "answer_type": "binary",
            "na_allowed": True,
            "na_rule": (
                "Оператор подключился к уже идущему диалогу после передачи от другого оператора, "
                "и приветствие было ранее."
            ),
        },
        {
            "id": "identification",
            "name": "Идентификация / верификация клиента",
            "section": "Открытие",
            "description": (
                "Перед раскрытием данных по счёту или выполнением операций оператор "
                "идентифицирует клиента (ФИО, номер счёта, кодовое слово, телефон и т.п.)."
            ),
            "weight": 10,
            "answer_type": "binary",
            "na_allowed": True,
            "na_rule": (
                "Запрос общий и не требует доступа к персональным данным или счёту клиента, "
                "либо клиент уже верифицирован ботом/системой (видно в системных событиях)."
            ),
            "is_critical": True,
            "critical_rule": (
                "Оператор раскрыл конфиденциальные данные счёта или провёл операцию "
                "без какой-либо идентификации клиента."
            ),
        },
        {
            "id": "needs_discovery",
            "name": "Выявление потребности",
            "section": "Решение",
            "description": (
                "Оператор понимает суть запроса: задаёт уточняющие вопросы при неясности, "
                "не отвечает «мимо» вопроса клиента."
            ),
            "weight": 15,
            "answer_type": "scale",
            "scale_min": 0,
            "scale_max": 2,
            "scale_levels": [
                {"value": 0, "description": "Запрос не понят или проигнорирован."},
                {"value": 1, "description": "Понят частично, нужные уточнения пропущены."},
                {"value": 2, "description": "Запрос понят полностью, уточнения заданы по делу."},
            ],
        },
        {
            "id": "accuracy",
            "name": "Корректность и полнота информации",
            "section": "Решение",
            "description": (
                "Информация оператора точная, полная и непротиворечивая; оператор не вводит "
                "клиента в заблуждение и даёт конкретику (сроки, шаги, условия)."
            ),
            "weight": 25,
            "answer_type": "scale",
            "scale_min": 0,
            "scale_max": 3,
            "scale_levels": [
                {"value": 0, "description": "Информация неверна или вводит в заблуждение."},
                {"value": 1, "description": "Существенные неточности или пропуски."},
                {"value": 2, "description": "В целом верно, мелкие пропуски."},
                {"value": 3, "description": "Полно, точно и конкретно."},
            ],
            "is_critical": True,
            "critical_rule": (
                "Оператор дал явно ложную информацию, способную привести к финансовым потерям "
                "клиента (неверные реквизиты, сроки вывода, условия сделки)."
            ),
        },
        {
            "id": "resolution",
            "name": "Решение вопроса / следующие шаги",
            "section": "Решение",
            "description": (
                "Вопрос решён в рамках диалога, либо оператор чётко зафиксировал следующие шаги: "
                "что произойдёт, кто и в какой срок свяжется, номер обращения."
            ),
            "weight": 15,
            "answer_type": "scale",
            "scale_min": 0,
            "scale_max": 2,
            "scale_levels": [
                {"value": 0, "description": "Вопрос не решён, следующих шагов нет."},
                {"value": 1, "description": "Частично: шаги размыты, без сроков/ответственного."},
                {"value": 2, "description": "Решено или шаги и сроки зафиксированы чётко."},
            ],
        },
        {
            "id": "politeness",
            "name": "Вежливость и эмпатия",
            "section": "Коммуникация",
            "description": (
                "Оператор вежлив, корректен, проявляет эмпатию к проблеме клиента, не спорит "
                "и не перекладывает вину; язык ответа соответствует языку клиента."
            ),
            "weight": 10,
            "answer_type": "scale",
            "scale_min": 0,
            "scale_max": 2,
            "scale_levels": [
                {"value": 0, "description": "Грубость, пренебрежение, пассивная агрессия."},
                {"value": 1, "description": "Нейтрально-формально, без эмпатии где она нужна."},
                {"value": 2, "description": "Вежливо и эмпатично на протяжении всего диалога."},
            ],
            "is_critical": True,
            "critical_rule": "Оператор оскорбляет клиента или использует ненормативную лексику.",
        },
        {
            "id": "compliance",
            "name": "Соблюдение регуляторных требований",
            "section": "Коммуникация",
            "description": (
                "Оператор не даёт индивидуальных инвестиционных рекомендаций, не гарантирует "
                "доходность, не обещает невозможного и не запрашивает пароли/коды из SMS."
            ),
            "weight": 10,
            "answer_type": "binary",
            "is_critical": True,
            "critical_rule": (
                "Оператор гарантировал доходность, дал прямую рекомендацию купить/продать "
                "актив или запросил пароль/одноразовый код."
            ),
        },
        {
            "id": "closing",
            "name": "Завершение диалога",
            "section": "Закрытие",
            "description": ("Оператор уточняет, остались ли вопросы, и корректно прощается."),
            "weight": 5,
            "answer_type": "binary",
            "na_allowed": True,
            "na_rule": (
                "Диалог оборван клиентом или технически (клиент перестал отвечать / связь "
                "прервалась) до момента, когда завершение было уместно."
            ),
        },
    ],
}


def _load_upgrade_migration():
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "20261107_2100_6f4d8c9a1b20_upgrade_legacy_default_checklist.py"
    )
    spec = importlib.util.spec_from_file_location("migration_6f4d8c9a1b20", migration_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_legacy_migration_upgrades_only_untouched_default_and_keeps_snapshots():
    engine = create_engine("sqlite://")
    import_all_models()
    Base.metadata.create_all(engine)

    legacy_cfg = ChecklistConfig.model_validate(LEGACY_DEFAULT_CHECKLIST).model_dump(mode="json")
    edited_cfg = deepcopy(legacy_cfg)
    edited_cfg["criteria"][0]["description"] = "Пользовательское изменение"

    with Session(engine, expire_on_commit=False) as db:
        untouched = Checklist(
            name=DEFAULT_CHECKLIST_NAME,
            description="Стартовая конфигурация из 8 критериев",
            version=1,
            is_active=True,
            config=deepcopy(legacy_cfg),
        )
        edited = Checklist(
            name=DEFAULT_CHECKLIST_NAME,
            description="Стартовая конфигурация из 8 критериев",
            version=1,
            is_active=True,
            config=deepcopy(edited_cfg),
        )
        db.add_all([untouched, edited])
        db.flush()

        old_ev = Evaluation(
            conversation_id="conv-legacy",
            checklist_id=untouched.id,
            checklist_version=1,
            checklist_snapshot=deepcopy(legacy_cfg),
            status="done",
            total_score=80.0,
        )
        db.add(old_ev)
        db.commit()

    migration = _load_upgrade_migration()
    with engine.begin() as conn, patch.object(migration.op, "get_bind", return_value=conn):
        migration.upgrade()

    expected_cfg = default_checklist_config().model_dump(mode="json")
    with Session(engine) as db:
        upgraded = db.get(Checklist, untouched.id)
        kept_edited = db.get(Checklist, edited.id)
        saved_ev = db.get(Evaluation, old_ev.id)

        assert upgraded is not None
        assert upgraded.version == 2
        assert [c["id"] for c in upgraded.config["criteria"]] == [
            "contact",
            "discovery",
            "identification",
            "consultation",
            "empathy",
            "dialogue",
            "closure",
            "critical",
        ]
        assert upgraded.config == expected_cfg

        assert kept_edited is not None
        assert kept_edited.version == 1
        assert kept_edited.config == edited_cfg

        assert saved_ev is not None
        assert saved_ev.checklist_version == 1
        assert saved_ev.checklist_snapshot == legacy_cfg

    engine.dispose()


def test_checklist_endpoints_do_not_duplicate_and_preserve_evaluation_snapshots():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    import_all_models()
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        with session_factory() as db:
            upsert_records(
                db,
                "DEV",
                [
                    ConversationRecord(
                        conversation_id="b1-conv-1",
                        channel="agent chat",
                        language="RU",
                        transcript=[
                            {
                                "timestamp": "00:05",
                                "speaker": "operator",
                                "text": "Здравствуйте! Меня зовут Алия.",
                            }
                        ],
                    )
                ],
            )

        client = TestClient(app)

        first_list = client.get("/api/checklists").json()
        second_list = client.get("/api/checklists").json()
        active = client.get("/api/checklists/active").json()
        assert len(first_list) == 1
        assert len(second_list) == 1
        assert active["id"] == first_list[0]["id"]
        assert [c["id"] for c in active["config"]["criteria"]] == [
            "contact",
            "discovery",
            "identification",
            "consultation",
            "empathy",
            "dialogue",
            "closure",
            "critical",
        ]

        # Первая оценка сохраняет снимок версии 1
        ev_v1 = client.post(
            "/api/evaluations", json={"conversation_id": "b1-conv-1"}
        ).json()
        assert ev_v1["checklist_id"] == active["id"]
        assert ev_v1["checklist_version"] == 1

        # Создаём второй чек-лист из /default-config, меняем критерий и проверяем версию
        tpl = client.get("/api/checklists/default-config").json()
        custom_created = client.post(
            "/api/checklists",
            json={"name": "Custom v1", "description": "Второй чек-лист", "config": tpl},
        ).json()
        assert custom_created["is_active"] is False
        assert custom_created["version"] == 1

        edited_tpl = deepcopy(tpl)
        edited_tpl["criteria"][0]["name"] = "Приветствие (обновлено)"
        custom_v2 = client.put(
            f"/api/checklists/{custom_created['id']}",
            json={"config": edited_tpl},
        ).json()
        assert custom_v2["version"] == 2

        # Оценка с явно выбранным checklist_id использует именно его и его версию
        ev_custom = client.post(
            "/api/evaluations",
            json={"conversation_id": "b1-conv-1", "checklist_id": custom_v2["id"]},
        ).json()
        assert ev_custom["checklist_id"] == custom_v2["id"]
        assert ev_custom["checklist_version"] == 2
        assert ev_custom["final_result"]["criteria"][0]["name"] == "Приветствие (обновлено)"

        # При этом старая оценка сохраняет свой снимок и прежнее имя критерия
        ev_v1_reloaded = client.get(f"/api/evaluations/{ev_v1['id']}").json()
        assert ev_v1_reloaded["checklist_version"] == 1
        assert ev_v1_reloaded["final_result"]["criteria"][0]["name"] == "Установление контакта"
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()
