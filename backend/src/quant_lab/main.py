from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError

from quant_lab import __version__
from quant_lab.ai.cases import ResearchCaseService
from quant_lab.ai.provenance import AIProvenanceService
from quant_lab.ai.repository import AIRepository
from quant_lab.api.ai_research import router as ai_research_router
from quant_lab.api.backtests import router as backtests_router
from quant_lab.api.calendars import router as calendars_router
from quant_lab.api.data_imports import router as data_imports_router
from quant_lab.api.datasets import publish_router
from quant_lab.api.datasets import router as datasets_router
from quant_lab.api.experiments import router as experiments_router
from quant_lab.api.health import router as health_router
from quant_lab.api.market_data import router as market_data_router
from quant_lab.api.paper import router as paper_router
from quant_lab.api.profiles import router as profiles_router
from quant_lab.api.research_journal import router as research_journal_router
from quant_lab.api.strategies import router as strategies_router
from quant_lab.backtest.repository import BacktestRepository
from quant_lab.backtest.service import BacktestService
from quant_lab.backtest.strategy_library import StrategyLibrary
from quant_lab.core.config import Settings
from quant_lab.core.logging import configure_logging
from quant_lab.datasets.publication import PublicationService
from quant_lab.datasets.query import DatasetQueryService
from quant_lab.datasets.recovery import PublicationRecoveryService
from quant_lab.datasets.repository import DatasetRepository
from quant_lab.db.duckdb import DuckDbStore
from quant_lab.db.sqlite import create_sqlite_engine
from quant_lab.health.service import HealthService
from quant_lab.market_data.calendar_persistence import TradingCalendarRepository
from quant_lab.market_data.calendar_service import TradingCalendarImportService
from quant_lab.market_data.consumption import MarketDataService
from quant_lab.market_data.profile_persistence import MarketDataProfileRepository
from quant_lab.market_data.profile_service import MarketDataProfileService
from quant_lab.market_data.repository import MarketDataRepository
from quant_lab.market_data.service import MarketDataImportService
from quant_lab.paper.policy_service import PaperRiskPolicyService
from quant_lab.paper.repository import PaperRepository
from quant_lab.paper.risk import RiskEngine
from quant_lab.paper.risk_service import PaperRiskService
from quant_lab.paper.service import PaperSessionService
from quant_lab.research.artifacts import ArtifactReader
from quant_lab.research.comparability import (
    BacktestComparabilityService,
    BacktestComparisonService,
)
from quant_lab.research.diagnostics import ResearchDiagnosticsService
from quant_lab.research.reports import ResearchReportService
from quant_lab.research.repository import ResearchRepository

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    health_service: HealthService | None = None,
) -> FastAPI:
    """Create an application with injectable infrastructure for deterministic tests."""

    resolved_settings = settings or Settings()
    owned_engine: Engine | None = None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        nonlocal owned_engine
        resolved_settings.ensure_runtime_directories()
        configure_logging(resolved_settings.log_level, resolved_settings.log_path)
        owned_engine = create_sqlite_engine(resolved_settings)
        repository = MarketDataRepository(owned_engine)
        app.state.market_data_repository = repository
        app.state.calendar_repository = TradingCalendarRepository(owned_engine)
        app.state.calendar_import_service = TradingCalendarImportService(
            app.state.calendar_repository
        )
        app.state.profile_repository = MarketDataProfileRepository(owned_engine)
        app.state.backtest_repository = BacktestRepository(owned_engine)
        app.state.sqlite_engine = owned_engine
        app.state.dataset_repository = DatasetRepository(
            owned_engine,
            run_mode=resolved_settings.run_mode,
        )
        app.state.import_service = MarketDataImportService(
            repository,
            resolved_settings.import_directory,
            resolved_settings.import_preview_rows,
        )
        app.state.publication_service = PublicationService(
            app.state.dataset_repository, repository, resolved_settings
        )
        app.state.dataset_query_service = DatasetQueryService(
            app.state.dataset_repository, resolved_settings.published_directory
        )
        app.state.profile_service = MarketDataProfileService(
            app.state.profile_repository,
            app.state.calendar_repository,
            app.state.dataset_query_service,
            app.state.dataset_repository,
        )
        app.state.market_data_service = MarketDataService(
            app.state.profile_repository,
            app.state.calendar_repository,
            app.state.dataset_query_service,
            owned_engine,
        )
        app.state.backtest_service = BacktestService(
            app.state.profile_repository,
            app.state.market_data_service,
            app.state.calendar_repository,
            app.state.backtest_repository,
            resolved_settings,
        )
        app.state.paper_repository = PaperRepository(owned_engine)
        app.state.paper_risk_service = PaperRiskService(
            app.state.paper_repository, RiskEngine()
        )
        app.state.paper_risk_policy_service = PaperRiskPolicyService(
            app.state.paper_repository
        )
        app.state.paper_session_service = PaperSessionService(
            owned_engine,
            app.state.paper_repository,
            app.state.market_data_service,
            app.state.calendar_repository,
            app.state.dataset_query_service,
            app.state.paper_risk_service,
        )
        app.state.publication_recovery = PublicationRecoveryService(
            app.state.dataset_repository,
            resolved_settings.publication_staging_directory,
            resolved_settings.published_directory,
        )
        app.state.publication_recovery.recover()
        app.state.research_repository = ResearchRepository(owned_engine)
        app.state.research_reader = ArtifactReader(
            resolved_settings.runtime_root or resolved_settings.project_root
        )
        app.state.comparability = BacktestComparabilityService()
        app.state.comparison = BacktestComparisonService(
            app.state.backtest_repository,
            app.state.research_reader,
            StrategyLibrary(owned_engine),
            app.state.comparability,
        )
        app.state.diagnostics = ResearchDiagnosticsService(app.state.research_reader)
        app.state.reports = ResearchReportService(
            app.state.backtest_repository,
            app.state.research_reader,
            app.state.diagnostics,
            app.state.research_repository,
        )
        try:
            app.state.ai_repository = AIRepository(owned_engine)
            app.state.ai_fts_document_count = (
                app.state.ai_repository.rebuild_research_case_fts()
            )
            app.state.ai_case_service = ResearchCaseService(app.state.ai_repository)
            app.state.ai_provenance_service = AIProvenanceService(app.state.ai_repository)
            app.state.ai_provenance_service.recover_incomplete_runs(datetime.now(UTC))
            app.state.ai_provenance_available = True
        except SQLAlchemyError:
            logger.warning(
                "Optional AI provenance component unavailable",
                extra={"event": "ai.provenance.unavailable"},
                exc_info=True,
            )
            app.state.ai_repository = None
            app.state.ai_fts_document_count = None
            app.state.ai_case_service = None
            app.state.ai_provenance_service = None
            app.state.ai_provenance_available = False
        if health_service is None:
            app.state.health_service = HealthService(
                owned_engine,
                DuckDbStore(resolved_settings.duckdb_path),
            )
        else:
            app.state.health_service = health_service
        logger.info("Application started", extra={"event": "application.started"})
        try:
            yield
        finally:
            logger.info("Application stopped", extra={"event": "application.stopped"})
            if owned_engine is not None:
                owned_engine.dispose()
            configure_logging(resolved_settings.log_level)

    application = FastAPI(
        title="Personal A-Share Quant Lab",
        version=__version__,
        lifespan=lifespan,
    )
    application.state.settings = resolved_settings
    application.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.frontend_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Accept", "Content-Type"],
    )
    application.include_router(health_router, prefix="/api/v1")
    application.include_router(data_imports_router, prefix="/api/v1")
    application.include_router(datasets_router, prefix="/api/v1")
    application.include_router(publish_router, prefix="/api/v1")
    application.include_router(calendars_router, prefix="/api/v1")
    application.include_router(profiles_router, prefix="/api/v1")
    application.include_router(market_data_router, prefix="/api/v1")
    application.include_router(backtests_router, prefix="/api/v1")
    application.include_router(paper_router, prefix="/api/v1")
    application.include_router(strategies_router, prefix="/api/v1")
    application.include_router(experiments_router, prefix="/api/v1")
    application.include_router(research_journal_router, prefix="/api/v1")
    application.include_router(ai_research_router, prefix="/api/v1")
    return application


app = create_app()
