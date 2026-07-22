from __future__ import annotations

import hashlib
from decimal import Decimal

from quant_lab.market_data.fingerprints import canonical_json_bytes


def fingerprint_json(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def fingerprint_strategy(strategy_type: str, strategy_spec: dict[str, object]) -> str:
    return fingerprint_json({"strategy_type": strategy_type, "strategy_spec": strategy_spec})


def fingerprint_config(config: dict[str, object]) -> str:
    return fingerprint_json(config)


def fingerprint_run_input(
    *,
    market_data_snapshot_fingerprint: str,
    strategy_fingerprint: str,
    config_fingerprint: str,
    initial_cash: Decimal,
    start_date: str,
    end_date: str,
) -> str:
    return fingerprint_json(
        {
            "market_data_snapshot_fingerprint": market_data_snapshot_fingerprint,
            "strategy_fingerprint": strategy_fingerprint,
            "config_fingerprint": config_fingerprint,
            "initial_cash": initial_cash,
            "start_date": start_date,
            "end_date": end_date,
        }
    )
