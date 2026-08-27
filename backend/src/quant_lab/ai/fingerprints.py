from __future__ import annotations

import hashlib

from quant_lab.market_data.fingerprints import canonical_json_bytes


def fingerprint_payload(payload: object) -> str:
    """Return the SHA-256 of the repository's canonical JSON representation."""

    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
