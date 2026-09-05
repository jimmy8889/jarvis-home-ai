from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import json
import logging
from typing import Any, Awaitable, Callable

import aiohttp
import aiomqtt

from .config import Settings
from .storage import Storage

LOG = logging.getLogger(__name__)


class MqttReporter:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.queue: asyncio.Queue[tuple[str, str, bool, int]] = asyncio.Queue(maxsize=2000)
        self.connected = False
        self.tesla_callback: Callable[[str, str], Awaitable[None]] | None = None

    async def publish(self, suffix: str, payload: Any, retain: bool = True, qos: int = 1) -> None:
        encoded = payload if isinstance(payload, str) else json.dumps(payload, separators=(",", ":"), default=str)
        item = (f"{self.settings.mqtt_prefix}/{suffix}", encoded, retain, qos)
        await self._enqueue(item)

    async def publish_absolute(self, topic: str, payload: Any, retain: bool = True, qos: int = 1) -> None:
        encoded = payload if isinstance(payload, str) else json.dumps(payload, separators=(",", ":"), default=str)
        await self._enqueue((topic, encoded, retain, qos))

    async def _enqueue(self, item: tuple[str, str, bool, int]) -> None:
        try:
            self.queue.put_nowait(item)
        except asyncio.QueueFull:
            _ = self.queue.get_nowait()
            self.queue.task_done()
            self.queue.put_nowait(item)

    async def run(self) -> None:
        delay = 1.0
        while True:
            try:
                async with aiomqtt.Client(
                    hostname=self.settings.mqtt_host,
                    port=self.settings.mqtt_port,
                    identifier="energy-manager",
                    will=aiomqtt.Will(f"{self.settings.mqtt_prefix}/availability", "offline", qos=1, retain=True),
                ) as client:
                    self.connected = True
                    delay = 1.0
                    await client.publish(f"{self.settings.mqtt_prefix}/availability", "online", qos=1, retain=True)
                    await client.subscribe("teslamate/cars/1/#", qos=0)
                    publisher = asyncio.create_task(self._publisher(client))
                    try:
                        async for message in client.messages:
                            if self.tesla_callback:
                                await self.tesla_callback(str(message.topic), bytes(message.payload).decode(errors="replace"))
                    finally:
                        publisher.cancel()
                        await asyncio.gather(publisher, return_exceptions=True)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.connected = False
                LOG.warning("MQTT disconnected: %s", exc)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30)

    async def _publisher(self, client: aiomqtt.Client) -> None:
        while True:
            topic, payload, retain, qos = await self.queue.get()
            try:
                await client.publish(topic, payload, qos=qos, retain=retain)
            finally:
                self.queue.task_done()


def _escape_tag(value: Any) -> str:
    return str(value).replace(" ", "\\ ").replace(",", "\\,").replace("=", "\\=")


def _field(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return f"{value}i"
    if isinstance(value, float):
        return repr(value)
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


class InfluxReporter:
    def __init__(self, settings: Settings, session: aiohttp.ClientSession, storage: Storage):
        self.settings = settings
        self.session = session
        self.storage = storage
        self.last_error: str | None = None
        self.backlog = 0

    async def write(self, measurement: str, fields: dict[str, Any], tags: dict[str, Any] | None = None, at: datetime | None = None) -> None:
        if not fields:
            return
        tag_text = "" if not tags else "," + ",".join(f"{_escape_tag(k)}={_escape_tag(v)}" for k, v in tags.items())
        field_text = ",".join(f"{_escape_tag(k)}={_field(v)}" for k, v in fields.items() if v is not None)
        timestamp = int((at or datetime.now(UTC)).timestamp() * 1_000_000_000)
        body = f"{_escape_tag(measurement)}{tag_text} {field_text} {timestamp}\n"
        await self.storage.enqueue_outbox("influx", measurement, body)
        self.backlog = await self.storage.outbox_count("influx")

    async def run(self) -> None:
        while True:
            try:
                await self.flush()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = str(exc)
                LOG.debug("Influx outbox flush failed: %s", exc)
            await asyncio.sleep(1)

    async def flush(self) -> None:
        token = self.settings.secret("influx_token")
        self.backlog = await self.storage.outbox_count("influx")
        if not token or self.backlog == 0:
            if not token:
                self.last_error = "influx_token secret is missing; rows retained in SQLite outbox"
            return
        rows = await self.storage.pending_outbox("influx")
        body = "".join(str(row["payload"]) for row in rows)
        params = {"org": self.settings.influx_org, "bucket": self.settings.influx_bucket, "precision": "ns"}
        try:
            async with self.session.post(
                f"{self.settings.influx_url}/api/v2/write",
                params=params,
                data=body.encode(),
                headers={"Authorization": f"Token {token}", "Content-Type": "text/plain"},
            ) as response:
                if response.status >= 300:
                    raise RuntimeError(f"Influx write failed HTTP {response.status}: {(await response.text())[:200]}")
            self.last_error = None
            await self.storage.ack_outbox([int(row["id"]) for row in rows])
            self.backlog = await self.storage.outbox_count("influx")
        except Exception as exc:
            self.last_error = str(exc)
            await self.storage.fail_outbox([int(row["id"]) for row in rows])
            raise

    async def ensure_bucket(self) -> None:
        # Bucket creation is done once by deployment with an admin token. The
        # service token intentionally has write-only scope.
        return


DISCOVERY = {
    "status": ("sensor", "Energy Manager Status", None, None),
    "pv_power": ("sensor", "Energy Manager PV Power", "kW", "power"),
    "pv1_power": ("sensor", "Energy Manager PV1 North Power", "kW", "power"),
    "pv2_power": ("sensor", "Energy Manager PV2 South Power", "kW", "power"),
    "pv3_power": ("sensor", "Energy Manager PV3 South Power", "kW", "power"),
    "pv1_expected": ("sensor", "Energy Manager PV1 Expected Power", "kW", "power"),
    "pv2_expected": ("sensor", "Energy Manager PV2 Expected Power", "kW", "power"),
    "pv3_expected": ("sensor", "Energy Manager PV3 Expected Power", "kW", "power"),
    "pv1_forecast_error": ("sensor", "Energy Manager PV1 Forecast Error", "kW", "power"),
    "pv2_forecast_error": ("sensor", "Energy Manager PV2 Forecast Error", "kW", "power"),
    "pv3_forecast_error": ("sensor", "Energy Manager PV3 Forecast Error", "kW", "power"),
    "load_power": ("sensor", "Energy Manager Load Power", "kW", "power"),
    "load_total_power": ("sensor", "Energy Manager SAJ Total Load Diagnostic", "kW", "power"),
    "load_backup_power": ("sensor", "Energy Manager Backup Load Power", "kW", "power"),
    "load_source": ("sensor", "Energy Manager Load Source", None, None),
    "load_balance_error": ("sensor", "Energy Manager Load Balance Error", "kW", "power"),
    "server_rack_power": ("sensor", "Energy Manager Server and Desk Power", "W", "power"),
    "server_rack_confidence": ("sensor", "Energy Manager Server Power Confidence", None, None),
    "server_rack_energy_today": ("sensor", "Energy Manager Server and Desk Energy Today", "kWh", "energy"),
    "grid_health": ("sensor", "Energy Manager Grid Health", None, None),
    "protected_supply": ("sensor", "Energy Manager UPS Supply Mode", None, None),
    "outage_active": ("binary_sensor", "Energy Manager Grid Outage", None, "problem"),
    "outage_duration": ("sensor", "Energy Manager Outage Duration", "s", "duration"),
    "resilience_stage": ("sensor", "Energy Manager Resilience Stage", None, None),
    "rack_power": ("sensor", "Energy Manager Server Rack Power", "W", "power"),
    "office_power": ("sensor", "Energy Manager Office Power", "W", "power"),
    "ups_conversion_loss": ("sensor", "Energy Manager UPS Conversion Loss", "W", "power"),
    "grid_power": ("sensor", "Energy Manager Grid Power", "kW", "power"),
    "battery_power": ("sensor", "Energy Manager Battery Power", "kW", "power"),
    "battery_soc": ("sensor", "Energy Manager Battery SOC", "%", "battery"),
    "battery_soh": ("sensor", "Energy Manager Battery SOH", "%", "battery"),
    "battery_stored": ("sensor", "Energy Manager Stored Energy", "kWh", "energy_storage"),
    "amber_fit": ("sensor", "Energy Manager Amber FIT", "AUD/kWh", "monetary"),
    "amber_import": ("sensor", "Energy Manager Amber Import", "AUD/kWh", "monetary"),
    "aemo_price": ("sensor", "Energy Manager AEMO Wholesale", "AUD/kWh", "monetary"),
    "hot_water_power": ("sensor", "Energy Manager Hot Water Element Power", "W", "power"),
    "hot_water_relay": ("binary_sensor", "Energy Manager Hot Water Relay", None, None),
    "hot_water_runtime": ("sensor", "Energy Manager Hot Water Runtime", "h", "duration"),
    "ev_amps": ("sensor", "Energy Manager EV Charging Current", "A", "current"),
    "ev_soc": ("sensor", "Energy Manager EV SOC", "%", "battery"),
    "james_car_home": ("binary_sensor", "James Car Home", None, "presence"),
    "garage_preset": ("sensor", "Garage Preset", None, None),
    "tesla_climate_on": ("binary_sensor", "Tesla Climate", None, "running"),
    "tesla_climate_target": ("sensor", "Tesla Climate Target", "°C", "temperature"),
    "tesla_interior_temperature": ("sensor", "Tesla Interior Temperature", "°C", "temperature"),
    "tesla_exterior_temperature": ("sensor", "Tesla Exterior Temperature", "°C", "temperature"),
    "tesla_lock_state": ("sensor", "Tesla Lock State", None, None),
    "tesla_charge_port_open": ("binary_sensor", "Tesla Charge Port", None, "opening"),
    "tesla_charge_port_latch": ("sensor", "Tesla Charge Port Latch", None, None),
    "tesla_asleep": ("binary_sensor", "Tesla Asleep", None, None),
    "tesla_windows_open": ("binary_sensor", "Tesla Windows", None, "window"),
    "tesla_steering_heat": ("binary_sensor", "Tesla Steering Wheel Heat", None, "heat"),
    "tesla_defrost": ("binary_sensor", "Tesla Defrost", None, "heat"),
    "tesla_range": ("sensor", "Tesla BLE Range", "km", "distance"),
    "tesla_minutes_to_limit": ("sensor", "Tesla Minutes To Limit", "min", "duration"),
    "tesla_charging_state": ("sensor", "Tesla BLE Charging State", None, None),
    "ev_trip_profile": ("sensor", "Energy Manager EV Trip Profile", None, None),
    "ev_trip_deadline": ("sensor", "Energy Manager EV Trip Deadline", None, "timestamp"),
    "ev_opportunistic_fit": ("sensor", "Energy Manager EV Opportunistic FIT", "AUD/kWh", "monetary"),
    "current_action": ("sensor", "Energy Manager Current Action", None, None),
    "current_reason": ("sensor", "Energy Manager Current Reason", None, None),
    "protected_reserve": ("sensor", "Energy Manager Protected Reserve", "%", "battery"),
    "site_export_target": ("sensor", "Energy Manager Site Export Target", "kW", "power"),
    "battery_target": ("sensor", "Energy Manager Battery Target", "kW", "power"),
    "zero_export": ("binary_sensor", "Energy Manager Zero Export", None, None),
    "expected_pv": ("sensor", "Energy Manager Expected PV", "kW", "power"),
    "plan_generated": ("sensor", "Energy Manager Plan Generated", None, "timestamp"),
    "plan_horizon_end": ("sensor", "Energy Manager Plan Horizon End", None, "timestamp"),
    "forecast_coverage_end": ("sensor", "Energy Manager Price Coverage End", None, "timestamp"),
    "next_export_start": ("sensor", "Energy Manager Next Export Start", None, None),
    "next_export_end": ("sensor", "Energy Manager Next Export End", None, None),
    "next_export_price": ("sensor", "Energy Manager Next Export Price", "AUD/kWh", "monetary"),
    "next_export_power": ("sensor", "Energy Manager Next Export Power", "kW", "power"),
    "export_window_count": ("sensor", "Energy Manager Export Window Count", None, None),
    "hot_water_plan_start": ("sensor", "Energy Manager Hot Water Plan Start", None, "timestamp"),
    "hot_water_plan_end": ("sensor", "Energy Manager Hot Water Plan End", None, "timestamp"),
    "hot_water_remaining": ("sensor", "Energy Manager Hot Water Remaining", "h", "duration"),
    "hot_water_deadline": ("sensor", "Energy Manager Hot Water Deadline", None, "timestamp"),
    "hot_water_source": ("sensor", "Energy Manager Hot Water Source", None, None),
    "ev_recommendation": ("sensor", "Energy Manager EV Recommendation", None, None),
    "ev_target_soc": ("sensor", "Energy Manager EV Target SOC", "%", "battery"),
    "predicted_soc_min": ("sensor", "Energy Manager Predicted Minimum SOC", "%", "battery"),
    "predicted_soc_end": ("sensor", "Energy Manager Predicted Ending SOC", "%", "battery"),
    "expected_pv_energy": ("sensor", "Energy Manager Expected PV Energy", "kWh", "energy"),
    "expected_house_energy": ("sensor", "Energy Manager Expected House Energy", "kWh", "energy"),
    "expected_ev_energy": ("sensor", "Energy Manager Expected EV Energy", "kWh", "energy"),
    "planned_battery_export_energy": ("sensor", "Energy Manager Planned Battery Export Energy", "kWh", "energy"),
    "planned_battery_export_revenue": ("sensor", "Energy Manager Planned Battery Export Revenue", "AUD", "monetary"),
    "planned_battery_export_wear": ("sensor", "Energy Manager Planned Battery Export Wear", "AUD", "monetary"),
    "planned_battery_export_net": ("sensor", "Energy Manager Planned Battery Export Net Benefit", "AUD", "monetary"),
    "planned_solar_export_revenue": ("sensor", "Energy Manager Planned Solar Export Revenue", "AUD", "monetary"),
    "planned_total_export_revenue": ("sensor", "Energy Manager Planned Total Export Revenue", "AUD", "monetary"),
    "realised_battery_export_revenue_today": ("sensor", "Energy Manager Realised Battery Export Revenue Today", "AUD", "monetary"),
    "realised_solar_export_revenue_today": ("sensor", "Energy Manager Realised Solar Export Revenue Today", "AUD", "monetary"),
    "realised_export_revenue_today": ("sensor", "Energy Manager Realised Export Revenue Today", "AUD", "monetary"),
    "realised_import_cost_today": ("sensor", "Energy Manager Realised Import Cost Today", "AUD", "monetary"),
    "realised_battery_wear_today": ("sensor", "Energy Manager Realised Battery Wear Today", "AUD", "monetary"),
    "realised_net_benefit_today": ("sensor", "Energy Manager Realised Net Benefit Today", "AUD", "monetary"),
    "expected_pv_peak": ("sensor", "Energy Manager Expected PV Peak", "kW", "power"),
    "expected_pv_peak_time": ("sensor", "Energy Manager Expected PV Peak Time", None, "timestamp"),
    "influx_backlog": ("sensor", "Energy Manager Influx Backlog", None, None),
}


async def publish_discovery(reporter: MqttReporter) -> None:
    device = {"identifiers": ["standalone_energy_manager"], "name": "Standalone Energy Manager", "manufacturer": "Pilot", "model": "Energy Manager"}
    for object_id, (domain, name, unit, device_class) in DISCOVERY.items():
        state_topic = f"{reporter.settings.mqtt_prefix}/ha/{object_id}/state"
        config: dict[str, Any] = {
            "name": name,
            "unique_id": f"energy_manager_{object_id}",
            "default_entity_id": f"{domain}.energy_manager_{object_id}",
            "state_topic": state_topic,
            "availability": [
                {
                    "topic": f"{reporter.settings.mqtt_prefix}/availability",
                    "payload_available": "online",
                    "payload_not_available": "offline",
                },
                {
                    "topic": f"{reporter.settings.mqtt_prefix}/ha/{object_id}/availability",
                    "payload_available": "available",
                    "payload_not_available": "unavailable",
                },
            ],
            "availability_mode": "all",
            "device": device,
        }
        if unit:
            config["unit_of_measurement"] = unit
        if device_class:
            config["device_class"] = device_class
        await reporter.publish_absolute(f"homeassistant/{domain}/energy_manager/{object_id}/config", config)


def _nut_sensor_metadata(variable: str) -> tuple[str | None, str | None, str | None]:
    """Return unit, HA device class and optional entity category for a NUT variable."""
    unit: str | None = None
    device_class: str | None = None
    if variable.endswith(".realpower") or variable.endswith(".realpower.nominal"):
        unit, device_class = "W", "power"
    elif variable.endswith(".power") or variable.endswith(".power.nominal"):
        unit, device_class = "VA", "apparent_power"
    elif variable.endswith(".current"):
        unit, device_class = "A", "current"
    elif variable.endswith(".frequency") or variable.endswith(".frequency.nominal"):
        unit, device_class = "Hz", "frequency"
    elif variable.endswith(".voltage") or variable.endswith(".voltage.nominal") or variable in {"input.transfer.high", "input.transfer.low"}:
        unit, device_class = "V", "voltage"
    elif variable.endswith(".temperature"):
        unit, device_class = "°C", "temperature"
    elif variable in {"battery.charge", "battery.charge.low", "battery.charge.restart", "ups.efficiency", "ups.load"} or variable.endswith(".autoswitch.charge.low"):
        unit = "%"
        if variable == "battery.charge":
            device_class = "battery"
    elif variable.endswith(".powerfactor"):
        unit = "%" if variable.startswith("outlet.") else None
    elif variable == "battery.capacity":
        unit = "Ah"
    elif any(token in variable for token in ("runtime", ".delay.", ".timer.", "test.interval", "energysave.delay")):
        unit, device_class = "s", "duration"

    diagnostic = (
        variable.startswith(("device.", "driver."))
        or variable.endswith((".nominal", ".serial", ".firmware", ".vendorid", ".productid", ".switchable", ".desc", ".id"))
        or any(token in variable for token in (".delay.", ".timer.", "transfer.", "test.", "energysave.", "ups.start.", "ups.shutdown", "ups.beeper", "battery.protection"))
    )
    return unit, device_class, "diagnostic" if diagnostic else None


async def publish_nut_discovery(reporter: MqttReporter, variables: dict[str, str]) -> None:
    """Expose every read-only NUT variable as part of one manager-owned UPS device."""
    serial = variables.get("device.serial") or variables.get("ups.serial") or "nutdev1"
    model = variables.get("device.model") or variables.get("ups.model") or "Network UPS"
    manufacturer = variables.get("device.mfr") or variables.get("ups.mfr") or "NUT"
    device = {
        "identifiers": [f"energy_manager_nut_{serial}"],
        "name": f"{model} via Energy Manager",
        "manufacturer": manufacturer,
        "model": model,
        "serial_number": serial,
        "sw_version": variables.get("ups.firmware", "unknown"),
        "via_device": "standalone_energy_manager",
    }
    state_topic = f"{reporter.settings.mqtt_prefix}/server-rack"
    for variable in sorted(variables):
        object_id = "ups_" + variable.replace(".", "_").replace("-", "_")
        unit, device_class, category = _nut_sensor_metadata(variable)
        config: dict[str, Any] = {
            "name": "UPS " + variable.replace(".", " ").replace("_", " ").title(),
            "unique_id": f"energy_manager_nut_{variable.replace('.', '_')}",
            "default_entity_id": f"sensor.energy_manager_{object_id}",
            "state_topic": state_topic,
            "value_template": "{{ value_json.variables['" + variable + "'] }}",
            "availability": [
                {
                    "topic": f"{reporter.settings.mqtt_prefix}/availability",
                    "payload_available": "online",
                    "payload_not_available": "offline",
                },
                {
                    "topic": state_topic,
                    "value_template": "{{ 'available' if value_json.available else 'unavailable' }}",
                    "payload_available": "available",
                    "payload_not_available": "unavailable",
                },
            ],
            "availability_mode": "all",
            "device": device,
        }
        if unit:
            config["unit_of_measurement"] = unit
            config["state_class"] = "measurement"
        if device_class:
            config["device_class"] = device_class
        if category:
            config["entity_category"] = category
        await reporter.publish_absolute(
            f"homeassistant/sensor/energy_manager_nut/{object_id}/config",
            config,
            qos=1,
        )


SAJ_DISCOVERY: dict[str, dict[str, Any]] = {
    "pv_power": {"entity": "sensor.saj_pv_power", "name": "PV Power", "unit": "kW", "class": "power", "template": "{{ value_json.pv_kw }}"},
    "pv1_power": {"entity": "sensor.saj_pv1_power", "name": "PV1 North Power", "unit": "kW", "class": "power", "template": "{{ value_json.pv1_kw }}"},
    "pv2_power": {"entity": "sensor.saj_pv2_power", "name": "PV2 South Power", "unit": "kW", "class": "power", "template": "{{ value_json.pv2_kw }}"},
    "pv3_power": {"entity": "sensor.saj_pv3_power", "name": "PV3 South Power", "unit": "kW", "class": "power", "template": "{{ value_json.pv3_kw }}"},
    "home_load": {"entity": "sensor.saj_home_load", "name": "Normal House Total", "unit": "kW", "class": "power", "template": "{{ value_json.load_kw }}"},
    "total_load_power": {"entity": "sensor.saj_total_load_power", "name": "Total Load Power", "unit": "kW", "class": "power", "template": "{{ value_json.load_total_kw }}"},
    "backup_load_power": {"entity": "sensor.saj_backup_total_load_power_watt", "name": "Backup Load Power", "unit": "kW", "class": "power", "template": "{{ value_json.load_backup_kw }}", "category": "diagnostic"},
    "battery_power": {"entity": "sensor.saj_battery_power", "name": "Battery Power", "unit": "kW", "class": "power", "template": "{{ value_json.battery_kw }}"},
    "inverter_power": {"entity": "sensor.saj_inverter_power", "name": "Inverter Power", "unit": "kW", "class": "power", "template": "{{ value_json.inverter_kw }}"},
    "grid_power": {"entity": "sensor.saj_meter_a_real_power_total", "name": "Meter A Real Power Total", "unit": "kW", "class": "power", "template": "{{ value_json.grid_kw }}"},
    "ct_grid_power": {"entity": "sensor.saj_ct_grid_power_total", "name": "CT Grid Power Total", "unit": "kW", "class": "power", "template": "{{ value_json.grid_kw }}"},
    "flow_grid_power": {"entity": "sensor.saj_total_grid_power", "name": "Flow Grid Power", "unit": "kW", "class": "power", "template": "{{ value_json.flow_grid_kw }}", "category": "diagnostic"},
    "battery_soc": {"entity": "sensor.saj_battery_1_soc", "name": "Battery 1 SOC", "unit": "%", "class": "battery", "template": "{{ value_json.soc_pct }}"},
    "battery_energy_percent": {"entity": "sensor.saj_battery_energy_percent", "name": "Battery Energy Percent", "unit": "%", "class": "battery", "template": "{{ value_json.soc_pct }}"},
    "battery_soh": {"entity": "sensor.saj_battery_1_soh", "name": "Battery 1 SOH", "unit": "%", "class": "battery", "template": "{{ value_json.soh_pct }}"},
    "battery_voltage": {"entity": "sensor.saj_battery_1_voltage", "name": "Battery 1 Voltage", "unit": "V", "class": "voltage", "template": "{{ value_json.battery_voltage_v }}"},
    "battery_temperature": {"entity": "sensor.saj_battery_1_temperature", "name": "Battery 1 Temperature", "unit": "°C", "class": "temperature", "template": "{{ value_json.battery_temperature_c }}"},
    "battery_cycles": {"entity": "sensor.saj_battery_1_cycle_count", "name": "Battery 1 Cycle Count", "template": "{{ value_json.battery_cycle_count }}", "category": "diagnostic"},
    "inverter_temperature": {"entity": "sensor.saj_inverter_temperature", "name": "Inverter Temperature", "unit": "°C", "class": "temperature", "template": "{{ value_json.inverter_temperature_c }}"},
    "environment_temperature": {"entity": "sensor.saj_environment_temperature", "name": "Environment Temperature", "unit": "°C", "class": "temperature", "template": "{{ value_json.environment_temperature_c }}"},
    "inverter_status": {"entity": "sensor.saj_inverter_status", "name": "Inverter Status", "template": "{{ value_json.inverter_status }}"},
    "working_mode": {"entity": "sensor.saj_inverter_working_mode", "name": "Inverter Working Mode", "template": "{{ value_json.app_mode }}", "category": "diagnostic"},
    "active_faults": {"entity": "sensor.saj_active_faults", "name": "Active Faults", "template": "{{ value_json.active_faults | join(', ') if value_json.active_faults else 'none' }}", "category": "diagnostic"},
    "fault_count": {"entity": "sensor.saj_fault_count", "name": "Fault Count", "template": "{{ value_json.fault_count }}", "category": "diagnostic"},
    "fault_severity": {"entity": "sensor.saj_fault_severity", "name": "Fault Severity", "template": "{{ value_json.fault_severity }}", "category": "diagnostic"},
    "last_fault": {"entity": "sensor.saj_last_fault", "name": "Last Fault", "template": "{{ value_json.last_fault }}", "category": "diagnostic"},
    "grid_state": {"entity": "sensor.saj_grid_state", "name": "Grid State", "template": "{{ value_json.grid_state }}"},
    "sample_skew": {"entity": "sensor.saj_sample_skew", "name": "Sample Skew", "unit": "ms", "class": "duration", "template": "{{ value_json.sample_skew_ms }}", "category": "diagnostic"},
    "cycle_duration": {"entity": "sensor.saj_poll_cycle_duration", "name": "Poll Cycle Duration", "unit": "ms", "class": "duration", "template": "{{ value_json.cycle_duration_ms }}", "category": "diagnostic"},
    "sample_sequence": {"entity": "sensor.saj_sample_sequence", "name": "Sample Sequence", "template": "{{ value_json.sample_sequence }}", "category": "diagnostic"},
    "read_errors": {"entity": "sensor.saj_modbus_read_errors", "name": "Modbus Read Errors", "template": "{{ value_json.modbus_read_errors }}", "category": "diagnostic"},
    "reconnects": {"entity": "sensor.saj_modbus_reconnects", "name": "Modbus Reconnects", "template": "{{ value_json.modbus_reconnects }}", "category": "diagnostic"},
    "fast_pv_power": {"entity": "sensor.saj_fast_pv_power", "name": "Fast PV Power", "unit": "kW", "class": "power", "template": "{{ value_json.pv_kw }}", "category": "diagnostic"},
    "fast_battery_power": {"entity": "sensor.saj_fast_battery_power", "name": "Fast Battery Power", "unit": "kW", "class": "power", "template": "{{ value_json.battery_kw }}", "category": "diagnostic"},
    "fast_grid_power": {"entity": "sensor.saj_fast_grid_load_power", "name": "Fast Grid Power", "unit": "kW", "class": "power", "template": "{{ value_json.grid_kw }}", "category": "diagnostic"},
    "fast_total_load": {"entity": "sensor.saj_fast_total_load_power", "name": "Fast Total Load Power", "unit": "kW", "class": "power", "template": "{{ value_json.load_total_kw }}", "category": "diagnostic"},
    "fast_backup_load": {"entity": "sensor.saj_fast_backup_total_load_power_watt", "name": "Fast Backup Load Power", "unit": "kW", "class": "power", "template": "{{ value_json.load_backup_kw }}", "category": "diagnostic"},
    "fast_pv1_power": {"entity": "sensor.saj_fast_pv1_power", "name": "Fast PV1 Power", "unit": "kW", "class": "power", "template": "{{ value_json.pv1_kw }}", "category": "diagnostic"},
    "fast_pv2_power": {"entity": "sensor.saj_fast_pv2_power", "name": "Fast PV2 Power", "unit": "kW", "class": "power", "template": "{{ value_json.pv2_kw }}", "category": "diagnostic"},
}

for phase in range(3):
    number = phase + 1
    SAJ_DISCOVERY[f"meter_power_{number}"] = {"entity": f"sensor.saj_meter_a_real_power_{number}", "name": f"Meter A Real Power {number}", "unit": "kW", "class": "power", "template": f"{{{{ value_json.meter_phase_power_kw[{phase}] }}}}"}
    SAJ_DISCOVERY[f"voltage_{number}"] = {"entity": f"sensor.saj_meter_a_voltage_{number}", "name": f"Meter A Voltage {number}", "unit": "V", "class": "voltage", "template": f"{{{{ value_json.meter_phase_voltage_v[{phase}] }}}}"}
    SAJ_DISCOVERY[f"current_{number}"] = {"entity": f"sensor.saj_meter_a_current_{number}", "name": f"Meter A Current {number}", "unit": "A", "class": "current", "template": f"{{{{ value_json.meter_phase_current_a[{phase}] }}}}"}
    SAJ_DISCOVERY[f"frequency_{number}"] = {"entity": f"sensor.saj_meter_a_frequency_{number}", "name": f"Meter A Frequency {number}", "unit": "Hz", "class": "frequency", "template": f"{{{{ value_json.meter_phase_frequency_hz[{phase}] }}}}"}
    SAJ_DISCOVERY[f"phase_present_{number}"] = {"domain": "binary_sensor", "entity": f"binary_sensor.saj_grid_phase_{number}_present", "name": f"Grid Phase {number} Present", "class": "connectivity", "template": f"{{{{ 'ON' if value_json.grid_phase_present[{phase}] else 'OFF' }}}}"}

SAJ_DISCOVERY.update({
    "fault": {"domain": "binary_sensor", "entity": "binary_sensor.saj_fault", "name": "Inverter Fault", "class": "problem", "template": "{{ 'ON' if value_json.fault_count | int > 0 else 'OFF' }}", "category": "diagnostic"},
    "grid_online": {"domain": "binary_sensor", "entity": "binary_sensor.saj_grid_online", "name": "Grid Online", "class": "connectivity", "template": "{{ 'ON' if value_json.grid_state == 'online' else 'OFF' }}"},
})

ENERGY_COUNTER_ENTITIES = {
    "pv_today_kwh": "sensor.saj_power_current_day",
    "pv_total_kwh": "sensor.saj_total_power_generation",
    "battery_charge_today_kwh": "sensor.saj_battery_today_charge",
    "battery_charge_total_kwh": "sensor.saj_battery_total_charge",
    "battery_discharge_today_kwh": "sensor.saj_battery_today_discharge",
    "battery_discharge_total_kwh": "sensor.saj_battery_total_discharge",
    "inverter_generation_today_kwh": "sensor.saj_inverter_today_generation",
    "inverter_generation_total_kwh": "sensor.saj_inverter_total_generation",
    "total_load_today_kwh": "sensor.saj_total_today_load",
    "total_load_total_kwh": "sensor.saj_total_load",
    "backup_load_today_kwh": "sensor.saj_backup_today_load",
    "backup_load_total_kwh": "sensor.saj_backup_total_load",
    "pv2_total_kwh": "sensor.saj_total_pv_energy_2",
    "pv3_total_kwh": "sensor.saj_total_pv_energy_3",
    "grid_import_today_kwh": "sensor.saj_sum_all_phases_feed_in_today",
    "grid_import_total_kwh": "sensor.saj_sum_all_phases_feed_in_total",
    "grid_export_today_kwh": "sensor.saj_sum_all_phases_sell_today",
    "grid_export_total_kwh": "sensor.saj_sum_all_phases_sell_total",
}
for key, entity in ENERGY_COUNTER_ENTITIES.items():
    SAJ_DISCOVERY[key] = {"entity": entity, "name": entity.split("sensor.saj_", 1)[1].replace("_", " ").title(), "unit": "kWh", "class": "energy", "state_class": "total_increasing", "template": f"{{{{ value_json.energy_counters.get('{key}') }}}}"}


async def publish_saj_discovery(reporter: MqttReporter, identity: dict[str, Any] | None = None) -> None:
    identity = identity or {}
    serial = str(identity.get("serial_number") or "energy-manager-relay")
    device = {
        "identifiers": [f"saj_h2_{serial}"], "name": "SAJ H2 Inverter via Energy Manager",
        "manufacturer": "SAJ", "model": str(identity.get("product_code") or "H2"),
        "serial_number": serial, "sw_version": str(identity.get("master_software") or "unknown"),
        "via_device": "standalone_energy_manager",
    }
    state_topic = f"{reporter.settings.mqtt_prefix}/saj/realtime"
    for object_id, spec in SAJ_DISCOVERY.items():
        domain = spec.get("domain", "sensor")
        value_template = spec["template"]
        unit = spec.get("unit")
        # Preserve the units used by the retired SAJ Home Assistant integration.
        # Grafana and HA long-term history already store these familiar power
        # entity IDs as watts, while the manager's native payload remains kW.
        if spec.get("class") == "power" and unit == "kW":
            expression = value_template.removeprefix("{{").removesuffix("}}").strip()
            value_template = f"{{{{ ((({expression}) | float(0)) * 1000) | round(0) }}}}"
            unit = "W"
        config: dict[str, Any] = {
            "name": spec["name"], "unique_id": f"energy_manager_saj_{object_id}",
            "default_entity_id": spec["entity"], "state_topic": state_topic,
            "value_template": value_template,
            "availability_topic": f"{reporter.settings.mqtt_prefix}/availability",
            "payload_available": "online", "payload_not_available": "offline",
            "expire_after": 3, "device": device,
        }
        if unit:
            config["unit_of_measurement"] = unit
        if spec.get("class"):
            config["device_class"] = spec["class"]
        if domain == "sensor" and unit:
            config["state_class"] = spec.get("state_class", "measurement")
            config["suggested_display_precision"] = 0 if unit == "W" else 1
        if spec.get("category"):
            config["entity_category"] = spec["category"]
        await reporter.publish_absolute(
            f"homeassistant/{domain}/saj_relay/{object_id}/config", config, qos=1
        )
