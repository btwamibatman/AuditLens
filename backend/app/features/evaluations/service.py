"""Пайплайн оценки: диалог + чек-лист → промпт → LLM → валидация → привязка цитат → подсчёт → БД."""

import json
import logging
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.errors import AppError, ExternalServiceError, NotFoundError
from app.features.checklists import service as checklist_service
from app.features.checklists.models import Checklist
from app.features.checklists.schemas import ChecklistConfig, Criterion
from app.features.conversations import service as conversation_service
from app.features.conversations.models import Conversation
from app.features.evaluations import prompt as prompt_builder
from app.features.evaluations.llm import generate_with_retry, get_provider
from app.features.evaluations.models import Evaluation
from app.features.evaluations.schemas import (
    BatchRequest,
    BatchStatus,
    CheckedRange,
    CriterionResult,
    Evidence,
    LLMCriterionOutput,
    LLMEvaluationOutput,
    PromptPreview,
)
from app.features.evaluations.scoring import compute_totals

log = logging.getLogger(__name__)


# ---------------------------------------------------------------- подготовка


def split_criteria(
    config: ChecklistConfig, channel: str
) -> tuple[list[Criterion], list[Criterion]]:
    """(критерии для LLM, критерии авто-N/A по каналу)."""
    kind = "call" if conversation_service.is_call(channel) else "chat"
    llm, auto_na = [], []
    for c in config.active_criteria:
        (llm if kind in c.channels else auto_na).append(c)
    return llm, auto_na


def build_prompt(conv: Conversation, config: ChecklistConfig) -> PromptPreview:
    llm_criteria, auto_na = split_criteria(config, conv.channel)
    return PromptPreview(
        system_instruction=prompt_builder.build_system_instruction(config, llm_criteria),
        input=prompt_builder.build_input(
            conversation_id=conv.id,
            channel=conv.channel,
            language=conv.language,
            transcript=conv.transcript,
        ),
        response_schema=prompt_builder.build_response_schema(llm_criteria),
        llm_criteria=[c.id for c in llm_criteria],
        auto_na_criteria=[c.id for c in auto_na],
    )


# ---------------------------------------------------------------- привязка цитат

_QUOTE_CHARS = "\"'«»“”„`"


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip(_QUOTE_CHARS + " .…").casefold())


def _ground_one(transcript: list[dict], index: int, quote: str) -> Evidence | None:
    """Проверяет цитату в транскрипте; при неверном индексе ищет совпадение по всему тексту."""

    def make(i: int, q: str, verified: bool) -> Evidence:
        msg = transcript[i]
        return Evidence(
            message_index=i,
            quote=q,
            timestamp=str(msg.get("timestamp", "")),
            speaker=str(msg.get("speaker", "")),
            verified=verified,
        )

    in_range = 0 <= index < len(transcript)
    q = _norm(quote)
    if not q:
        return make(index, transcript[index].get("text", ""), True) if in_range else None

    if in_range and q in _norm(transcript[index].get("text", "")):
        return make(index, quote, True)
    for i, msg in enumerate(transcript):  # модель ошиблась индексом
        if q in _norm(msg.get("text", "")):
            return make(i, quote, True)

    # Нечёткое совпадение (модель перефразировала / перевела)
    best_i, best_ratio = -1, 0.0
    for i, msg in enumerate(transcript):
        text = _norm(msg.get("text", ""))
        if not text:
            continue
        ratio = SequenceMatcher(None, q, text).find_longest_match(
            0, len(q), 0, len(text)
        ).size / len(q)
        if ratio > best_ratio:
            best_i, best_ratio = i, ratio
    if best_i >= 0 and best_ratio >= 0.6:
        return make(best_i, quote, True)
    return make(index, quote, False) if in_range else None


def _checked_range(transcript: list[dict], raw: LLMCriterionOutput) -> CheckedRange | None:
    if raw.checked_range is None or not transcript:
        return None
    last = len(transcript) - 1
    a = min(max(raw.checked_range.from_index, 0), last)
    b = min(max(raw.checked_range.to_index, 0), last)
    a, b = min(a, b), max(a, b)
    return CheckedRange(
        from_index=a,
        to_index=b,
        from_timestamp=str(transcript[a].get("timestamp", "")),
        to_timestamp=str(transcript[b].get("timestamp", "")),
    )


# ---------------------------------------------------------------- сборка результата


def _base_result(c: Criterion, **kwargs) -> CriterionResult:
    return CriterionResult(
        criterion_id=c.id,
        name=c.name,
        section=c.section,
        answer_type=c.answer_type,
        weight=c.weight,
        scale_min=c.scale_min,
        scale_max=c.scale_max,
        is_critical=c.is_critical,
        **kwargs,
    )


def build_criterion_result(
    c: Criterion, raw: LLMCriterionOutput | None, transcript: list[dict]
) -> CriterionResult:
    if raw is None:
        # Модель пропустила критерий — ставим минимум и помечаем для ручной проверки
        return _base_result(
            c,
            status="scored",
            score=c.scale_min,
            explanation="Модель не вернула оценку по критерию — требуется ручная проверка.",
            warnings=["missing_in_llm_output"],
        )

    warnings: list[str] = []
    applicable = raw.applicable
    if not applicable and not c.na_allowed:
        applicable = True
        warnings.append("na_not_allowed_forced_scored")

    score = raw.score
    if applicable and not (c.scale_min <= score <= c.scale_max):
        warnings.append(f"score_out_of_range:{score}")
        score = min(max(score, c.scale_min), c.scale_max)

    critical = raw.critical_violation and c.is_critical
    if raw.critical_violation and not c.is_critical:
        warnings.append("critical_flag_ignored_not_critical_criterion")

    evidence = []
    for ev in raw.evidence:
        grounded = _ground_one(transcript, ev.message_index, ev.quote)
        if grounded is None:
            warnings.append(f"evidence_index_out_of_range:{ev.message_index}")
            continue
        if not grounded.verified:
            warnings.append(f"quote_not_found:#{ev.message_index}")
        evidence.append(grounded)

    return _base_result(
        c,
        status="scored" if applicable else "na",
        score=score if applicable else None,
        na_reason="" if applicable else (raw.na_reason or raw.explanation),
        critical_violation=critical,
        explanation=raw.explanation,
        evidence=evidence,
        checked_range=_checked_range(transcript, raw),
        warnings=warnings,
    )


def parse_llm_output(text: str) -> LLMEvaluationOutput:
    cleaned = text.strip()
    if cleaned.startswith("```"):  # на случай, если модель обернула JSON в markdown
        cleaned = re.sub(r"^```(?:json)?|```$", "", cleaned, flags=re.MULTILINE).strip()
    try:
        return LLMEvaluationOutput.model_validate(json.loads(cleaned))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ExternalServiceError(f"LLM returned invalid JSON: {exc}") from exc


# ---------------------------------------------------------------- основной сценарий


def _resolve_checklist(db: Session, checklist_id: int | None) -> Checklist:
    if checklist_id is None:
        return checklist_service.get_active(db)
    return checklist_service.get_checklist(db, checklist_id)


def evaluate(db: Session, conversation_id: str, checklist_id: int | None = None) -> Evaluation:
    conv = conversation_service.get_conversation(db, conversation_id)
    checklist = _resolve_checklist(db, checklist_id)
    config = checklist_service.parse_config(checklist)
    preview = build_prompt(conv, config)

    evaluation = Evaluation(
        conversation_id=conv.id,
        checklist_id=checklist.id,
        checklist_version=checklist.version,
        checklist_snapshot=checklist.config,
        status="pending",
    )
    db.add(evaluation)
    db.commit()

    provider = get_provider()
    evaluation.model = getattr(provider, "model", provider.name)
    try:
        criteria_results: list[CriterionResult] = []
        summary = ""
        if preview.llm_criteria:
            raw_output = None
            for _ in range(2):  # повтор, если модель вернула невалидный JSON
                llm_result, _attempts = generate_with_retry(
                    provider,
                    system_instruction=preview.system_instruction,
                    input_text=preview.input,
                    schema=preview.response_schema,
                )
                evaluation.input_tokens += llm_result.input_tokens
                evaluation.output_tokens += llm_result.output_tokens
                evaluation.thought_tokens += llm_result.thought_tokens
                evaluation.cost_usd += llm_result.cost_usd()
                evaluation.latency_ms += llm_result.latency_ms
                evaluation.raw_response = llm_result.text
                try:
                    raw_output = parse_llm_output(llm_result.text)
                    break
                except ExternalServiceError as exc:
                    log.warning("Invalid LLM JSON for %s: %s", conv.id, exc)
            if raw_output is None:
                raise ExternalServiceError("LLM returned invalid JSON twice")
            by_id = {r.criterion_id: r for r in raw_output.criteria}
            summary = raw_output.summary
        else:
            by_id = {}

        for c in config.active_criteria:
            if c.id in preview.auto_na_criteria:
                criteria_results.append(
                    _base_result(
                        c,
                        status="na",
                        na_reason=f"Критерий не применяется к каналу «{conv.channel}».",
                        source="auto",
                    )
                )
            else:
                criteria_results.append(build_criterion_result(c, by_id.get(c.id), conv.transcript))

        result = compute_totals(criteria_results, config.scoring, summary)
        payload = result.model_dump(mode="json")
        evaluation.ai_result = payload
        evaluation.final_result = payload
        evaluation.total_score = result.total
        evaluation.has_critical_error = result.has_critical_error
        evaluation.status = "done"
    except AppError as exc:
        evaluation.status = "failed"
        evaluation.error = exc.message
        db.commit()
        raise
    db.commit()
    db.refresh(evaluation)
    return evaluation


# ---------------------------------------------------------------- чтение


def get_evaluation(db: Session, evaluation_id: int) -> Evaluation:
    evaluation = db.get(Evaluation, evaluation_id)
    if evaluation is None:
        raise NotFoundError(f"Evaluation {evaluation_id} not found")
    return evaluation


def list_evaluations(
    db: Session, *, conversation_id: str | None = None, checklist_id: int | None = None
) -> list[Evaluation]:
    stmt = select(Evaluation).order_by(Evaluation.id.desc())
    if conversation_id:
        stmt = stmt.where(Evaluation.conversation_id == conversation_id)
    if checklist_id:
        stmt = stmt.where(Evaluation.checklist_id == checklist_id)
    return list(db.scalars(stmt))


# ---------------------------------------------------------------- пакетная оценка

_jobs: dict[str, BatchStatus] = {}
_jobs_lock = threading.Lock()


def resolve_batch_targets(db: Session, req: BatchRequest) -> tuple[list[str], int]:
    checklist = _resolve_checklist(db, req.checklist_id)
    if req.conversation_ids:
        ids = req.conversation_ids
    else:
        ids = [
            c.id
            for c in conversation_service.list_conversations(db, dataset_group=req.dataset_group)
        ]
    if req.only_missing:
        done = set(
            db.scalars(
                select(Evaluation.conversation_id).where(
                    Evaluation.checklist_id == checklist.id,
                    Evaluation.checklist_version == checklist.version,
                    Evaluation.status == "done",
                )
            )
        )
        ids = [i for i in ids if i not in done]
    if not ids:
        raise AppError("No conversations to evaluate")
    return ids, checklist.id


def _evaluate_isolated(conversation_id: str, checklist_id: int) -> tuple[int, float]:
    with SessionLocal() as db:  # отдельная сессия на поток
        ev = evaluate(db, conversation_id, checklist_id)
        return ev.id, ev.cost_usd


def run_batch(
    conversation_ids: list[str], checklist_id: int, job: BatchStatus | None = None, on_progress=None
) -> BatchStatus:
    job = job or BatchStatus(
        job_id=uuid.uuid4().hex[:12],
        status="running",
        total=len(conversation_ids),
        done=0,
        failed=0,
    )
    workers = max(1, get_settings().llm_batch_concurrency)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_evaluate_isolated, cid, checklist_id): cid for cid in conversation_ids
        }
        for future in as_completed(futures):
            cid = futures[future]
            with _jobs_lock:
                try:
                    ev_id, cost = future.result()
                    job.evaluation_ids.append(ev_id)
                    job.total_cost_usd = round(job.total_cost_usd + cost, 6)
                    job.done += 1
                except Exception as exc:  # noqa: BLE001
                    job.failed += 1
                    job.errors[cid] = str(exc)[:500]
            if on_progress:
                on_progress(cid, job)
    job.status = "done" if job.done else "failed"
    return job


def start_batch_job(conversation_ids: list[str], checklist_id: int) -> BatchStatus:
    job = BatchStatus(
        job_id=uuid.uuid4().hex[:12],
        status="running",
        total=len(conversation_ids),
        done=0,
        failed=0,
    )
    with _jobs_lock:
        _jobs[job.job_id] = job

    def _runner():
        try:
            run_batch(conversation_ids, checklist_id, job)
        except Exception as exc:  # noqa: BLE001
            job.status = "failed"
            job.errors["_batch"] = str(exc)

    threading.Thread(target=_runner, daemon=True, name=f"batch-{job.job_id}").start()
    return job


def get_batch_job(job_id: str) -> BatchStatus:
    job = _jobs.get(job_id)
    if job is None:
        raise NotFoundError(f"Batch job {job_id} not found")
    return job
