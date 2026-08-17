from __future__ import annotations

import pytest

from quant_lab.datasets.errors import DatasetError
from quant_lab.research.domain import JournalEntryType


def test_journal_create_and_edit(research_context):
    repo = research_context["research_repo"]
    model = repo.create_journal_entry(
        title="note",
        entry_type=JournalEntryType.OBSERVATION.value,
        content="observed",
        tags=["a"],
        experiment_id=None,
        backtest_run_id=None,
        strategy_version_id=None,
    )
    assert model.entry_type == JournalEntryType.OBSERVATION.value
    updated = repo.update_journal_entry(
        model.id, content="edited", title=None, entry_type=None, tags=None
    )
    assert updated.content == "edited"


def test_journal_delete(research_context):
    repo = research_context["research_repo"]
    model = repo.create_journal_entry(
        title="note",
        entry_type=JournalEntryType.TODO.value,
        content="x",
        tags=[],
        experiment_id=None,
        backtest_run_id=None,
        strategy_version_id=None,
    )
    repo.delete_journal_entry(model.id)
    with pytest.raises(DatasetError) as error:
        repo.get_journal_entry(model.id)
    assert error.value.category == "JOURNAL_ENTRY_NOT_FOUND"


def test_journal_filters(research_context):
    repo = research_context["research_repo"]
    repo.create_journal_entry(
        title="h",
        entry_type=JournalEntryType.HYPOTHESIS.value,
        content="h",
        tags=["x"],
        experiment_id=None,
        backtest_run_id=None,
        strategy_version_id=None,
    )
    repo.create_journal_entry(
        title="o",
        entry_type=JournalEntryType.OBSERVATION.value,
        content="o",
        tags=[],
        experiment_id=None,
        backtest_run_id=None,
        strategy_version_id=None,
    )
    hypotheses = repo.list_journal_entries(entry_type=JournalEntryType.HYPOTHESIS.value)
    assert len(hypotheses) == 1
    assert hypotheses[0].title == "h"


def test_journal_is_plain_text_contract(research_context):
    repo = research_context["research_repo"]
    payload = "<script>alert(1)</script><b>bold</b>"
    model = repo.create_journal_entry(
        title="html",
        entry_type=JournalEntryType.OBSERVATION.value,
        content=payload,
        tags=[],
        experiment_id=None,
        backtest_run_id=None,
        strategy_version_id=None,
    )
    fetched = repo.get_journal_entry(model.id)
    assert fetched.content == payload
