from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from energy_optimizer.models import Slot
from energy_optimizer.parsing import build_slots


BRISBANE = ZoneInfo("Australia/Brisbane")


def test_signed_fit_and_solcast_are_preserved():
    now = datetime(2026, 8, 11, 11, 30, tzinfo=BRISBANE)
    fit = {"attributes": {"forecast": [
        {"time": now.isoformat(), "value": -0.01},
        {"time": (now + timedelta(minutes=30)).isoformat(), "value": 0.21},
    ]}}
    imports = {"attributes": {"forecast": [
        {"time": now.isoformat(), "value": 0.03},
        {"time": (now + timedelta(minutes=30)).isoformat(), "value": 0.30},
    ]}}
    solar = {"attributes": {"detailedForecast": [
        {"period_start": now.isoformat(), "pv_estimate": 10, "pv_estimate10": 7, "pv_estimate90": 11},
        {"period_start": (now + timedelta(minutes=30)).isoformat(), "pv_estimate": 9, "pv_estimate10": 5, "pv_estimate90": 10},
    ]}}
    slots = build_slots(
        now=now,
        horizon_hours=1,
        slot_minutes=30,
        timezone=BRISBANE,
        fit_entity=fit,
        import_entity=imports,
        solar_entities=[solar],
        load_forecast=lambda _: 1.5,
        calibration_ratio=1.0,
        weather_condition="sunny",
    )
    assert slots[0].export_price == -0.01
    assert slots[1].export_price == 0.21
    assert slots[0].solar_kw == 10
    assert slots[0].solar_low_kw == 6.3


def test_incomplete_amber_horizon_uses_historical_fallback():
    now = datetime(2026, 8, 11, 10, 0, tzinfo=BRISBANE)
    slots = build_slots(
        now=now,
        horizon_hours=2,
        slot_minutes=30,
        timezone=BRISBANE,
        fit_entity={},
        import_entity={},
        solar_entities=[],
        load_forecast=lambda _: 1.0,
        calibration_ratio=1.0,
        weather_condition="sunny",
    )
    assert all(slot.price_source == "historical_fallback" for slot in slots)
    assert slots[-1].import_price == 0.04
