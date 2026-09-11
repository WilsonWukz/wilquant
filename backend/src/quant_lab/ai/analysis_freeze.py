"""Durable, exclusive create ownership; never re-observe an interrupted create key."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from quant_lab.ai.analysis_persistence import AIAnalysisContextFreezeModel as Freeze


class ContextFreezeRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def claim(self, key: str, fingerprint: str, artifact: dict[str, object]) -> str | None:
        deadline = time.monotonic() + 30
        while True:
            with Session(self.engine) as session:
                session.execute(text("BEGIN IMMEDIATE"))
                row = session.get(Freeze, key)
                if row is None:
                    owner = str(uuid4())
                    session.add(
                        Freeze(
                            create_key=key,
                            submitted_request_fingerprint=fingerprint,
                            request_artifact_json=json.dumps(artifact),
                            owner_id=owner,
                            status="OBSERVING",
                            created_at=datetime.now(UTC),
                        )
                    )
                    session.commit()
                    return owner
                if row.submitted_request_fingerprint != fingerprint:
                    raise ValueError("IDEMPOTENCY_KEY_CONFLICT")
                if row.status == "FROZEN":
                    return None
                if row.status == "FAILED":
                    raise ValueError(row.failure_code or "ANALYSIS_CONTEXT_INTERRUPTED")
            if time.monotonic() >= deadline:
                raise ValueError("ANALYSIS_IN_PROGRESS")
            time.sleep(0.02)

    def observe(self, key: str, owner: str, artifact: dict[str, object]) -> None:
        with Session(self.engine) as session:
            session.execute(text("BEGIN IMMEDIATE"))
            row = session.get(Freeze, key)
            if row is None or row.owner_id != owner or row.status != "OBSERVING":
                raise ValueError("ANALYSIS_CONTEXT_NOT_OWNED")
            if row.observation_artifact_json is not None:
                raise ValueError("ANALYSIS_OBSERVATION_ALREADY_FROZEN")
            row.observation_artifact_json = json.dumps(artifact)
            session.commit()

    def fail(self, key: str, owner: str, code: str = "ANALYSIS_CONTEXT_INTERRUPTED") -> None:
        with Session(self.engine) as session:
            session.execute(text("BEGIN IMMEDIATE"))
            row = session.get(Freeze, key)
            if row and row.owner_id == owner and row.status == "OBSERVING":
                row.status, row.failure_code = "FAILED", code
                session.commit()
