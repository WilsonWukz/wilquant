from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Engine, func, inspect, select, text
from sqlalchemy.orm import Session

from quant_lab.ai.analysis_persistence import (
    AIAnalysisContextFreezeModel as Freeze,
)
from quant_lab.ai.analysis_persistence import (
    AIAnalysisExecutionEpochModel as Epoch,
)
from quant_lab.ai.analysis_persistence import (
    AIAnalysisOrchestrationModel as Analysis,
)
from quant_lab.ai.fingerprints import fingerprint_payload
from quant_lab.ai.persistence import (
    AIAnalysisAttemptModel as Attempt,
)
from quant_lab.ai.persistence import (
    AIAnalysisRunModel as Run,
)
from quant_lab.ai.persistence import (
    AIAnalysisTraceEventModel as Trace,
)
from quant_lab.ai.persistence import (
    AIProviderCallBindingModel as Call,
)
from quant_lab.ai.persistence import (
    AIUsageLedgerModel as Usage,
)

TERMINAL = frozenset({"COMPLETED", "FAILED", "REJECTED", "CANCELLED"})


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _trace(session: Session, run_id: str, event: str, payload: dict[str, object]) -> None:
    sequence = (
        session.scalar(select(func.max(Trace.sequence)).where(Trace.run_id == run_id)) or 0
    ) + 1
    session.add(
        Trace(
            id=str(uuid4()),
            run_id=run_id,
            sequence=sequence,
            event_type=event,
            payload_json=_json(payload),
            payload_fingerprint=fingerprint_payload(payload),
            occurred_at=datetime.now(UTC),
        )
    )


def _abandon(session: Session, attempt: Attempt) -> bool:
    binding = session.get(Call, attempt.id)
    unknown = binding is not None
    attempt.status = "ABANDONED" if unknown else "FAILED"
    attempt.failure_code = "PROVIDER_RESULT_UNKNOWN" if unknown else "AI_CANCELLED_BEFORE_DISPATCH"
    attempt.completed_at = datetime.now(UTC)
    if binding and session.scalar(select(Usage.id).where(Usage.attempt_id == attempt.id)) is None:
        session.add(
            Usage(
                id=str(uuid4()),
                run_id=attempt.run_id,
                attempt_id=attempt.id,
                currency=binding.currency,
                is_estimate=True,
                occurred_at=datetime.now(UTC),
            )
        )
    return unknown


class AnalysisRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def run_ids(self) -> set[str]:
        if not inspect(self.engine).has_table(Analysis.__tablename__):
            return set()
        with Session(self.engine) as session:
            return set(session.scalars(select(Analysis.run_id)))

    def get(self, run_id: str) -> Analysis:
        with Session(self.engine) as session:
            row = session.get(Analysis, run_id)
            if row is None:
                raise ValueError("ANALYSIS_NOT_FOUND")
            session.expunge(row)
            return row

    def find_create(self, key: str, fingerprint: str) -> Analysis | None:
        with Session(self.engine) as session:
            row = session.scalar(select(Analysis).where(Analysis.create_key == key))
            if row is not None:
                if row.request_fingerprint != fingerprint:
                    raise ValueError("IDEMPOTENCY_KEY_CONFLICT")
                session.expunge(row)
            return row

    def attach(
        self,
        run_id: str,
        key: str,
        fingerprint: str,
        artifact: dict[str, object],
        context: dict[str, object],
        *,
        run: Run | None = None,
        freeze_owner: str | None = None,
    ) -> Analysis:
        with Session(self.engine, expire_on_commit=False) as session:
            session.execute(text("BEGIN IMMEDIATE"))
            existing = session.scalar(select(Analysis).where(Analysis.create_key == key))
            if existing is not None:
                if existing.request_fingerprint != fingerprint:
                    raise ValueError("IDEMPOTENCY_KEY_CONFLICT")
                session.expunge(existing)
                return existing
            if run is not None:
                session.add(run)
                session.flush()
            row = Analysis(
                run_id=run_id,
                create_key=key,
                request_fingerprint=fingerprint,
                request_artifact_json=_json(artifact),
                context_json=_json(context),
                progress="CONTEXT_PREPARED",
                created_at=datetime.now(UTC),
            )
            session.add(row)
            if freeze_owner is not None:
                frozen = session.get(Freeze, key)
                if (
                    frozen is None
                    or frozen.owner_id != freeze_owner
                    or frozen.status != "OBSERVING"
                ):
                    raise ValueError("ANALYSIS_CONTEXT_NOT_OWNED")
                frozen.run_id, frozen.status = run_id, "FROZEN"
            _trace(session, run_id, "CONTEXT_BUILT", {"request_fingerprint": fingerprint})
            _trace(
                session,
                run_id,
                "EVIDENCE_FROZEN",
                {
                    "evidence_pack_id": context.get("evidence_pack_id"),
                    "evidence_pack_fingerprint": context.get("evidence_pack_fingerprint"),
                },
            )
            _trace(
                session,
                run_id,
                "CASES_RETRIEVED",
                {
                    "retrieval_snapshot_id": context.get("retrieval_snapshot_id"),
                    "retrieval_snapshot_fingerprint": context.get("retrieval_snapshot_fingerprint"),
                },
            )
            session.commit()
            session.expunge(row)
            return row

    def claim(
        self, run_id: str, key: str, fingerprint: str, intent: str
    ) -> tuple[Epoch | None, bool]:
        with Session(self.engine, expire_on_commit=False) as session:
            session.execute(text("BEGIN IMMEDIATE"))
            row, run = session.get(Analysis, run_id), session.get(Run, run_id)
            if row is None or run is None:
                raise ValueError("ANALYSIS_NOT_FOUND")
            previous = session.scalar(
                select(Epoch).where(Epoch.run_id == run_id, Epoch.idempotency_key == key)
            )
            if previous:
                if previous.payload_fingerprint != fingerprint:
                    raise ValueError("IDEMPOTENCY_KEY_CONFLICT")
                if previous.status == "ACTIVE":
                    raise ValueError("ANALYSIS_IN_PROGRESS")
                session.expunge(previous)
                return previous, False
            if run.status in TERMINAL:
                return None, False
            if row.active_epoch_id is not None:
                raise ValueError("ANALYSIS_IN_PROGRESS")
            count = (
                session.scalar(
                    select(func.count()).select_from(Epoch).where(Epoch.run_id == run_id)
                )
                or 0
            )
            if intent not in {"INITIAL", "RESUME", "RETRY_UNKNOWN"}:
                raise ValueError("ANALYSIS_EXECUTE_INTENT_INVALID")
            if (count == 0) != (intent == "INITIAL"):
                raise ValueError("ANALYSIS_EXECUTE_INTENT_INVALID")
            if row.provider_result_unknown and intent != "RETRY_UNKNOWN":
                raise ValueError("PROVIDER_UNKNOWN_CONFIRMATION_REQUIRED")
            epoch = Epoch(
                id=str(uuid4()),
                run_id=run_id,
                idempotency_key=key,
                payload_fingerprint=fingerprint,
                intent=intent,
                status="ACTIVE",
                created_at=datetime.now(UTC),
            )
            session.add(epoch)
            row.active_epoch_id = epoch.id
            if run.status == "CREATED":
                run.status = "RUNNING"
                run.started_at = datetime.now(UTC)
            _trace(
                session,
                run_id,
                "ANALYSIS_EXECUTE_CLAIMED",
                {"epoch_id": epoch.id, "intent": intent},
            )
            session.commit()
            session.expunge(epoch)
            return epoch, True

    def checkpoint(
        self,
        run_id: str,
        epoch_id: str,
        *,
        progress: str,
        outcome: str | None = None,
        lifecycle: str | None = None,
        diagnosis: dict[str, object] | None = None,
        recommendation: dict[str, object] | None = None,
        gate: dict[str, object] | None = None,
        unknown: bool = False,
        release: bool = False,
    ) -> None:
        with Session(self.engine, autoflush=False) as session:
            session.execute(text("BEGIN IMMEDIATE"))
            row, run, epoch = (
                session.get(Analysis, run_id),
                session.get(Run, run_id),
                session.get(Epoch, epoch_id),
            )
            if (
                row is None
                or run is None
                or epoch is None
                or row.active_epoch_id != epoch_id
                or run.status in TERMINAL
            ):
                raise ValueError("ANALYSIS_EXECUTION_NOT_OWNED")
            for field, value in (
                ("diagnosis_json", diagnosis),
                ("recommendation_json", recommendation),
                ("gate_json", gate),
            ):
                if value is not None:
                    encoded = _json(value)
                    if getattr(row, field) not in {None, encoded}:
                        raise ValueError("ANALYSIS_ACCEPTED_RESULT_IMMUTABLE")
                    setattr(row, field, encoded)
            row.progress, row.outcome = progress, outcome
            row.provider_result_unknown = row.provider_result_unknown or unknown
            if lifecycle is not None:
                if lifecycle not in TERMINAL:
                    raise ValueError("ANALYSIS_TERMINAL_STATUS_INVALID")
                for attempt in session.scalars(
                    select(Attempt).where(Attempt.run_id == run_id, Attempt.status == "STARTED")
                ):
                    was_unknown = _abandon(session, attempt)
                    row.provider_result_unknown = row.provider_result_unknown or was_unknown
                    if not was_unknown:
                        attempt.failure_code = "AI_ATTEMPT_NOT_DISPATCHED"
                run.status, run.completed_at = lifecycle, datetime.now(UTC)
                if lifecycle in {"FAILED", "REJECTED"}:
                    run.failure_code = outcome
            if lifecycle is not None or release:
                row.active_epoch_id = None
                epoch.status, epoch.completed_at = "COMPLETED", datetime.now(UTC)
            _trace(
                session,
                run_id,
                {
                    "STAGE1_PENDING": "STAGE1_STARTED",
                    "STAGE2_PENDING": "STAGE2_STARTED",
                    "TERMINAL": "ANALYSIS_COMPLETED"
                    if lifecycle == "COMPLETED"
                    else "ANALYSIS_TERMINATED",
                }.get(progress, progress),
                {
                    "epoch_id": epoch_id,
                    "outcome": outcome,
                    "provider_result_unknown": row.provider_result_unknown,
                    "gate": gate,
                    "accepted": diagnosis or recommendation,
                },
            )
            session.commit()

    def validation_checkpoint(
        self,
        run_id: str,
        epoch_id: str,
        stage: int,
        validation_id: str,
        attempt_id: str,
        codes: tuple[str, ...],
    ) -> None:
        with Session(self.engine) as session:
            session.execute(text("BEGIN IMMEDIATE"))
            row = session.get(Analysis, run_id)
            if row is None or row.active_epoch_id != epoch_id:
                return
            for event in session.scalars(
                select(Trace).where(
                    Trace.run_id == run_id,
                    Trace.event_type == ("STAGE1_VALIDATED" if stage == 1 else "STAGE2_VALIDATED"),
                )
            ):
                if json.loads(event.payload_json).get("validation_result_id") == validation_id:
                    return
            _trace(
                session,
                run_id,
                "STAGE1_VALIDATED" if stage == 1 else "STAGE2_VALIDATED",
                {
                    "validation_result_id": validation_id,
                    "attempt_id": attempt_id,
                    "reason_codes": codes,
                },
            )
            session.commit()

    def cancel(self, run_id: str) -> None:
        with Session(self.engine) as session:
            session.execute(text("BEGIN IMMEDIATE"))
            row, run = session.get(Analysis, run_id), session.get(Run, run_id)
            if row is None or run is None:
                raise ValueError("ANALYSIS_NOT_FOUND")
            if run.status in TERMINAL:
                return
            for attempt in session.scalars(
                select(Attempt).where(Attempt.run_id == run_id, Attempt.status == "STARTED")
            ):
                row.provider_result_unknown = (
                    _abandon(session, attempt) or row.provider_result_unknown
                )
            if row.active_epoch_id:
                epoch = session.get(Epoch, row.active_epoch_id)
                if epoch:
                    epoch.status, epoch.completed_at = "CANCELLED", datetime.now(UTC)
            row.active_epoch_id, row.progress, row.outcome = None, "TERMINAL", "CANCELLED"
            run.status, run.completed_at = "CANCELLED", datetime.now(UTC)
            _trace(
                session,
                run_id,
                "ANALYSIS_CANCELLED",
                {"provider_result_unknown": row.provider_result_unknown},
            )
            session.commit()

    def recover(self) -> None:
        with Session(self.engine) as session:
            session.execute(text("BEGIN IMMEDIATE"))
            for frozen in session.scalars(select(Freeze).where(Freeze.status == "OBSERVING")):
                frozen.status, frozen.failure_code = "FAILED", "ANALYSIS_CONTEXT_INTERRUPTED"
            for row in session.scalars(
                select(Analysis).where(Analysis.active_epoch_id.is_not(None))
            ):
                epoch = session.get(Epoch, row.active_epoch_id)
                for attempt in session.scalars(select(Attempt).where(Attempt.run_id == row.run_id)):
                    if attempt.status == "STARTED":
                        _abandon(session, attempt)
                        # A STARTED at restart is conservatively unknown even without a binding.
                        attempt.status, attempt.failure_code = (
                            "ABANDONED",
                            "PROVIDER_RESULT_UNKNOWN",
                        )
                    if attempt.status == "ABANDONED":
                        row.provider_result_unknown = True
                if epoch:
                    epoch.status, epoch.completed_at = "INTERRUPTED", datetime.now(UTC)
                row.active_epoch_id = None
                if row.provider_result_unknown:
                    row.outcome = "PROVIDER_RESULT_UNKNOWN"
                _trace(
                    session,
                    row.run_id,
                    "ANALYSIS_RECOVERY_REQUIRED",
                    {"provider_result_unknown": row.provider_result_unknown},
                )
            session.commit()
