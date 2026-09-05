import json
from types import SimpleNamespace

import pytest

from energy_manager.reporting import publish_nut_discovery, publish_saj_discovery


class CapturingReporter:
    def __init__(self) -> None:
        self.settings = SimpleNamespace(mqtt_prefix="energy-manager")
        self.messages: dict[str, dict] = {}

    async def publish_absolute(self, topic: str, payload: dict, **_: object) -> None:
        # Match the real reporter contract while keeping the assertions readable.
        self.messages[topic] = json.loads(json.dumps(payload))


@pytest.mark.asyncio
async def test_saj_legacy_power_discovery_preserves_watt_history_units() -> None:
    reporter = CapturingReporter()
    await publish_saj_discovery(reporter)

    home = reporter.messages["homeassistant/sensor/saj_relay/home_load/config"]
    backup = reporter.messages["homeassistant/sensor/saj_relay/backup_load_power/config"]
    energy = reporter.messages["homeassistant/sensor/saj_relay/total_load_today_kwh/config"]

    assert home["default_entity_id"] == "sensor.saj_home_load"
    assert home["unit_of_measurement"] == "W"
    assert "* 1000" in home["value_template"]
    assert home["suggested_display_precision"] == 0
    assert backup["unit_of_measurement"] == "W"
    assert backup["entity_category"] == "diagnostic"
    assert energy["unit_of_measurement"] == "kWh"
    assert energy["suggested_display_precision"] == 1


@pytest.mark.asyncio
async def test_nut_discovery_exposes_all_variables_with_typed_units() -> None:
    reporter = CapturingReporter()
    await publish_nut_discovery(reporter, {
        "device.mfr": "EATON",
        "device.model": "Eaton 9PX 3000i RT 2U",
        "device.serial": "GA14H32036",
        "ups.realpower": "580",
        "battery.charge": "95",
        "battery.runtime": "1794",
        "input.voltage": "238.9",
        "outlet.1.status": "on",
    })

    power = reporter.messages["homeassistant/sensor/energy_manager_nut/ups_ups_realpower/config"]
    battery = reporter.messages["homeassistant/sensor/energy_manager_nut/ups_battery_charge/config"]
    runtime = reporter.messages["homeassistant/sensor/energy_manager_nut/ups_battery_runtime/config"]
    identity = reporter.messages["homeassistant/sensor/energy_manager_nut/ups_device_model/config"]

    assert len(reporter.messages) == 8
    assert power["unit_of_measurement"] == "W"
    assert power["device_class"] == "power"
    assert battery["unit_of_measurement"] == "%"
    assert battery["device_class"] == "battery"
    assert runtime["unit_of_measurement"] == "s"
    assert runtime["device_class"] == "duration"
    assert identity["entity_category"] == "diagnostic"
    assert power["device"]["serial_number"] == "GA14H32036"
    assert power["value_template"] == "{{ value_json.variables['ups.realpower'] }}"
