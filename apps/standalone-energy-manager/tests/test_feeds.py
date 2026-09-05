import copy
from datetime import UTC, datetime
import json
from pathlib import Path

import aiohttp
import pytest

from energy_manager.config import Settings
from energy_manager.feeds import AmberFeed, SolarForecasts, amber_channels
from energy_manager.planner import provider_power


FIXTURES = Path(__file__).parent / "fixtures"


class FakeForecastSolarResponse:
    def __init__(self, payload: dict, status: int = 200):
        self.payload = payload
        self.status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    def raise_for_status(self) -> None:
        if self.status >= 400:
            raise aiohttp.ClientResponseError(None, (), status=self.status)

    async def json(self) -> dict:
        return copy.deepcopy(self.payload)


class FakeForecastSolarSession:
    def __init__(self, payloads: list[dict]):
        self.payloads = list(payloads)
        self.requests: list[tuple[str, dict]] = []

    def get(self, url: str, **kwargs):
        self.requests.append((url, kwargs))
        return FakeForecastSolarResponse(self.payloads.pop(0))


def forecast_solar_fixture() -> dict:
    return json.loads((FIXTURES / "forecast_solar_watts_v7_41.json").read_text())


def feed() -> AmberFeed:
    return AmberFeed(Settings(), None)  # type: ignore[arg-type]


def test_amber_uses_advanced_predicted_price_for_forecast() -> None:
    item = feed()._interval({
        "type": "ForecastInterval",
        "channelType": "feedIn",
        "startTime": "2026-08-25T08:45:00Z",
        "endTime": "2026-08-25T08:50:00Z",
        "perKwh": 12.0,
        "advancedPrice": {"low": 10.0, "predicted": 15.0, "high": 20.0},
    })
    assert item is not None
    assert item.price_per_kwh == -0.15
    assert item.start == datetime(2026, 8, 25, 8, 45, tzinfo=UTC)


def test_amber_converts_feed_in_from_billing_to_customer_sign() -> None:
    item = feed()._interval({
        "type": "CurrentInterval",
        "channelType": "feedIn",
        "startTime": "2026-08-25T08:45:00Z",
        "endTime": "2026-08-25T08:50:00Z",
        "perKwh": -7.5,
        "estimate": False,
    })
    assert item is not None
    assert item.price_per_kwh == 0.075


def test_amber_positive_billing_feed_in_is_negative_customer_fit() -> None:
    item = feed()._interval({
        "type": "CurrentInterval",
        "channelType": "feedIn",
        "startTime": "2026-08-25T08:45:01Z",
        "endTime": "2026-08-25T08:50:00Z",
        "perKwh": 7.5,
        "estimate": False,
    })
    assert item is not None
    assert item.price_per_kwh == -0.075
    assert item.start == datetime(2026, 8, 25, 8, 45, tzinfo=UTC)


def test_cached_forecast_covers_boundary_until_current_arrives() -> None:
    amber = feed()
    now = datetime(2026, 8, 25, 8, 45, tzinfo=UTC)
    forecast = amber._interval({
        "type": "ForecastInterval",
        "channelType": "feedIn",
        "startTime": "2026-08-25T08:45:00Z",
        "endTime": "2026-08-25T08:50:00Z",
        "perKwh": 20.0,
    })
    assert forecast is not None
    amber.forecast = {"feedIn": [forecast]}
    fit, _ = amber_channels(amber, now)
    assert fit is forecast


def test_current_interval_supersedes_cached_forecast() -> None:
    amber = feed()
    now = datetime(2026, 8, 25, 8, 45, tzinfo=UTC)
    forecast = amber._interval({
        "type": "ForecastInterval", "channelType": "feedIn",
        "startTime": "2026-08-25T08:45:00Z", "endTime": "2026-08-25T08:50:00Z", "perKwh": -20.0,
    })
    current = amber._interval({
        "type": "CurrentInterval", "channelType": "feedIn",
        "startTime": "2026-08-25T08:45:00Z", "endTime": "2026-08-25T08:50:00Z", "perKwh": 5.0,
    })
    assert forecast is not None and current is not None
    amber.forecast = {"feedIn": [forecast, current]}
    amber.current = {"feedIn": current}
    fit, _ = amber_channels(amber, now)
    assert fit is current


async def test_forecast_solar_uses_official_watts_shape_for_five_minute_plan() -> None:
    """Pin the Forecast.Solar v7.41 power-only response contract."""

    payload = forecast_solar_fixture()
    session = FakeForecastSolarSession([payload, payload])
    forecasts = SolarForecasts(Settings(), session)  # type: ignore[arg-type]

    result = await forecasts.forecast_solar()

    assert len(session.requests) == 2
    assert all("/estimate/watts/" in url for url, _kwargs in session.requests)
    assert all("/watthours/period/" not in url for url, _kwargs in session.requests)
    assert all(kwargs["params"] == {"time": "utc"} for _url, kwargs in session.requests)
    assert result["roofs"]["north"]["watts"]["2026-08-25T22:30:00+00:00"] == 3416
    assert payload["message"]["info"]["timezone"] == "Australia/Brisbane"
    assert set(result["roofs"]["north"]) == {"watts"}

    # The rolling planner asks at five-minute boundaries even when the
    # provider account returns wider periods.  The normalised cached shape is
    # consumed directly and resolves a nearby provider power point.
    five_minute_point = datetime(2026, 8, 25, 22, 35, tzinfo=UTC)
    power = provider_power(forecasts, five_minute_point, "Australia/Brisbane")
    assert power["forecast_solar_kw"] == pytest.approx(6.832)


async def test_forecast_solar_parse_failure_preserves_last_good_cache() -> None:
    payload = forecast_solar_fixture()
    session = FakeForecastSolarSession([payload, {"result": [], "message": {"code": 0}}])
    forecasts = SolarForecasts(Settings(), session)  # type: ignore[arg-type]
    cached = {
        "issued_at": "2026-08-25T20:00:00+00:00",
        "roofs": {"north": {"watts": {"2026-08-25T22:00:00+00:00": 1234}}},
    }
    forecasts.providers["forecast-solar"] = copy.deepcopy(cached)

    with pytest.raises(ValueError, match="no result mapping"):
        await forecasts.forecast_solar()

    assert forecasts.providers["forecast-solar"] == cached
