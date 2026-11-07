"""Пайплайн оценки: диалог + чек-лист → промпт → LLM → валидация → привязка цитат → подсчёт → БД."""

import copy
import json
import logging
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.errors import AppError, BusyError, ConflictError, ExternalServiceError, NotFoundError
from app.features.checklists import service as checklist_service
from app.features.checklists.models import Checklist
from app.features.checklists.schemas import ChecklistConfig, Criterion
from app.features.conversations import service as conversation_service
from app.features.conversations.models import Conversation
from app.features.evaluations import prompt as prompt_builder
from app.features.evaluations.llm import LLMResult, generate_with_retry, get_provider
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

# Один общий предел на процесс; HTTP-запросы не ждут освобождения слота.
_evaluation_slots = threading.BoundedSemaphore(max(1, get_settings().llm_batch_concurrency))

PinnedChecklist = tuple[int, int, dict]


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
        system_instruction=prompt_builder.build_system_instruction(
            config, llm_criteria, is_call=conversation_service.is_call(conv.channel)
        ),
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


def _norm(text: str) -> str:
    # В промпте пробелы и переносы строк уже объединены; остальной текст не меняем.
    return " ".join(text.split())


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
        return make(index, quote, False) if in_range else None

    if in_range and q in _norm(transcript[index].get("text", "")):
        return make(index, quote, True)
    for i, msg in enumerate(transcript):  # модель ошиблась индексом
        if q in _norm(msg.get("text", "")):
            return make(i, quote, True)

    return make(index, quote, False) if in_range else None


def _checked_range(transcript: list[dict], raw: LLMCriterionOutput) -> CheckedRange | None:
    if raw.checked_range is None:
        return None
    a, b = raw.checked_range.from_index, raw.checked_range.to_index
    if not 0 <= a <= b < len(transcript):
        raise ExternalServiceError(f"LLM returned invalid checked_range for {raw.criterion_id}")
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
        raise ExternalServiceError(f"LLM omitted criterion {c.id}")

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


def validate_llm_output(
    output: LLMEvaluationOutput, criteria: list[Criterion], transcript: list[dict]
) -> None:
    expected = {c.id: c for c in criteria}
    ids = [r.criterion_id for r in output.criteria]
    if len(ids) != len(set(ids)) or set(ids) != set(expected):
        raise ExternalServiceError("LLM must return every requested criterion exactly once")

    for result in output.criteria:
        criterion = expected[result.criterion_id]
        if not result.explanation.strip():
            raise ExternalServiceError(f"LLM returned empty explanation for {criterion.id}")
        checked_range = _checked_range(transcript, result)
        has_evidence = any(
            (grounded := _ground_one(transcript, ev.message_index, ev.quote)) is not None
            and grounded.verified
            for ev in result.evidence
        )
        if not result.applicable:
            if not criterion.na_allowed or not result.na_reason.strip() or not has_evidence:
                raise ExternalServiceError(f"LLM returned invalid N/A for {criterion.id}")
            if result.critical_violation:
                raise ExternalServiceError(f"LLM marked N/A criterion {criterion.id} as critical")
            continue

        if not has_evidence and checked_range is None:
            raise ExternalServiceError(
                f"LLM returned no verified evidence or range for {criterion.id}"
            )
        allowed = {level.value for level in criterion.scale_levels}
        if not criterion.scale_min <= result.score <= criterion.scale_max or (
            criterion.answer_type == "scale" and allowed and result.score not in allowed
        ):
            raise ExternalServiceError(
                f"LLM returned invalid score for {criterion.id}: {result.score}"
            )
        if result.critical_violation and not criterion.is_critical:
            raise ExternalServiceError(
                f"LLM marked non-critical criterion {criterion.id} as critical"
            )
        if criterion.id == "critical" and criterion.answer_type == "binary":
            if result.critical_violation != bool(result.score):
                raise ExternalServiceError("LLM critical score contradicts critical_violation")


# ---------------------------------------------------------------- основной сценарий


def _resolve_checklist(db: Session, checklist_id: int | None) -> Checklist:
    if checklist_id is None:
        return checklist_service.get_active(db)
    return checklist_service.get_checklist(db, checklist_id)


def _snapshot_checklist(
    checklist_id: int | None, db: Session | None = None
) -> PinnedChecklist:
    if db is not None:
        checklist = _resolve_checklist(db, checklist_id)
        return checklist.id, checklist.version, copy.deepcopy(checklist.config)
    with SessionLocal() as session:
        checklist = _resolve_checklist(session, checklist_id)
        return checklist.id, checklist.version, copy.deepcopy(checklist.config)


def evaluate(
    db: Session,
    conversation_id: str,
    checklist_id: int | None = None,
    *,
    wait_for_slot: bool = False,
    pinned_checklist: PinnedChecklist | None = None,
) -> Evaluation:
    if not _evaluation_slots.acquire(blocking=wait_for_slot):
        raise BusyError(code="evaluation_busy")
    try:
        if pinned_checklist is None:
            return _evaluate(db, conversation_id, checklist_id)
        return _evaluate(
            db, conversation_id, checklist_id, pinned_checklist=pinned_checklist
        )
    finally:
        _evaluation_slots.release()


def _evaluate(
    db: Session,
    conversation_id: str,
    checklist_id: int | None = None,
    *,
    pinned_checklist: PinnedChecklist | None = None,
) -> Evaluation:
    conv = conversation_service.get_conversation(db, conversation_id)
    if pinned_checklist is not None:
        chk_id, chk_version, chk_raw_config = pinned_checklist
        chk_snapshot = copy.deepcopy(chk_raw_config)
        config = ChecklistConfig.model_validate(chk_snapshot)
    else:
        checklist = _resolve_checklist(db, checklist_id)
        chk_id = checklist.id
        chk_version = checklist.version
        chk_snapshot = copy.deepcopy(checklist.config)
        config = checklist_service.parse_config(checklist)
    preview = build_prompt(conv, config)

    evaluation = Evaluation(
        conversation_id=conv.id,
        checklist_id=chk_id,
        checklist_version=chk_version,
        checklist_snapshot=chk_snapshot,
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
            last_validation_error = ""
            deadline = time.monotonic() + get_settings().llm_timeout_seconds
            for attempt_idx in range(2):  # повтор, если модель вернула невалидный JSON
                if attempt_idx > 0 and time.monotonic() >= deadline:
                    raise ExternalServiceError(
                        "LLM evaluation deadline exceeded after invalid output: "
                        f"{last_validation_error}"
                    )
                llm_result, _attempts = generate_with_retry(
                    provider,
                    system_instruction=preview.system_instruction,
                    input_text=preview.input,
                    schema=preview.response_schema,
                    deadline=deadline,
                )
                evaluation.input_tokens += llm_result.input_tokens
                evaluation.output_tokens += llm_result.output_tokens
                evaluation.thought_tokens += llm_result.thought_tokens
                evaluation.cost_usd += llm_result.cost_usd()
                evaluation.latency_ms += llm_result.latency_ms
                evaluation.raw_response = llm_result.text
                try:
                    raw_output = parse_llm_output(llm_result.text)
                    validate_llm_output(
                        raw_output,
                        [c for c in config.active_criteria if c.id in preview.llm_criteria],
                        conv.transcript,
                    )
                    break
                except ExternalServiceError as exc:
                    raw_output = None
                    last_validation_error = exc.message
                    log.warning("Invalid LLM output for %s: %s", conv.id, exc)
            if raw_output is None:
                raise ExternalServiceError(
                    f"LLM returned invalid output twice: {last_validation_error}"
                )
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
                criteria_results.append(
                    build_criterion_result(c, by_id.get(c.id), conv.transcript)
                )

        result = compute_totals(criteria_results, config.scoring, summary)
        payload = result.model_dump(mode="json")
        evaluation.ai_result = payload
        evaluation.final_result = payload
        evaluation.total_score = result.total
        evaluation.has_critical_error = result.has_critical_error
        evaluation.status = "done"
    except AppError as exc:
        partial = getattr(exc, "partial_result", None)
        if isinstance(partial, LLMResult):
            evaluation.input_tokens += partial.input_tokens
            evaluation.output_tokens += partial.output_tokens
            evaluation.thought_tokens += partial.thought_tokens
            evaluation.cost_usd += partial.cost_usd()
            evaluation.latency_ms += partial.latency_ms
        evaluation.status = "failed"
        evaluation.error = exc.message
        db.commit()
        exc.evaluation_id = evaluation.id  # type: ignore[attr-defined]
        exc.cost_usd = evaluation.cost_usd  # type: ignore[attr-defined]
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
    db: Session,
    *,
    conversation_id: str | None = None,
    checklist_id: int | None = None,
    checklist_version: int | None = None,
    dataset_group: str | None = None,
) -> list[Evaluation]:
    stmt = select(Evaluation).order_by(Evaluation.id.desc())
    if dataset_group:
        stmt = stmt.join(Conversation, Conversation.id == Evaluation.conversation_id).where(
            Conversation.dataset_group == dataset_group
        )
    if conversation_id:
        stmt = stmt.where(Evaluation.conversation_id == conversation_id)
    if checklist_id:
        stmt = stmt.where(Evaluation.checklist_id == checklist_id)
    if checklist_version is not None:
        stmt = stmt.where(Evaluation.checklist_version == checklist_version)
    return list(db.scalars(stmt))


def select_run_evaluation_ids(
    db: Session,
    *,
    checklist_id: int,
    checklist_version: int,
    dataset_group: str | None = None,
    conversation_ids: list[str] | None = None,
) -> list[int]:
    """Восстанавливает из БД список ID оценок для указанного чек-листа и версии."""
    if conversation_ids is not None:
        target_ids = list(dict.fromkeys(conversation_ids))
    else:
        target_ids = [
            c.id for c in conversation_service.list_conversations(db, dataset_group=dataset_group)
        ]
    if not target_ids:
        raise AppError("No target conversations found for run selection")

    rows = list(
        db.scalars(
            select(Evaluation)
            .where(
                Evaluation.conversation_id.in_(target_ids),
                Evaluation.checklist_id == checklist_id,
                Evaluation.checklist_version == checklist_version,
                Evaluation.status.in_(("done", "failed")),
            )
            .order_by(Evaluation.id.desc())
        )
    )
    by_conv_done: dict[str, int] = {}
    by_conv_failed: dict[str, int] = {}
    for row in rows:
        cid = row.conversation_id
        if row.status == "done" and cid not in by_conv_done:
            by_conv_done[cid] = row.id
        elif row.status == "failed" and cid not in by_conv_failed:
            by_conv_failed[cid] = row.id

    selected: list[int] = []
    missing: list[str] = []
    for cid in target_ids:
        ev_id = by_conv_done.get(cid) or by_conv_failed.get(cid)
        if ev_id is None:
            missing.append(cid)
        else:
            selected.append(ev_id)
    if missing:
        raise AppError(
            f"Missing evaluations for checklist {checklist_id} v{checklist_version}: "
            f"{', '.join(missing)}"
        )
    return selected


# ---------------------------------------------------------------- пакетная оценка

_jobs: dict[str, BatchStatus] = {}
_jobs_lock = threading.Lock()
_batch_slot = threading.Lock()
_active_batch_checklist: PinnedChecklist | None = None


def _reserve_batch() -> None:
    if not _batch_slot.acquire(blocking=False):
        raise ConflictError(
            "Пакетная обработка уже идёт. Дождитесь её завершения.",
            code="batch_already_running",
        )


def resolve_batch_targets(db: Session, req: BatchRequest) -> tuple[list[str], int]:
    checklist = _resolve_checklist(db, req.checklist_id)
    if req.conversation_ids:
        ids = list(dict.fromkeys(req.conversation_ids))
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


def _evaluate_isolated(
    conversation_id: str,
    checklist_id: int,
    pinned_checklist: PinnedChecklist | None = None,
) -> tuple[int, float]:
    with SessionLocal() as db:  # отдельная сессия на поток
        ev = evaluate(
            db,
            conversation_id,
            checklist_id,
            wait_for_slot=True,
            pinned_checklist=pinned_checklist,
        )
        return ev.id, ev.cost_usd


def run_batch(
    conversation_ids: list[str],
    checklist_id: int,
    job: BatchStatus | None = None,
    on_progress=None,
    *,
    pinned_checklist: PinnedChecklist | None = None,
) -> BatchStatus:
    global _active_batch_checklist
    _reserve_batch()
    try:
        _active_batch_checklist = pinned_checklist or _snapshot_checklist(checklist_id)
        return _run_batch(conversation_ids, checklist_id, job, on_progress)
    finally:
        _active_batch_checklist = None
        _batch_slot.release()


def _run_batch(
    conversation_ids: list[str],
    checklist_id: int,
    job: BatchStatus | None = None,
    on_progress=None,
    *,
    pinned_checklist: PinnedChecklist | None = None,
) -> BatchStatus:
    pinned = pinned_checklist or _active_batch_checklist or _snapshot_checklist(checklist_id)
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
            pool.submit(_evaluate_isolated, cid, checklist_id, pinned): cid
            for cid in conversation_ids
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
                    cost = getattr(exc, "cost_usd", 0.0)
                    if isinstance(cost, (int, float)) and cost > 0:
                        job.total_cost_usd = round(job.total_cost_usd + float(cost), 6)
                    ev_id = getattr(exc, "evaluation_id", None)
                    if isinstance(ev_id, int):
                        job.evaluation_ids.append(ev_id)
                    job.failed += 1
                    job.errors[cid] = str(exc)[:500]
            if on_progress:
                on_progress(cid, job)
    with _jobs_lock:
        job.status = "done" if job.done else "failed"
    return job


def start_batch_job(
    conversation_ids: list[str],
    checklist_id: int,
    *,
    pinned_checklist: PinnedChecklist | None = None,
) -> BatchStatus:
    global _active_batch_checklist
    _reserve_batch()
    try:
        _active_batch_checklist = pinned_checklist or _snapshot_checklist(checklist_id)
    except Exception:
        _active_batch_checklist = None
        _batch_slot.release()
        raise
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
        global _active_batch_checklist
        try:
            _run_batch(conversation_ids, checklist_id, job)
        except Exception as exc:  # noqa: BLE001
            with _jobs_lock:
                job.status = "failed"
                job.errors["_batch"] = str(exc)
        finally:
            _active_batch_checklist = None
            _batch_slot.release()

    try:
        threading.Thread(target=_runner, daemon=True, name=f"batch-{job.job_id}").start()
    except Exception:
        with _jobs_lock:
            _jobs.pop(job.job_id, None)
        _active_batch_checklist = None
        _batch_slot.release()
        raise
    return get_batch_job(job.job_id)


def get_batch_job(job_id: str) -> BatchStatus:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            raise NotFoundError(
                f"Batch job {job_id} not found (in-memory batch progress is cleared on server "
                "restart; completed evaluations remain available via GET /api/evaluations)"
            )
        return job.model_copy(deep=True)
