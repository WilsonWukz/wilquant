from __future__ import annotations

import pytest

from quant_lab.datasets.errors import DatasetError
from quant_lab.research.domain import ResearchExperimentStatus, RunRole

from .conftest import make_succeeded_run


def _create(repo, name="exp"):
    return repo.create_experiment(
        name=name, hypothesis="h", tags=["a"], market_data_profile_id=None
    )


def test_create_and_get_experiment(research_context):
    repo = research_context["research_repo"]
    model = _create(repo)
    assert model.status == ResearchExperimentStatus.DRAFT.value
    fetched = repo.get_experiment(model.id)
    assert fetched.name == "exp"
    assert fetched.hypothesis == "h"


def test_update_experiment_fields(research_context):
    repo = research_context["research_repo"]
    model = _create(repo)
    updated = repo.update_experiment(model.id, {"name": "renamed", "hypothesis": "h2"})
    assert updated.name == "renamed"
    assert updated.hypothesis == "h2"


def test_add_run_and_duplicate_rejected(research_context):
    repo = research_context["research_repo"]
    run = make_succeeded_run(research_context, name="run-dup")
    model = _create(repo)
    link = repo.add_run(model.id, run.backtest_run_id, RunRole.CANDIDATE.value, None)
    assert link.role == RunRole.CANDIDATE.value
    with pytest.raises(DatasetError, match="EXPERIMENT_RUN_DUPLICATE"):
        repo.add_run(model.id, run.backtest_run_id, RunRole.REFERENCE.value, None)


def test_one_baseline_and_replacement(research_context):
    repo = research_context["research_repo"]
    run_a = make_succeeded_run(research_context, name="run-a")
    run_b = make_succeeded_run(research_context, name="run-b")
    model = _create(repo)
    repo.add_run(model.id, run_a.backtest_run_id, RunRole.BASELINE.value, None)
    repo.add_run(model.id, run_b.backtest_run_id, RunRole.CANDIDATE.value, None)
    links = repo.list_run_links(model.id)
    baselines = [link for link in links if link.role == RunRole.BASELINE.value]
    assert len(baselines) == 1
    # 替换 baseline
    repo.update_run_link(model.id, run_b.backtest_run_id, RunRole.BASELINE.value, None)
    links = repo.list_run_links(model.id)
    baselines = [link for link in links if link.role == RunRole.BASELINE.value]
    assert len(baselines) == 1
    assert baselines[0].backtest_run_id == run_b.backtest_run_id
    old_a = [link for link in links if link.backtest_run_id == run_a.backtest_run_id]
    assert old_a and old_a[0].role != RunRole.BASELINE.value


def test_remove_run_link(research_context):
    repo = research_context["research_repo"]
    run = make_succeeded_run(research_context, name="run-remove")
    model = _create(repo)
    repo.add_run(model.id, run.backtest_run_id, RunRole.CANDIDATE.value, None)
    repo.remove_run_link(model.id, run.backtest_run_id)
    assert repo.list_run_links(model.id) == ()


def test_deleting_link_does_not_delete_run(research_context):
    repo = research_context["research_repo"]
    backtest_repo = research_context["backtest_repo"]
    run = make_succeeded_run(research_context, name="run-keep")
    model = _create(repo)
    repo.add_run(model.id, run.backtest_run_id, RunRole.CANDIDATE.value, None)
    repo.remove_run_link(model.id, run.backtest_run_id)
    assert backtest_repo.get(run.backtest_run_id).backtest_run_id == run.backtest_run_id


def test_archived_experiment_readable(research_context):
    repo = research_context["research_repo"]
    model = _create(repo)
    repo.update_experiment(model.id, {"status": ResearchExperimentStatus.ARCHIVED.value})
    fetched = repo.get_experiment(model.id)
    assert fetched.status == ResearchExperimentStatus.ARCHIVED.value
