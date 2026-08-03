from __future__ import annotations

import os
from pathlib import Path
import tempfile
import time
import unittest

from fastapi.testclient import TestClient

from pilot_core.api import create_app
from pilot_core.config import (
    IntegrationSettings,
    Player,
    Room,
    ServerSettings,
    Settings,
    Vehicle,
    VehicleControl,
)
from pilot_core.integrations import IntegrationRequestFailed
from pilot_core.storage import Store
from pilot_core.vehicle import VehicleProviderUnavailable


class FakeIntegrations:
    def __init__(self) -> None:
        self.states = {
            "binary_sensor.jarvis_online": "on",
            "sensor.jarvis_battery": "72",
            "number.jarvis_charge_limit": "80",
            "sensor.jarvis_tpms_fl": "9.2",
            "lock.jarvis": "locked",
            "select.jarvis_seat_right": "Off",
        }
        self.calls: list[tuple[str, str, dict[str, object]]] = []
        self.fail_climate = False

    async def home_assistant_state(self, entity_id: str) -> dict[str, object]:
        return {
            "entity_id": entity_id,
            "state": self.states.get(entity_id, "unknown"),
            "attributes": {"unit_of_measurement": "bar"},
            "last_updated": "2026-08-03T05:00:00+00:00",
        }

    async def home_assistant_vehicle_action(
        self,
        domain: str,
        service: str,
        *,
        entity_id: str = "",
        device_id: str = "",
        service_data: dict[str, object] | None = None,
    ) -> dict[str, object]:
        data = dict(service_data or {})
        self.calls.append((domain, service, data))
        if domain == "climate" and self.fail_climate:
            raise IntegrationRequestFailed("climate provider failed")
        if domain == "lock" and service == "unlock":
            self.states[entity_id] = "unlocked"
        if domain == "select" and service == "select_option":
            self.states[entity_id] = str(data["option"])
        return {"accepted": True, "targeted": bool(entity_id or device_id)}


class FakeTeslaMate:
    outage = False

    async def drives(self, car_id: int, *, limit: int, cursor: int | None) -> dict[str, object]:
        del car_id, limit, cursor
        if self.outage:
            raise VehicleProviderUnavailable("TeslaMate adapter is unavailable")
        return {
            "items": [
                {
                    "id": 9,
                    "distance": 20,
                    "start_rated_range_km": 400,
                    "end_rated_range_km": 360,
                    "configured_efficiency_wh_per_km": 180,
                    "start_battery_level": 80,
                    "end_battery_level": 70,
                    "end_date": "2026-08-01T01:00:00Z",
                    "start_address": "Home",
                    "end_address": "Work",
                }
            ],
            "next_cursor": None,
        }

    async def drive(self, car_id: int, drive_id: int) -> dict[str, object]:
        del car_id
        return {"id": drive_id, "distance": 20, "end_date": None}

    async def drive_positions(self, car_id: int, drive_id: int) -> dict[str, object]:
        del car_id, drive_id
        return {"items": [], "truncated": False}

    async def charges(self, car_id: int, *, limit: int, cursor: int | None) -> dict[str, object]:
        del car_id, limit, cursor
        return {
            "items": [
                {
                    "id": 3,
                    "charge_energy_added": 18,
                    "charge_energy_used": 20,
                    "dc_fast_charger": False,
                    "end_date": "2026-08-01T03:00:00Z",
                }
            ],
            "next_cursor": None,
        }

    async def battery_health(
        self, car_id: int, *, manual_baseline_kwh: float | None
    ) -> dict[str, object]:
        del car_id, manual_baseline_kwh
        return {"status": "insufficient_data", "sample_count": 0}


class VehicleApiTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["PILOT_TESLAMATE_ADAPTER_TOKEN"] = "t" * 32
        os.environ["PILOT_TESLA_VEHICLE_ID"] = "provider-vehicle-test"
        self.root = tempfile.TemporaryDirectory()
        root = Path(self.root.name)
        self.settings = Settings(
            server=ServerSettings(
                database_path=":memory:", vehicle_asset_path=str(root / "receipts")
            ),
            integrations=IntegrationSettings(
                teslamate_adapter_url="http://teslamate.test:8781"
            ),
            rooms=(
                Room("office", "Office", "speaker", "music"),
            ),
            players=(
                Player("speaker", "office", "Speaker", "pipewire", "response"),
                Player("music", "office", "Music", "sendspin", "music"),
            ),
            vehicles=(
                Vehicle(
                    id="jarvis",
                    name="Jarvis",
                    teslamate_car_id=1,
                    manual_battery_baseline_kwh=75,
                    telemetry=(
                        ("online", "binary_sensor.jarvis_online"),
                        ("battery_percent", "sensor.jarvis_battery"),
                        ("charge_limit_percent", "number.jarvis_charge_limit"),
                        ("tyre_front_left_bar", "sensor.jarvis_tpms_fl"),
                    ),
                    controls=(
                        VehicleControl(
                            "set_seat_climate_front_right",
                            "select",
                            "select_option",
                            "select.jarvis_seat_right",
                            observable_entity_id="select.jarvis_seat_right",
                        ),
                        VehicleControl(
                            "unlock",
                            "lock",
                            "unlock",
                            "lock.jarvis",
                            observable_entity_id="lock.jarvis",
                        ),
                        VehicleControl("climate_on", "climate", "turn_on", "climate.jarvis"),
                        VehicleControl(
                            "set_temperature",
                            "climate",
                            "set_temperature",
                            "climate.jarvis",
                        ),
                        VehicleControl(
                            "send_route",
                            "tesla_custom",
                            "api",
                            provider_vehicle_id_env="PILOT_TESLA_VEHICLE_ID",
                        ),
                    ),
                ),
            ),
        )
        self.store = Store(":memory:", self.settings)
        self.token = self.store.register_device(
            "pilot-drive",
            "office",
            "Pilot Drive",
            ["vehicle-read", "vehicle-control", "vehicle-maintenance"],
        )
        self.read_token = self.store.register_device(
            "read-only", "office", "Read only", ["vehicle-read"]
        )
        self.integrations = FakeIntegrations()
        self.teslamate = FakeTeslaMate()
        self.app = create_app(
            self.settings,
            self.store,
            integrations_override=self.integrations,  # type: ignore[arg-type]
            teslamate_override=self.teslamate,  # type: ignore[arg-type]
        )
        self.client_context = TestClient(self.app)
        self.client = self.client_context.__enter__()

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        self.store.close()
        self.root.cleanup()
        os.environ.pop("PILOT_TESLAMATE_ADAPTER_TOKEN", None)
        os.environ.pop("PILOT_TESLA_VEHICLE_ID", None)

    def headers(self, device_id: str = "pilot-drive", token: str | None = None) -> dict[str, str]:
        return {
            "X-Pilot-Device-ID": device_id,
            "Authorization": f"Bearer {token or self.token}",
        }

    def wait_action(self, action_id: str) -> dict[str, object]:
        for _ in range(100):
            result = self.client.get(
                f"/v1/devices/pilot-drive/actions/{action_id}", headers=self.headers()
            ).json()
            if result["status"] not in {"accepted", "executing"}:
                return result
            time.sleep(0.01)
        self.fail("vehicle action did not finish")

    def create_destination(self) -> dict[str, object]:
        response = self.client.post(
            "/v1/devices/pilot-drive/vehicles/jarvis/destinations",
            headers=self.headers(),
            json={
                "name": "Work",
                "address": "1 Example Street",
                "latitude": -27.4,
                "longitude": 153.0,
                "icon": "briefcase",
                "climate_enabled": True,
                "seat_climate_mode": "cool_medium",
            },
        )
        self.assertEqual(response.status_code, 201)
        return response.json()

    def test_vehicle_projection_is_capability_scoped_and_hides_provider_ids(self) -> None:
        response = self.client.get(
            "/v1/devices/pilot-drive/vehicles/jarvis", headers=self.headers()
        )
        encoded = response.text

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["state"]["battery_percent"], 72)
        self.assertEqual(response.json()["state"]["stored_energy_kwh"], 54)
        self.assertEqual(
            response.json()["state"]["energy_to_charge_limit_kwh"], 6
        )
        self.assertEqual(
            response.json()["tyres"]["front_left"]["status"],
            "abnormal_unverified",
        )
        self.assertNotIn("sensor.jarvis", encoded)
        self.assertNotIn("teslamate_car_id", encoded)
        self.assertNotIn("vin", encoded.casefold())

        destination = self.create_destination()
        self.assertEqual(destination["seat_climate_mode"], "cool_medium")

        seat = self.client.post(
            "/v1/devices/pilot-drive/vehicles/jarvis/actions",
            headers=self.headers(),
            json={
                "action": "set_seat_climate",
                "parameters": {"mode": "cool_high"},
                "idempotency_key": "seat-cool-high-001",
            },
        )
        self.assertEqual(seat.status_code, 202)
        completed_seat = self.wait_action(seat.json()["id"])
        self.assertEqual(completed_seat["status"], "reconciled")
        self.assertIn(
            ("select", "select_option", {"option": "Cool High"}),
            self.integrations.calls,
        )

        denied = self.client.get(
            "/v1/devices/read-only/vehicles",
            headers=self.headers("read-only", self.read_token),
        )
        self.assertEqual(denied.status_code, 200)
        write_denied = self.client.post(
            "/v1/devices/read-only/vehicles/jarvis/destinations",
            headers=self.headers("read-only", self.read_token),
            json={
                "name": "Home",
                "address": "Home",
                "latitude": -27,
                "longitude": 153,
            },
        )
        self.assertEqual(write_denied.status_code, 403)

    def test_history_metrics_and_insufficient_battery_data_are_explicit(self) -> None:
        drives = self.client.get(
            "/v1/devices/pilot-drive/vehicles/jarvis/drives", headers=self.headers()
        ).json()
        charges = self.client.get(
            "/v1/devices/pilot-drive/vehicles/jarvis/charges", headers=self.headers()
        ).json()
        health = self.client.get(
            "/v1/devices/pilot-drive/vehicles/jarvis/battery-health",
            headers=self.headers(),
        ).json()

        self.assertEqual(drives["items"][0]["estimated_energy_kwh"], 7.2)
        self.assertEqual(drives["items"][0]["estimated_consumption_wh_per_km"], 360)
        self.assertEqual(charges["items"][0]["efficiency_percent"], 90)
        self.assertEqual(health["status"], "insufficient_data")
        self.assertNotIn("estimated_capacity_kwh", health)

    def test_teslamate_outage_is_explicit_and_does_not_break_current_state(self) -> None:
        self.teslamate.outage = True
        history = self.client.get(
            "/v1/devices/pilot-drive/vehicles/jarvis/drives",
            headers=self.headers(),
        )
        current = self.client.get(
            "/v1/devices/pilot-drive/vehicles/jarvis",
            headers=self.headers(),
        )

        self.assertEqual(history.status_code, 503)
        self.assertEqual(current.status_code, 200)
        self.assertEqual(current.json()["state"]["battery_percent"], 72)

    def test_sensitive_action_requires_biometric_confirmation_once(self) -> None:
        first = self.client.post(
            "/v1/devices/pilot-drive/vehicles/jarvis/actions",
            headers=self.headers(),
            json={"action": "unlock", "parameters": {}, "idempotency_key": "unlock-001"},
        ).json()
        duplicate = self.client.post(
            "/v1/devices/pilot-drive/vehicles/jarvis/actions",
            headers=self.headers(),
            json={"action": "unlock", "parameters": {}, "idempotency_key": "unlock-001"},
        ).json()

        self.assertEqual(first["status"], "pending_confirmation")
        self.assertEqual(first["id"], duplicate["id"])
        confirmed = self.client.post(
            f"/v1/devices/pilot-drive/actions/{first['id']}/confirm",
            headers=self.headers(),
            json={"biometric_verified": True},
        )
        self.assertEqual(confirmed.status_code, 202)
        completed = self.wait_action(first["id"])
        self.assertEqual(completed["status"], "reconciled")
        replay = self.client.post(
            f"/v1/devices/pilot-drive/actions/{first['id']}/confirm",
            headers=self.headers(),
            json={"biometric_verified": True},
        )
        self.assertEqual(replay.status_code, 409)

    def test_destination_workflow_delivers_route_after_climate_failure(self) -> None:
        destination = self.create_destination()
        self.assertEqual(destination["seat_climate_mode"], "cool_medium")
        self.integrations.fail_climate = True
        response = self.client.post(
            "/v1/devices/pilot-drive/vehicles/jarvis/actions",
            headers=self.headers(),
            json={
                "action": "destination_workflow",
                "parameters": {"destination_id": destination["id"]},
                "idempotency_key": "route-work-001",
            },
        )
        self.assertEqual(response.status_code, 202)
        completed = self.wait_action(response.json()["id"])
        steps = {item["step"]: item["status"] for item in completed["steps"]}
        self.assertEqual(steps["climate"], "failed")
        self.assertEqual(steps["temperature"], "failed")
        self.assertEqual(steps["front_passenger_seat"], "accepted")
        self.assertEqual(steps["route"], "accepted")
        self.assertEqual(completed["status"], "unverified")
        self.assertTrue(
            any(
                domain == "tesla_custom"
                and data.get("command") == "SEND_GPS_TO_VEHICLE"
                for domain, _service, data in self.integrations.calls
            )
        )

    def test_maintenance_due_and_bounded_receipt_attachment(self) -> None:
        created = self.client.post(
            "/v1/devices/pilot-drive/vehicles/jarvis/maintenance",
            headers=self.headers(),
            json={
                "category": "tyres",
                "title": "Rotate tyres",
                "completed_date": "2026-07-01",
                "odometer_km": 50000,
                "cost_amount": 80,
                "cost_currency": "AUD",
                "workshop": "Example Tyres",
                "notes": "Rotation completed",
                "next_due_date": "2026-08-20",
                "next_due_odometer_km": 51000,
            },
        )
        self.assertEqual(created.status_code, 201)
        maintenance_id = created.json()["id"]
        attachment = self.client.post(
            (
                "/v1/devices/pilot-drive/vehicles/jarvis/maintenance/"
                f"{maintenance_id}/attachments?filename=receipt.jpg"
            ),
            headers={**self.headers(), "Content-Type": "image/jpeg"},
            content=b"\xff\xd8\xffpilot-receipt",
        )
        self.assertEqual(attachment.status_code, 201)
        self.assertNotIn("path", attachment.json())

        items = self.client.get(
            "/v1/devices/pilot-drive/vehicles/jarvis/maintenance?odometer_km=50250",
            headers=self.headers(),
        ).json()["items"]
        self.assertEqual(items[0]["due_status"], "due_soon")
        self.assertEqual(items[0]["km_remaining"], 750)
        self.assertEqual(len(items[0]["attachments"]), 1)
        download = self.client.get(
            (
                "/v1/devices/pilot-drive/vehicles/jarvis/maintenance/"
                f"{maintenance_id}/attachments/{attachment.json()['id']}"
            ),
            headers=self.headers(),
        )
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.content, b"\xff\xd8\xffpilot-receipt")

        spoofed = self.client.post(
            (
                "/v1/devices/pilot-drive/vehicles/jarvis/maintenance/"
                f"{maintenance_id}/attachments?filename=not-really.jpg"
            ),
            headers={**self.headers(), "Content-Type": "image/jpeg"},
            content=b"not actually a jpeg",
        )
        self.assertEqual(spoofed.status_code, 422)

        denied = self.client.get(
            "/v1/devices/read-only/vehicles/jarvis/maintenance",
            headers=self.headers("read-only", self.read_token),
        )
        self.assertEqual(denied.status_code, 403)


if __name__ == "__main__":
    unittest.main()
