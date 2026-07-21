from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import Engine

from quant_lab import __version__
from quant_lab.api.data_imports import router as data_imports_router
from quant_lab.api.datasets import router as datasets_router
from quant_lab.api.health import router as health_router
from quant_lab.core.config import Settings
from quant_lab.core.logging import configure_logging
from quant_lab.datasets.repository import DatasetRepository
from quant_lab.db.duckdb import DuckDbStore
from quant_lab.db.sqlite import create_sqlite_engine
from quant_lab.health.service import HealthService
from quant_lab.market_data.repository import MarketDataRepository
from quant_lab.market_data.service import MarketDataImportService

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
        app.state.dataset_repository = DatasetRepository(
            owned_engine,
            run_mode=resolved_settings.run_mode,
        )
        app.state.import_service = MarketDataImportService(
            repository,
            resolved_settings.import_directory,
            resolved_settings.import_preview_rows,
        )
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
        allow_methods=["GET", "POST"],
        allow_headers=["Accept", "Content-Type"],
    )
    application.include_router(health_router, prefix="/api/v1")
    application.include_router(data_imports_router, prefix="/api/v1")
    application.include_router(datasets_router, prefix="/api/v1")
    return application


app = create_app()
