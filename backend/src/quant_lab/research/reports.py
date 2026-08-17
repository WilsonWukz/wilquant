from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from quant_lab.market_data.fingerprints import canonical_json_bytes

REPORT_SCHEMA_VERSION = "research-report@1"


def _fingerprint(payload: dict[str, object]) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _journal_payload(entries) -> list[dict[str, object]]:
    return [
        {
            "id": entry.id,
            "entry_type": entry.entry_type,
            "title": entry.title,
            "content": entry.content,
            "tags": json.loads(entry.tags_json),
            "experiment_id": entry.experiment_id,
            "backtest_run_id": entry.backtest_run_id,
            "strategy_version_id": entry.strategy_version_id,
        }
        for entry in entries
    ]


def _artifact_payload(artifacts) -> list[dict[str, object]]:
    return [
        {
            "artifact_type": a.artifact_type,
            "relative_path": a.relative_path,
            "sha256": a.sha256,
            "size_bytes": a.size_bytes,
        }
        for a in artifacts
    ]


class ResearchReportService:
    def __init__(self, run_repository, reader, diagnostics, journal_repository) -> None:
        self.runs = run_repository
        self.reader = reader
        self.diagnostics = diagnostics
        self.journal = journal_repository

    def run_report(self, run, strategy_identity: dict[str, object]) -> dict[str, object]:
        artifacts = self.runs.artifacts(run.backtest_run_id)
        metrics_artifact = next((a for a in artifacts if a.artifact_type == "METRICS"), None)
        metrics = self.reader.read_json(metrics_artifact) if metrics_artifact else {}
        diagnostic = self.diagnostics.compute(run, artifacts)
        journal = self.journal.list_journal_entries(backtest_run_id=run.backtest_run_id)
        payload: dict[str, object] = {
            "report_schema_version": REPORT_SCHEMA_VERSION,
            "run": {
                "backtest_run_id": run.backtest_run_id,
                "name": run.name,
                "status": run.status,
                "engine_version": run.engine_version,
            },
            "strategy": strategy_identity,
            "market_data_snapshot": json.loads(run.market_data_snapshot_json),
            "date_range": {
                "start_date": run.start_date.isoformat(),
                "end_date": run.end_date.isoformat(),
            },
            "initial_cash": _money(run.initial_cash),
            "config": json.loads(run.config_json),
            "metrics": metrics,
            "diagnostics": diagnostic,
            "artifact_integrity": _artifact_payload(artifacts),
            "linked_journal_entries": _journal_payload(journal),
        }
        fingerprint = _fingerprint(payload)
        return {
            **payload,
            "generated_at": datetime.now(UTC).isoformat(),
            "report_fingerprint": fingerprint,
        }

    def experiment_report(
        self,
        experiment,
        links,
        runs,
        comparison: dict[str, object],
        diagnostics: dict[str, dict[str, object]],
        strategy_identities: dict[str, dict[str, object]],
        journal,
    ) -> dict[str, object]:
        baseline_link = next((link for link in links if link.role == "BASELINE"), None)
        baseline_run = (
            next(
                (r for r in runs if r.backtest_run_id == baseline_link.backtest_run_id),
                None,
            )
            if baseline_link
            else None
        )
        payload: dict[str, object] = {
            "report_schema_version": REPORT_SCHEMA_VERSION,
            "experiment": {
                "id": experiment.id,
                "name": experiment.name,
                "hypothesis": experiment.hypothesis,
                "tags": json.loads(experiment.tags_json),
                "status": experiment.status,
            },
            "baseline": (
                {
                    "run_id": baseline_run.backtest_run_id,
                    "strategy": strategy_identities.get(baseline_run.backtest_run_id),
                }
                if baseline_run
                else None
            ),
            "candidates": [
                {
                    "run_id": r.backtest_run_id,
                    "strategy": strategy_identities.get(r.backtest_run_id),
                }
                for link in links
                for r in runs
                if link.role == "CANDIDATE" and r.backtest_run_id == link.backtest_run_id
            ],
            "references": [
                {
                    "run_id": r.backtest_run_id,
                    "strategy": strategy_identities.get(r.backtest_run_id),
                }
                for link in links
                for r in runs
                if link.role == "REFERENCE" and r.backtest_run_id == link.backtest_run_id
            ],
            "comparison": comparison,
            "diagnostics": diagnostics,
            "linked_journal_entries": _journal_payload(journal),
        }
        fingerprint = _fingerprint(payload)
        return {
            **payload,
            "generated_at": datetime.now(UTC).isoformat(),
            "report_fingerprint": fingerprint,
        }


def _money(value: object) -> str:
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text
