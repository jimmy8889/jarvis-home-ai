from energy_manager.models import Telemetry


def test_battery_model_uses_nominal_capacity_times_soh() -> None:
    telemetry = Telemetry(soc_pct=50, soh_pct=90)
    model = telemetry.battery_model(50, 5, 0.92, 0.92)
    assert model["effective_capacity_kwh"] == 45
    assert model["gross_stored_kwh"] == 22.5
    assert model["usable_above_floor_kwh"] == 20.25
    assert round(model["extractable_ac_kwh"], 2) == 18.63
    assert round(model["energy_to_full_ac_kwh"], 3) == 24.457


def test_battery_model_never_reports_energy_below_floor() -> None:
    telemetry = Telemetry(soc_pct=3, soh_pct=97.3)
    model = telemetry.battery_model(50, 5, 0.92, 0.92)
    assert model["usable_above_floor_kwh"] == 0
    assert model["extractable_ac_kwh"] == 0
