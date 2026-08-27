from __future__ import annotations

from datetime import UTC, datetime

import pytest

from quant_lab.ai.fingerprints import fingerprint_payload


def test_fingerprint_is_canonical_for_mapping_order() -> None:
    assert fingerprint_payload({"b": 2, "a": 1}) == fingerprint_payload({"a": 1, "b": 2})


def test_fingerprint_preserves_list_order_and_values() -> None:
    assert fingerprint_payload({"items": [1, 2]}) != fingerprint_payload({"items": [2, 1]})
    assert fingerprint_payload({"value": 1}) != fingerprint_payload({"value": 2})


def test_fingerprint_requires_aware_timestamps() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        fingerprint_payload({"as_of": datetime(2026, 8, 27, 12, 0)})

    value = fingerprint_payload({"as_of": datetime(2026, 8, 27, 12, 0, tzinfo=UTC)})
    assert len(value) == 64
