from __future__ import annotations

from quant_lab.research.domain import JournalEntryType, RunRole

from .conftest import make_succeeded_run


def test_run_report_fingerprint_is_deterministic(research_context):
    run = make_succeeded_run(research_context, name="rep-run")
    reports = research_context["reports"]
    comparison = research_context["comparison"]
    identity = comparison._strategy_identity(run)
    first = reports.run_report(run, identity)
    second = reports.run_report(run, identity)
    assert first["report_fingerprint"] == second["report_fingerprint"]
    assert first["generated_at"] != second["generated_at"]


def test_journal_edit_changes_run_report_fingerprint(research_context):
    repo = research_context["research_repo"]
    run = make_succeeded_run(research_context, name="rep-journal")
    reports = research_context["reports"]
    comparison = research_context["comparison"]
    identity = comparison._strategy_identity(run)
    before = reports.run_report(run, identity)
    entry = repo.create_journal_entry(
        title="obs",
        entry_type=JournalEntryType.OBSERVATION.value,
        content="first",
        tags=[],
        experiment_id=None,
        backtest_run_id=run.backtest_run_id,
        strategy_version_id=None,
    )
    after = reports.run_report(run, identity)
    assert before["report_fingerprint"] != after["report_fingerprint"]
    repo.update_journal_entry(entry.id, content="changed", title=None, entry_type=None, tags=None)
    changed = reports.run_report(run, identity)
    assert changed["report_fingerprint"] != after["report_fingerprint"]


def test_adding_candidate_changes_experiment_report_fingerprint(research_context):
    repo = research_context["research_repo"]
    reports = research_context["reports"]
    comparison = research_context["comparison"]
    diagnostics = research_context["diagnostics"]
    baseline = make_succeeded_run(research_context, name="rep-base")
    candidate = make_succeeded_run(research_context, name="rep-cand")
    experiment = repo.create_experiment(
        name="e", hypothesis="h", tags=[], market_data_profile_id=None
    )
    repo.add_run(experiment.id, baseline.backtest_run_id, RunRole.BASELINE.value, None)
    links = repo.list_run_links(experiment.id)
    runs = (baseline,)

    def build():
        comp = comparison.compare(experiment, links, runs)
        diags = {}
        ids = {}
        for r in runs:
            artifacts = research_context["backtest_repo"].artifacts(r.backtest_run_id)
            diags[r.backtest_run_id] = diagnostics.compute(r, artifacts)
            ids[r.backtest_run_id] = comparison._strategy_identity(r)
        journal = repo.list_journal_entries(experiment_id=experiment.id)
        return reports.experiment_report(experiment, links, runs, comp, diags, ids, journal)

    before = build()
    repo.add_run(experiment.id, candidate.backtest_run_id, RunRole.CANDIDATE.value, None)
    links = repo.list_run_links(experiment.id)
    runs = (baseline, candidate)
    after = build()
    assert before["report_fingerprint"] != after["report_fingerprint"]


def test_report_excludes_investment_advice(research_context):
    run = make_succeeded_run(research_context, name="rep-advice")
    reports = research_context["reports"]
    comparison = research_context["comparison"]
    report = reports.run_report(run, comparison._strategy_identity(run))
    text = str(report)
    for phrase in ("建议买入", "强烈推荐", "预计上涨", "保证收益", "应该实盘"):
        assert phrase not in text
