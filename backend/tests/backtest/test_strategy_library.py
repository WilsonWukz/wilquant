from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from quant_lab.backtest.fingerprints import fingerprint_strategy
from quant_lab.backtest.repository import BacktestRepository
from quant_lab.backtest.service import BacktestService
from quant_lab.backtest.strategy_library import StrategyLibrary, StrategyVersionModel
from quant_lab.core.config import Settings
from quant_lab.datasets.errors import DatasetError


@pytest.fixture
def library(repository):
    engine, _ = repository
    return StrategyLibrary(engine)


@pytest.fixture
def definition(library):
    return library.create_definition("momentum", "rotational momentum", "BUY_AND_HOLD")


def test_create_definition_and_first_version(library, definition):
    assert definition.strategy_type == "BUY_AND_HOLD"
    assert definition.status == "ACTIVE"
    version = library.create_version(definition.id, {"instrument_id": "600000.XSHG"}, "")
    assert version.version == 1
    assert version.strategy_definition_id == definition.id


def test_version_increments_within_definition(library, definition):
    first = library.create_version(definition.id, {"instrument_id": "600000.XSHG"}, "")
    second = library.create_version(definition.id, {"instrument_id": "600000.XSHG"}, "")
    assert first.version == 1
    assert second.version == 2


def test_version_is_immutable(repository, library, definition):
    engine, _ = repository
    version = library.create_version(definition.id, {"instrument_id": "600000.XSHG"}, "")
    with pytest.raises(sa.exc.IntegrityError), Session(engine) as session:
        model = session.get(StrategyVersionModel, version.id)
        assert model is not None
        model.strategy_spec_json = "{}"
        session.commit()


def test_version_cannot_be_deleted(repository, library, definition):
    engine, _ = repository
    version = library.create_version(definition.id, {"instrument_id": "600000.XSHG"}, "")
    with pytest.raises(sa.exc.IntegrityError), Session(engine) as session:
        model = session.get(StrategyVersionModel, version.id)
        assert model is not None
        session.delete(model)
        session.commit()


def test_same_type_and_spec_share_fingerprint():
    assert fingerprint_strategy("BUY_AND_HOLD", {"x": 1}) == fingerprint_strategy(
        "BUY_AND_HOLD", {"x": 1}
    )


def test_different_spec_has_different_fingerprint():
    assert fingerprint_strategy("BUY_AND_HOLD", {"x": 1}) != fingerprint_strategy(
        "BUY_AND_HOLD", {"x": 2}
    )


def test_version_fingerprint_matches_unique_helper(library, definition):
    spec = {"instrument_id": "600000.XSHG", "target_weight": 1}
    version = library.create_version(definition.id, spec, "")
    assert version.strategy_fingerprint == fingerprint_strategy("BUY_AND_HOLD", spec)


def test_top_level_unsafe_key_rejected(library, definition):
    with pytest.raises(DatasetError, match="STRATEGY_SPEC_INVALID"):
        library.create_version(definition.id, {"python": "print('x')"}, "")


def test_nested_unsafe_key_rejected(library, definition):
    with pytest.raises(DatasetError, match="STRATEGY_SPEC_INVALID"):
        library.create_version(definition.id, {"config": {"python": "print('x')"}}, "")


def test_list_nested_unsafe_key_rejected(library, definition):
    with pytest.raises(DatasetError, match="STRATEGY_SPEC_INVALID"):
        library.create_version(definition.id, {"steps": [{"sql": "SELECT 1"}]}, "")


def test_plain_string_parameters_are_not_rejected(library, definition):
    version = library.create_version(
        definition.id,
        {"instrument_id": "600000.XSHG", "note": "strategy containing the word python"},
        "",
    )
    assert version.version == 1


def _service(engine, tmp_path) -> BacktestService:
    return BacktestService(
        repository=None,
        market_data_service=None,
        calendar_repository=None,
        run_repository=BacktestRepository(engine),
        settings=Settings(project_root=tmp_path),
    )


def test_version_plus_nonempty_spec_conflicts(repository, tmp_path):
    engine, _ = repository
    service = _service(engine, tmp_path)
    with pytest.raises(DatasetError, match="STRATEGY_SOURCE_CONFLICT"):
        service.create_run(
            name="run",
            market_data_profile_id="p",
            strategy_type="BUY_AND_HOLD",
            strategy_spec={"instrument_id": "600000.XSHG"},
            strategy_version_id="v",
            start_date=None,
            end_date=None,
            initial_cash=None,
            config={},
        )


def test_version_plus_empty_spec_conflicts(repository, tmp_path):
    engine, _ = repository
    service = _service(engine, tmp_path)
    with pytest.raises(DatasetError, match="STRATEGY_SOURCE_CONFLICT"):
        service.create_run(
            name="run",
            market_data_profile_id="p",
            strategy_type="BUY_AND_HOLD",
            strategy_spec={},
            strategy_version_id="v",
            start_date=None,
            end_date=None,
            initial_cash=None,
            config={},
        )


def test_neither_source_rejected(repository, tmp_path):
    engine, _ = repository
    service = _service(engine, tmp_path)
    with pytest.raises(DatasetError, match="STRATEGY_SPEC_INVALID"):
        service.create_run(
            name="run",
            market_data_profile_id="p",
            strategy_type="BUY_AND_HOLD",
            strategy_spec=None,
            strategy_version_id=None,
            start_date=None,
            end_date=None,
            initial_cash=None,
            config={},
        )
