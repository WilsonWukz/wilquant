from __future__ import annotations

from quant_lab.datasets.errors import DatasetError
from quant_lab.datasets.query import DatasetQueryService
from quant_lab.datasets.repository import DatasetRepository
from quant_lab.market_data.calendar_persistence import TradingCalendarRepository
from quant_lab.market_data.profile_persistence import (
    MarketDataProfileModel,
    MarketDataProfileRepository,
)


class MarketDataProfileService:
    def __init__(
        self,
        repository: MarketDataProfileRepository | None,
        calendar_repository: TradingCalendarRepository,
        dataset_query: DatasetQueryService | None,
        dataset_repository: DatasetRepository | None = None,
    ) -> None:
        self.repository = repository
        self.calendar_repository = calendar_repository
        self.dataset_query = dataset_query
        self.dataset_repository = dataset_repository

    def _validate_bindings(
        self,
        *,
        bars_dataset_id: str,
        bars_dataset_version_id: str,
        calendar_id: str,
        calendar_version_id: str,
    ) -> tuple[object, object]:
        if self.dataset_repository is None or self.dataset_query is None:
            raise DatasetError("DATASET_NOT_PUBLISHED", "数据集版本未发布")
        version = self.dataset_repository.get_version(bars_dataset_id, bars_dataset_version_id)
        self.dataset_query._files(bars_dataset_id, bars_dataset_version_id)
        if version.status != "PUBLISHED":
            raise DatasetError("DATASET_NOT_PUBLISHED", "数据集版本未发布")
        calendar = self.calendar_repository.get_version(calendar_id, calendar_version_id)
        if calendar.status != "PUBLISHED":
            raise DatasetError("CALENDAR_NOT_PUBLISHED", "交易日日历版本未发布")
        return version, calendar

    def create_profile(
        self,
        *,
        name: str,
        market: str,
        bar_frequency: str,
        bars_dataset_id: str,
        bars_dataset_version_id: str,
        calendar_id: str,
        calendar_version_id: str,
    ) -> MarketDataProfileModel:
        if market != "CN_A_SHARE" or bar_frequency != "DAILY":
            raise DatasetError("PROFILE_MARKET_UNSUPPORTED", "当前仅支持 CN_A_SHARE 日线")
        self._validate_bindings(
            bars_dataset_id=bars_dataset_id,
            bars_dataset_version_id=bars_dataset_version_id,
            calendar_id=calendar_id,
            calendar_version_id=calendar_version_id,
        )
        if self.repository is None:
            raise DatasetError("PROFILE_STORAGE_UNAVAILABLE", "市场数据配置存储不可用")
        return self.repository.create(
            name=name,
            market=market,
            bar_frequency=bar_frequency,
            bars_dataset_id=bars_dataset_id,
            bars_dataset_version_id=bars_dataset_version_id,
            calendar_id=calendar_id,
            calendar_version_id=calendar_version_id,
        )

    def update_profile(
        self,
        profile_id: str,
        *,
        bars_dataset_id: str,
        bars_dataset_version_id: str,
        calendar_id: str,
        calendar_version_id: str,
    ) -> MarketDataProfileModel:
        self._validate_bindings(
            bars_dataset_id=bars_dataset_id,
            bars_dataset_version_id=bars_dataset_version_id,
            calendar_id=calendar_id,
            calendar_version_id=calendar_version_id,
        )
        if self.repository is None:
            raise DatasetError("PROFILE_STORAGE_UNAVAILABLE", "市场数据配置存储不可用")
        return self.repository.update_bindings(
            profile_id,
            {
                "bars_dataset_id": bars_dataset_id,
                "bars_dataset_version_id": bars_dataset_version_id,
                "calendar_id": calendar_id,
                "calendar_version_id": calendar_version_id,
            },
        )
