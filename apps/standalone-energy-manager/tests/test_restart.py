from dataclasses import replace
from datetime import UTC, datetime, timedelta

from energy_manager.config import Settings
from energy_manager.service import restorable_plan


NOW = datetime(2026, 8, 25, 10, tzinfo=UTC)


def plan(settings: Settings) -> dict[str, str]:
    return {
        "software_revision": settings.software_revision,
        "configuration_revision": settings.configuration_revision(),
        "horizon_end": (NOW + timedelta(hours=24)).isoformat(),
    }


def test_current_plan_survives_restart() -> None:
    settings = Settings()
    value = plan(settings)
    assert restorable_plan(value, settings, NOW) is value


def test_old_release_plan_is_rebuilt() -> None:
    settings = Settings()
    value = {**plan(settings), "software_revision": "standalone-old"}
    assert restorable_plan(value, settings, NOW) is None


def test_changed_settings_or_expired_plan_is_rebuilt() -> None:
    settings = Settings()
    value = plan(settings)
    assert restorable_plan(value, replace(settings, min_sell_price_per_kwh=0.25), NOW) is None
    assert restorable_plan({**value, "horizon_end": NOW.isoformat()}, settings, NOW) is None
