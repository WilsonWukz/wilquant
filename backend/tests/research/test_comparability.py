from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal

from quant_lab.research.domain import ComparabilityStatus, RunRole

from .conftest import make_succeeded_run


def _make_run(
    context,
    name,
    *,
    dataset="dv",
    calendar="cv",
    start="2026-01-02",
    end="2026-01-06",
    cash=Decimal("100000"),
    fee=None,
    slippage=None,
    status="SUCCEEDED",
):
    runs = context["backtest_repo"]
    fee = fee if fee is not None else {}
    slippage = slippage if slippage is not None else {}
    snapshot = json.dumps({"bars_dataset_version_id": dataset, "calendar_version_id": calendar})
    config = json.dumps(
        {
            "fee_policy": fee,
            "slippage_policy": slippage,
            "max_volume_participation": None,
            "instrument_metadata_overrides": {},
        }
    )
    run = runs.claim(
        name=name,
        market_data_profile_id="p",
        market_data_snapshot_json=snapshot,
        market_data_snapshot_fingerprint="a" * 64,
        strategy_type="BUY_AND_HOLD",
        strategy_spec_json="{}",
        strategy_fingerprint="b" * 64,
        engine_version="backtest-engine@1",
        config_json=config,
        config_fingerprint="c" * 64,
        run_input_fingerprint=hashlib.sha256(name.encode()).hexdigest(),
        initial_cash=cash,
        start_date=date.fromisoformat(start),
        end_date=date.fromisoformat(end),
    )
    if status == "SUCCEEDED":
        runs.mark_running(run.backtest_run_id)
        return runs.mark_succeeded(run.backtest_run_id, "backtests/x/manifest.json")
    if status == "FAILED":
        runs.mark_running(run.backtest_run_id)
        return runs.mark_failed(run.backtest_run_id, "BACKTEST_FAILED", "failed")
    return run


def test_identical_environment_is_strict(research_context):
    comparability = research_context["comparability"]
    baseline = _make_run(research_context, "base")
    candidate = _make_run(research_context, "cand")
    result = comparability.compute(baseline, candidate)
    assert result["status"] == ComparabilityStatus.STRICTLY_COMPARABLE.value
    assert result["reasons"] == []


def test_different_dataset_is_not_comparable(research_context):
    comparability = research_context["comparability"]
    baseline = _make_run(research_context, "base")
    candidate = _make_run(research_context, "cand", dataset="dv2")
    result = comparability.compute(baseline, candidate)
    assert result["status"] == ComparabilityStatus.NOT_COMPARABLE.value
    assert "DIFFERENT_DATASET_VERSION" in result["reasons"]


def test_different_calendar_is_not_comparable(research_context):
    comparability = research_context["comparability"]
    baseline = _make_run(research_context, "base")
    candidate = _make_run(research_context, "cand", calendar="cv2")
    result = comparability.compute(baseline, candidate)
    assert result["status"] == ComparabilityStatus.NOT_COMPARABLE.value
    assert "DIFFERENT_CALENDAR_VERSION" in result["reasons"]


def test_different_date_range_is_not_comparable(research_context):
    comparability = research_context["comparability"]
    baseline = _make_run(research_context, "base")
    candidate = _make_run(research_context, "cand", start="2026-02-01", end="2026-02-05")
    result = comparability.compute(baseline, candidate)
    assert result["status"] == ComparabilityStatus.NOT_COMPARABLE.value
    assert "DIFFERENT_DATE_RANGE" in result["reasons"]


def test_different_fee_is_partially_comparable(research_context):
    comparability = research_context["comparability"]
    baseline = _make_run(research_context, "base")
    candidate = _make_run(research_context, "cand", fee={"stock_commission_rate": "0.003"})
    result = comparability.compute(baseline, candidate)
    assert result["status"] == ComparabilityStatus.PARTIALLY_COMPARABLE.value
    assert "DIFFERENT_FEE_POLICY" in result["reasons"]


def test_different_slippage_is_partially_comparable(research_context):
    comparability = research_context["comparability"]
    baseline = _make_run(research_context, "base")
    candidate = _make_run(research_context, "cand", slippage={"buy_bps": "5"})
    result = comparability.compute(baseline, candidate)
    assert result["status"] == ComparabilityStatus.PARTIALLY_COMPARABLE.value
    assert "DIFFERENT_SLIPPAGE_POLICY" in result["reasons"]


def test_different_initial_cash_is_partially_comparable(research_context):
    comparability = research_context["comparability"]
    baseline = _make_run(research_context, "base")
    candidate = _make_run(research_context, "cand", cash=Decimal("200000"))
    result = comparability.compute(baseline, candidate)
    assert result["status"] == ComparabilityStatus.PARTIALLY_COMPARABLE.value
    assert "DIFFERENT_INITIAL_CASH" in result["reasons"]


def test_failed_run_is_not_comparable(research_context):
    comparability = research_context["comparability"]
    baseline = _make_run(research_context, "base")
    candidate = _make_run(research_context, "cand", status="FAILED")
    result = comparability.compute(baseline, candidate)
    assert result["status"] == ComparabilityStatus.NOT_COMPARABLE.value
    assert "RUN_NOT_SUCCEEDED" in result["reasons"]


def test_comparison_deltas_and_ranking(research_context):
    repo = research_context["research_repo"]
    comparison = research_context["comparison"]
    baseline = make_succeeded_run(research_context, name="cmp-base")
    candidate = make_succeeded_run(research_context, name="cmp-cand")
    experiment = repo.create_experiment(
        name="e", hypothesis="h", tags=[], market_data_profile_id=None
    )
    repo.add_run(experiment.id, baseline.backtest_run_id, RunRole.BASELINE.value, None)
    repo.add_run(experiment.id, candidate.backtest_run_id, RunRole.CANDIDATE.value, None)
    links = repo.list_run_links(experiment.id)
    runs = (baseline, candidate)
    result = comparison.compare(experiment, links, runs)
    assert result["baseline_run_id"] == baseline.backtest_run_id
    candidate_row = next(r for r in result["runs"] if r["role"] == RunRole.CANDIDATE.value)
    assert "deltas" in candidate_row
    assert "total_return_delta" in candidate_row["deltas"]
