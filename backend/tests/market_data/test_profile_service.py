from __future__ import annotations

import pytest

from quant_lab.datasets.errors import DatasetError
from quant_lab.market_data.profile_service import MarketDataProfileService


def test_profile_requires_published_explicit_versions(repository):
    _, calendars = repository
    service = MarketDataProfileService(
        repository=None, calendar_repository=calendars, dataset_query=None
    )
    with pytest.raises(DatasetError) as error:
        service.create_profile(
            name="CN daily",
            market="CN_A_SHARE",
            bar_frequency="DAILY",
            bars_dataset_id="dataset-missing",
            bars_dataset_version_id="version-missing",
            calendar_id="calendar-missing",
            calendar_version_id="calendar-version-missing",
        )
    assert error.value.category == "DATASET_NOT_PUBLISHED"
