from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from quant_lab.ai.validation import ValidationResultRecorder, ValidationService

from .test_ai2_validation import _candidate, _fact, _item, _pack


class _Repository:
    def __init__(self) -> None:
        self.models = {}

    def find_validation_result_by_fingerprint(self, fingerprint):
        return next(
            (model for model in self.models.values() if model.fingerprint == fingerprint), None
        )

    def add_validation_result(self, model):
        self.models[model.id] = model
        return model


def test_validation_result_recording_is_stable_and_preserves_untrusted_observations() -> None:
    pack = _pack(_item("a-new", Decimal("1.20")))
    invalid = _candidate(_fact())
    invalid["claims"][0]["unexpected"] = "schema failure"
    result = ValidationService().validate(
        invalid, pack, origin_attempt_id="attempt-1"
    )
    first_repository = _Repository()
    second_repository = _Repository()

    first = ValidationResultRecorder(
        first_repository, clock=lambda: datetime(2026, 8, 30, 0, tzinfo=UTC)
    ).record(
        run_id="run-1",
        attempt_id="attempt-1",
        evidence_pack_id=pack.id,
        result=result,
    )
    second = ValidationResultRecorder(
        second_repository, clock=lambda: datetime(2026, 8, 30, 1, tzinfo=UTC)
    ).record(
        run_id="run-1",
        attempt_id="attempt-1",
        evidence_pack_id=pack.id,
        result=result,
    )

    assert first.fingerprint == second.fingerprint
    assert first.created_at != second.created_at
    assert '"trusted":false' in first.observations_json
    assert first.accepted_assertions_json == "[]"
