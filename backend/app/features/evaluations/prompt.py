"""Сборка промпта и JSON-схемы ответа из конфигурации чек-листа.

Ничего не захардкожено под конкретные критерии: всё, что знает модель о правилах оценки,
берётся из ChecklistConfig. Изменили критерий в UI → следующий вызов получит новый промпт.
"""

from app.features.checklists.schemas import ChecklistConfig, Criterion

LANGUAGE_NAMES = {"ru": "Russian", "en": "English", "kk": "Kazakh", "kz": "Kazakh"}

SYSTEM_TEMPLATE = """\
You are a senior Quality Assurance analyst at a contact center. You evaluate the work of a \
human support OPERATOR in one conversation against a configurable checklist, exactly like a \
strict, consistent human QA reviewer would.

# Input format
The transcript is a numbered list of messages: `[#index] timestamp SPEAKER: text`.
Speakers: CLIENT (customer), OPERATOR (the human agent being evaluated), BOT (automated \
assistant), SYSTEM (technical events: transfers, joins, call metadata).
Conversations may be in Russian, Kazakh or English (or mixed). Understand them natively; do \
not penalize the operator for the language as long as it matches the client.

# Evaluation rules
1. Evaluate ONLY the OPERATOR's behaviour. BOT and SYSTEM messages are context only: an action \
performed by the bot is NOT credited to the operator, but may make a criterion N/A when the \
criterion's N/A rule says so.
2. Judge strictly by what is in the transcript. Never assume actions that are not visible. \
If something is ambiguous, choose the score a careful human reviewer would defend.
3. For each criterion follow its description, scale levels, N/A rule and critical-error rule \
literally. A criterion may be marked not applicable (applicable=false) ONLY if it explicitly \
allows N/A and its N/A rule is satisfied; then give `na_reason` and set score to the scale minimum.
For N/A, `evidence` must not be empty: cite the CLIENT/BOT/SYSTEM/OPERATOR messages that \
demonstrate the condition, and explain how they satisfy the criterion's N/A rule. Do not \
substitute a generic restatement of the rule for evidence from this conversation.
4. `score` must be an integer within the criterion scale. For binary criteria: 1 = requirement \
met, 0 = not met.
Check every required part of a criterion. "A or B, and C" requires C together with at least \
one of A or B. A polite phrase does not prove that another required action occurred. A \
client's confirmation or a bot's action cannot replace an action required of the OPERATOR.
5. `critical_violation` = true ONLY for criteria that define a critical-error rule and only when \
that rule is clearly violated. Otherwise false.
6. Evidence: list the message(s) that prove your decision. `message_index` must be the [#index] \
of the message, and `quote` must be an EXACT verbatim fragment (5-25 words) copied from that \
message in its original language. Prefer OPERATOR messages; quote CLIENT/BOT/SYSTEM messages \
when they are the proof (e.g. for N/A).
7. If a required action is MISSING, there is nothing to quote: leave `evidence` empty or cite \
the closest relevant message, and set `checked_range` to the span of message indexes you \
inspected (e.g. the operator's first messages for a missing greeting).
Every scored criterion needs at least one exact supporting quote or a `checked_range`. \
The range must satisfy 0 <= from_index <= to_index < Messages; never reverse its endpoints. \
A range alone cannot justify N/A: N/A always needs an exact supporting quote and a non-empty reason.
8. `explanation`: 1-3 concise sentences in {explanation_language} explaining why this score was \
given, referring to concrete behaviour. Explanation of N/A must state the reason.
9. Return exactly one entry per criterion listed below, using the given criterion_id values, \
and a short overall `summary` (2-3 sentences in {explanation_language}).
{company_context}
# Checklist
{criteria_block}
"""


def _criterion_block(c: Criterion) -> str:
    lines = [f"## criterion_id: {c.id}", f"Name: {c.name}"]
    if c.section:
        lines.append(f"Section: {c.section}")
    lines.append(f"What to check: {c.description}")
    if c.answer_type == "binary":
        lines.append("Answer type: binary (1 = yes / met, 0 = no / not met)")
    else:
        lines.append(f"Answer type: integer scale from {c.scale_min} to {c.scale_max}")
        for level in sorted(c.scale_levels, key=lambda lv: lv.value):
            lines.append(f"  - {level.value}: {level.description}")
    if c.na_allowed:
        lines.append(f"N/A allowed when: {c.na_rule}")
    else:
        lines.append("N/A NOT allowed: always score this criterion.")
    if c.is_critical:
        lines.append(f"Critical error (set critical_violation=true) when: {c.critical_rule}")
    return "\n".join(lines)


def build_system_instruction(config: ChecklistConfig, criteria: list[Criterion]) -> str:
    language = LANGUAGE_NAMES.get(config.explanation_language.lower(), config.explanation_language)
    company = (
        f"\n# Company context\n{config.evaluator_notes.strip()}\n" if config.evaluator_notes else ""
    )
    return SYSTEM_TEMPLATE.format(
        explanation_language=language,
        company_context=company,
        criteria_block="\n\n".join(_criterion_block(c) for c in criteria),
    )


def render_transcript(transcript: list[dict]) -> str:
    lines = []
    for i, msg in enumerate(transcript):
        speaker = str(msg.get("speaker", "")).upper()
        ts = msg.get("timestamp") or ""
        text = " ".join(str(msg.get("text", "")).split())
        lines.append(f"[#{i}] {ts} {speaker}: {text}")
    return "\n".join(lines)


def build_input(
    *, conversation_id: str, channel: str, language: str, transcript: list[dict]
) -> str:
    return (
        f"Conversation ID: {conversation_id}\n"
        f"Channel: {channel}\n"
        f"Declared language: {language}\n"
        f"Messages: {len(transcript)}\n\n"
        f"Transcript:\n{render_transcript(transcript)}\n\n"
        "Evaluate the operator against every criterion of the checklist and return JSON."
    )


def build_response_schema(criteria: list[Criterion]) -> dict:
    """JSON Schema для structured output. criterion_id ограничен enum'ом текущего чек-листа."""
    return {
        "type": "object",
        "properties": {
            "criteria": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "criterion_id": {"type": "string", "enum": [c.id for c in criteria]},
                        "applicable": {"type": "boolean"},
                        "na_reason": {"type": "string"},
                        "score": {"type": "integer"},
                        "critical_violation": {"type": "boolean"},
                        "explanation": {"type": "string"},
                        "evidence": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "message_index": {"type": "integer"},
                                    "quote": {"type": "string"},
                                },
                                "required": ["message_index", "quote"],
                            },
                        },
                        "checked_range": {
                            "type": "object",
                            "properties": {
                                "from_index": {"type": "integer"},
                                "to_index": {"type": "integer"},
                            },
                            "required": ["from_index", "to_index"],
                        },
                    },
                    "required": [
                        "criterion_id",
                        "applicable",
                        "score",
                        "critical_violation",
                        "explanation",
                        "evidence",
                    ],
                },
            },
            "summary": {"type": "string"},
        },
        "required": ["criteria", "summary"],
    }
