from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiohttp import web
from fastapi import HTTPException

from energy_manager.api import create_app
from energy_manager.dashboard import asset as public_asset
from energy_manager.reporting import DISCOVERY


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "energy_manager" / "web"
HA = ROOT / "home-assistant"
CANONICAL_ASSETS = ROOT.parents[1] / "assets" / "energy"
ASSET_NAMES = {
    "house-day.png",
    "house-day-tesla.png",
    "house-night.png",
    "house-night-tesla.png",
    "server-rack.png",
    "hot-water.png",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_dashboard_packages_the_canonical_energy_art() -> None:
    for name in ASSET_NAMES:
        packaged = WEB / "assets" / name
        canonical = CANONICAL_ASSETS / name
        assert packaged.is_file(), name
        assert canonical.is_file(), name
        assert _sha256(packaged) == _sha256(canonical), name
    assert _sha256(WEB / "assets" / "hot-water.png") == (
        "52c2da33ac455ac5d47aeaea55291cf21fa3f07f248a6815f9126b90cdffa251"
    )


def test_dashboard_assets_are_served_by_core_and_public_frontend() -> None:
    app = create_app(SimpleNamespace())
    route = next(route for route in app.routes if getattr(route, "path", None) == "/assets/{name}")
    response = asyncio.run(route.endpoint("house-day.png"))
    assert Path(response.path).name == "house-day.png"
    with pytest.raises(HTTPException) as exc:
        asyncio.run(route.endpoint("not-there.png"))
    assert exc.value.status_code == 404

    response = asyncio.run(public_asset(SimpleNamespace(match_info={"name": "hot-water.png"})))
    assert Path(response._path).name == "hot-water.png"
    with pytest.raises(web.HTTPNotFound):
        asyncio.run(public_asset(SimpleNamespace(match_info={"name": "../index.html"})))


def test_typed_settings_are_local_network_writable_but_overrides_remain_protected() -> None:
    app = create_app(SimpleNamespace())
    settings_route = next(route for route in app.routes if getattr(route, "path", None) == "/api/v1/settings" and "PUT" in getattr(route, "methods", set()))
    override_route = next(route for route in app.routes if getattr(route, "path", None) == "/api/v1/override")
    assert settings_route.dependant.dependencies == []
    assert len(override_route.dependant.dependencies) == 1
    vehicle_route = next(route for route in app.routes if getattr(route, "path", None) == "/api/v1/vehicle/control")
    assert len(vehicle_route.dependant.dependencies) == 1


def test_wheel_includes_dashboard_png_assets() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text()
    assert '"web/assets/*.png"' in pyproject


def test_internal_dashboard_exposes_flow_plan_economics_and_shared_settings() -> None:
    html = (WEB / "index.html").read_text()
    for asset in ASSET_NAMES:
        assert f"/assets/{asset}" in html or asset in {"house-day-tesla.png", "house-night.png", "house-night-tesla.png"}
    for embed in ("flow", "brief", "plan", "prices", "settings"):
        assert f"embed-{embed}" in html
    for contract in (
        "power_flow",
        "point.flow",
        "sources_kw",
        "sinks_kw",
        "meter_balance_error_kw",
        "narrative.current_summary",
        "narrative.next_actions",
        "battery_export_kwh",
        "battery_export_revenue",
        "battery_export_wear_cost",
        "battery_export_net_benefit",
        "solar_export_revenue",
        "total_export_revenue",
        "server_rack",
    ):
        assert contract in html

    for ups_contract in (
        "UPS &amp; server rack",
        "/api/v1/ups/series",
        "upsPowerChart",
        "upsBatteryChart",
        "upsVoltageChart",
        "upsOutlets",
    ):
        assert ups_contract in html
    for setting in (
        "ev_trip_profile",
        "ev_opportunistic_fit_max_per_kwh",
        "ev_charge_limit_pct",
        "min_sell_price_per_kwh",
        "ev_grid_allowed",
        "control_enabled",
        "hot_water_enabled",
    ):
        assert setting in html
    for wire_value in ("no_trip", "distance_100_km", "distance_200_km", "target_80", "target_100"):
        assert wire_value in html
    assert "(num(value)*100).toFixed(1)" in html
    assert "Math.round(num(value)*1000)" in html
    assert "toFixed(1)}%" in html


def test_flow_scene_shows_daily_energy_soc_and_stateful_asset_animation() -> None:
    html = (WEB / "index.html").read_text()
    for marker in (
        "flowPvDay", "flowGridDay", "flowHouseDay", "flowBatteryDay",
        "flowEvDay", "flowWaterDay", "flowRackDay", "flowBatterySoc",
        "flowEvSoc", "homeBatteryGauge", "teslaBatteryGauge",
        "rackLights", "waterHeatEffect",
    ):
        assert marker in html
    assert "daily_energy" in html
    assert "battery_charged_kwh" in html
    assert "ev_soc_pct" in html
    assert "rackInputKw(rack)" in html
    assert "rackOutputKw(rack)" in html
    assert "server_rack_power_w" in html
    assert "raw_real_power_w" in html
    assert "method:'PUT'" in html
    assert "Authorization:`Bearer ${token}`" not in html
    assert "apiToken" not in html
    assert "What happened" in html
    assert "/api/v1/series?limit=288" in html
    assert "Math.min(3.7,num(point.hot_water_kw)??3.7)" in html
    assert "document.addEventListener('visibilitychange'" in html
    assert "Date.now()-state.lastPlanFetchedAt>120000" in html
    assert "if(state.plan)renderPriceChart" not in html
    assert "Backup circuit · diagnostic only" in html
    assert "SAJ TotalLoad; backup is diagnostic only" in html
    assert "Fixed timer · 11am–2pm" in html


def test_home_assistant_dashboard_is_sections_based_and_uses_discovered_entities() -> None:
    dashboard = json.loads((HA / "energy-manager-dashboard.json").read_text())
    view = dashboard["views"][0]
    assert view["type"] == "sections"
    assert view["max_columns"] == 4
    serialised = json.dumps(dashboard)
    for embed in ("flow", "brief", "plan", "prices"):
        assert f"?embed={embed}" in serialised
    for helper in (
        "input_select.energy_manager_ev_trip_profile",
        "input_number.energy_manager_ev_opportunistic_fit_cents",
        "input_number.energy_manager_ev_charge_limit",
        "input_number.energy_manager_min_sell_price_cents",
        "input_boolean.energy_manager_ev_grid_allowed",
        "input_boolean.energy_manager_control_enabled",
    ):
        assert helper in serialised
    assert "sensor.energy_manager_server_rack_energy_today" in serialised
    assert "sensor.energy_manager_planned_battery_export_wear" in serialised
    assert "sensor.energy_manager_realised_battery_export_revenue_today" in serialised
    assert "sensor.energy_manager_realised_net_benefit_today" in serialised
    assert "Normal house total · SAJ TotalLoad" in json.dumps(dashboard, ensure_ascii=False)


def test_home_assistant_tesla_proxy_exposes_supported_controls_without_mqtt_commands() -> None:
    dashboard = json.loads((HA / "energy-manager-dashboard.json").read_text())
    view = dashboard["views"][0]
    serialised = json.dumps(dashboard)
    package = (HA / "energy-manager-dashboard-package.yaml").read_text()
    assert "energy_manager_tesla:" in package
    component = HA / "custom_components" / "energy_manager_tesla"
    for platform in ("climate", "lock", "button", "cover", "switch"):
        assert (component / f"{platform}.py").is_file()
    all_source = "\n".join(path.read_text() for path in component.glob("*.py"))
    for action in (
        "unlock_charge_port", "climate_on", "set_climate_temperature",
        "steering_heat_on", "defrost_on", "vent_windows",
    ):
        assert action in all_source
    assert "command_topic" not in all_source
    assert "async_config_entry_first_refresh" not in all_source

    legacy_base = {
        "sensor.standalone_energy_manager_energy_manager_status",
        "sensor.standalone_energy_manager_energy_manager_pv_power",
        "sensor.standalone_energy_manager_energy_manager_load_power",
        "sensor.standalone_energy_manager_energy_manager_grid_power",
        "sensor.standalone_energy_manager_energy_manager_battery_power",
        "sensor.standalone_energy_manager_energy_manager_ev_soc",
        "sensor.standalone_energy_manager_energy_manager_ev_charging_current",
        "sensor.standalone_energy_manager_energy_manager_hot_water_runtime",
        "sensor.standalone_energy_manager_energy_manager_hot_water_element_power",
    }
    for entity_id in legacy_base:
        assert entity_id in serialised

    known_local = {
        "sensor.energy_manager_battery_soc_rounded",
        "sensor.energy_manager_amber_fit_cents",
        "sensor.energy_manager_amber_import_cents",
        "sensor.energy_manager_aemo_cents",
    }
    discovered = {f"{domain}.energy_manager_{object_id}" for object_id, (domain, *_rest) in DISCOVERY.items()}
    entity_ids: set[str] = set()
    for section in view["sections"]:
        for card in section["cards"]:
            if "entity" in card:
                entity_ids.add(card["entity"])
            for entity in card.get("entities", []):
                if isinstance(entity, dict) and "entity" in entity:
                    entity_ids.add(entity["entity"])
    sensors = {entity for entity in entity_ids if entity.startswith(("sensor.", "binary_sensor."))}
    assert sensors <= discovered | known_local | legacy_base


def test_home_assistant_settings_sync_is_local_and_bidirectional() -> None:
    package = (HA / "energy-manager-dashboard-package.yaml").read_text()
    assert "scan_interval: 2" in package
    assert "energy_manager_api_authorization" not in package
    assert "rest_command.energy_manager_update_settings" in package
    assert "continue_on_error: true" in package
    assert "homeassistant.update_entity" in package
    assert "automation.energy_manager_synchronise_dashboard_settings" in package
    assert "http://10.0.1.205:8787/api/v1/settings" in package
    assert "input_boolean.energy_manager_hot_water_fixed_timer" in package
    assert "hot_water_enabled" in package
    for label in ("No trip", "100 km", "200 km", "Charge to 80%", "Ensure 100%"):
        assert label in package
    for wire_value in ("no_trip", "distance_100_km", "distance_200_km", "target_80", "target_100"):
        assert wire_value in package
    assert "min: 0\n    max: 100" in package
    assert "command_topic" not in package
    assert "mqtt:" not in package
    for source in (
        "sensor.standalone_energy_manager_energy_manager_battery_soc",
        "sensor.standalone_energy_manager_energy_manager_amber_fit",
        "sensor.standalone_energy_manager_energy_manager_amber_import",
        "sensor.standalone_energy_manager_energy_manager_aemo_wholesale",
    ):
        assert source in package
