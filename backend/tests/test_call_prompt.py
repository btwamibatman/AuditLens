"""Offline checks of call instructions and the unchanged evaluation contract."""

import json
from pathlib import Path

import pytest

from app.features.checklists.defaults import default_checklist_config
from app.features.checklists.schemas import Criterion, ScaleLevel
from app.features.conversations.models import Conversation
from app.features.evaluations import service
from app.features.evaluations.llm import LLMResult
from app.features.evaluations.prompt import build_response_schema, build_system_instruction

TRANSCRIPT = [
    {"timestamp": "2026-11-07T23:59:57+05:00", "speaker": "bot", "text": "Welcome"},
    {"timestamp": "2026-11-07T23:59:58+05:00", "speaker": "client", "text": "What are the fees?"},
    {"timestamp": "2026-11-07T23:59:59+05:00", "speaker": "system", "text": "Operator joined"},
    {
        "timestamp": "2026-11-08T00:00:05+05:00",
        "speaker": "operator",
        "text": "Let me check the fees.",
    },
]


def conversation(channel="voice call", language="RU", audio_url=None):
    return Conversation(
        id="call-prompt-test",
        channel=channel,
        language=language,
        transcript=TRANSCRIPT,
        audio_url=audio_url,
    )


@pytest.mark.parametrize("channel", ["voice call", "VOICE CALL", "call"])
def test_calls_receive_spoken_communication_and_evidence_limits(channel):
    config = default_checklist_config()
    original_config = config.model_dump(mode="json")
    preview = service.build_prompt(conversation(channel), config)
    assert "# Voice-call assessment (transcript only)" in preview.system_instruction
    assert "logical turn-taking" in preview.system_instruction
    assert "punctuation or capitalization" in preview.system_instruction
    assert "pronunciation, diction, speech rate, intonation" in preview.system_instruction
    assert "A gap between message timestamps alone does not establish silence" in (
        preview.system_instruction
    )
    assert "Do not invent waiting-time thresholds" in preview.system_instruction
    assert "Absence of audio is not itself a failed criterion or an N/A condition" in (
        preview.system_instruction
    )
    assert preview.response_schema == build_response_schema(config.active_criteria)
    assert preview.llm_criteria == [c.id for c in config.active_criteria]
    assert config.model_dump(mode="json") == original_config


def test_chat_keeps_existing_instructions_and_schema():
    config = default_checklist_config()
    preview = service.build_prompt(conversation("agent chat"), config)
    assert preview.system_instruction == build_system_instruction(config, config.active_criteria)
    assert "# Voice-call assessment" not in preview.system_instruction
    assert preview.response_schema == build_response_schema(config.active_criteria)


@pytest.mark.parametrize("language", ["RU", "KZ", "EN"])
def test_call_evidence_keeps_full_turn_indexes_and_original_iso_timestamps(language):
    preview = service.build_prompt(conversation(language=language), default_checklist_config())
    assert f"Declared language: {language}" in preview.input
    assert "[#0] 2026-11-07T23:59:57+05:00 BOT: Welcome" in preview.input
    assert "[#1] 2026-11-07T23:59:58+05:00 CLIENT: What are the fees?" in preview.input
    assert "[#2] 2026-11-07T23:59:59+05:00 SYSTEM: Operator joined" in preview.input
    assert "[#3] 2026-11-08T00:00:05+05:00 OPERATOR: Let me check the fees." in preview.input


def test_audio_link_does_not_change_transcript_only_capabilities():
    config = default_checklist_config()
    without_audio = service.build_prompt(conversation(), config)
    with_audio = service.build_prompt(
        conversation(audio_url="https://example.test/call.mp3"), config
    )
    assert with_audio == without_audio
    assert "An audio link is not evidence that you have listened to a recording" in (
        with_audio.system_instruction
    )


def test_call_rules_preserve_custom_criteria_and_channel_applicability():
    config = default_checklist_config()
    config.criteria[0].channels = ["chat"]
    config.criteria.append(
        Criterion(
            id="spoken_summary",
            name="Устный итог",
            description="Оператор повторил следующий шаг.",
            weight=3,
            answer_type="scale",
            scale_max=4,
            channels=["call"],
            scale_levels=[ScaleLevel(value=v, description=f"Уровень {v}") for v in [0, 2, 4]],
        )
    )
    before = config.model_dump(mode="json")
    preview = service.build_prompt(conversation(), config)
    assert "contact" in preview.auto_na_criteria and "contact" not in preview.llm_criteria
    assert "spoken_summary" in preview.llm_criteria
    assert "## criterion_id: contact" not in preview.system_instruction
    assert "What to check: Оператор повторил следующий шаг." in preview.system_instruction
    assert "integer scale from 0 to 4" in preview.system_instruction
    assert "  - 2: Уровень 2" in preview.system_instruction
    assert config.model_dump(mode="json") == before


def test_all_five_supplied_calls_receive_transcript_only_guidance():
    path = Path(__file__).resolve().parents[2] / "docs" / "invoke.json"
    records = json.loads(path.read_text(encoding="utf-8"))["data"]["records"]
    calls = [record for record in records if record["channel"] == "voice call"]
    assert len(calls) == 5
    for record in calls:
        conv = Conversation(
            id=record["conversation_id"],
            channel=record["channel"],
            language=record["language"],
            transcript=record["transcript"],
            audio_url=record["audio_url"],
        )
        preview = service.build_prompt(conv, default_checklist_config())
        assert "# Voice-call assessment (transcript only)" in preview.system_instruction
        assert len(preview.llm_criteria) == 8 and preview.auto_na_criteria == []
        for index, turn in enumerate(record["transcript"]):
            assert f"[#{index}] {turn['timestamp']} {turn['speaker'].upper()}: " in preview.input


def test_call_guidance_reaches_provider_and_preserves_na_critical_and_evidence(client, monkeypatch):
    record = {
        "conversation_id": "call-prompt-test",
        "channel": "voice call",
        "language": "EN",
        "transcript": TRANSCRIPT,
        "audio_url": "https://example.test/call.mp3",
    }
    assert client.post("/api/conversations/import", json={"records": [record]}).status_code == 200
    captured = []

    class Provider:
        name = "mock"  # No network or provider deadline thread is needed in this check.
        model = "offline-call-test"

        def generate(self, **kwargs):
            captured.append(kwargs)
            criteria = [
                {
                    "criterion_id": c.id,
                    "applicable": c.id != "discovery",
                    "na_reason": "The client stated the complete question."
                    if c.id == "discovery"
                    else "",
                    "score": 0 if c.id == "discovery" else c.scale_max,
                    "critical_violation": c.id == "critical",
                    "explanation": "OFFLINE TEST ONLY",
                    "evidence": [{"message_index": 3, "quote": "Let me check the fees."}],
                }
                for c in default_checklist_config().criteria
            ]
            return LLMResult(
                model=self.model,
                text=json.dumps(
                    {
                        "criteria": criteria,
                        "summary": "OFFLINE TEST ONLY",
                    }
                ),
            )

    monkeypatch.setattr(service, "get_provider", lambda: Provider())
    response = client.post("/api/evaluations", json={"conversation_id": record["conversation_id"]})
    assert response.status_code == 201 and len(captured) == 1
    assert "# Voice-call assessment (transcript only)" in captured[0]["system_instruction"]
    saved = client.get(f"/api/evaluations/{response.json()['id']}").json()
    assert saved["total_score"] == 100 and saved["has_critical_error"] is True
    assert saved["ai_result"] == saved["final_result"]
    criteria = {c["criterion_id"]: c for c in saved["ai_result"]["criteria"]}
    assert criteria["discovery"]["status"] == "na" and criteria["discovery"]["score"] is None
    assert criteria["critical"]["score"] == 1 and criteria["critical"]["weight"] == 0
    evidence = criteria["contact"]["evidence"][0]
    assert evidence["verified"] is True and evidence["message_index"] == 3
    assert evidence["timestamp"] == TRANSCRIPT[3]["timestamp"]
