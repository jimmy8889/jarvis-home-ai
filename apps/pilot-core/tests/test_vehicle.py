from __future__ import annotations

from datetime import date
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock

from pilot_core.config import (
    IntegrationSettings,
    Player,
    Room,
    ServerSettings,
    Settings,
    Vehicle,
    VehicleControl,
)
from pilot_core.storage import Store
from pilot_core.vehicle import VehicleService


def vehicle_settings(root: Path) -> Settings:
    return Settings(
        server=ServerSettings(
            database_path=":memory:", vehicle_asset_path=str(root / "receipts")
        ),
        integrations=IntegrationSettings(
            teslamate_adapter_url="http://teslamate-adapter.test:8781"
        ),
        rooms=(
            Room(
                id="office",
                name="Office",
                response_player_id="speaker",
                default_music_player_id="music",
            ),
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
                telemetry=(
                    ("online", "binary_sensor.jarvis_online"),
                    ("battery_percent", "sensor.jarvis_battery"),
                    ("tyre_front_left_bar", "sensor.jarvis_tpms_fl"),
                ),
                controls=(
                    VehicleControl("lock", "lock", "lock", "lock.jarvis"),
                    VehicleControl("unlock", "lock", "unlock", "lock.jarvis"),
                ),
            ),
        ),
    )


class VehicleServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = tempfile.TemporaryDirectory()
        self.settings = vehicle_settings(Path(self.root.name))
        self.store = Store(":memory:", self.settings)

    def tearDown(self) -> None:
        self.store.close()
        self.root.cleanup()

    def test_maintenance_due_logic_honours_date_and_odometer_warning_leads(self) -> None:
        item = {
            "next_due_date": "2026-08-20",
            "next_due_odometer_km": 51_000,
            "warning_days": 30,
            "warning_km": 1_000,
        }

        result = VehicleService._maintenance_due(
            item, 50_250, today=date(2026, 8, 3)
        )

        self.assertEqual(result["due_status"], "due_soon")
        self.assertEqual(result["days_remaining"], 17)
        self.assertEqual(result["km_remaining"], 750)

    def test_implausible_tyre_reading_is_not_presented_as_verified(self) -> None:
        state = {
            "state": "91",
            "attributes": {"unit_of_measurement": "psi"},
        }

        result = VehicleService._tyre_value(91.0, state)

        self.assertEqual(result["status"], "abnormal_unverified")
        self.assertGreater(result["value_bar"], 6)

    def test_high_risk_action_requires_confirmation_and_is_idempotent(self) -> None:
        service = VehicleService(
            self.settings,
            self.store,
            AsyncMock(),
            teslamate=AsyncMock(),
        )

        first, created = service.request_action(
            principal_id="phone",
            vehicle_id="jarvis",
            action="unlock",
            parameters={},
            idempotency_key="same-request",
        )
        second, created_again = service.request_action(
            principal_id="phone",
            vehicle_id="jarvis",
            action="unlock",
            parameters={},
            idempotency_key="same-request",
        )

        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(first["status"], "pending_confirmation")
        claimed = self.store.claim_vehicle_action(first["id"], "phone", confirmed=True)
        self.assertEqual(claimed["status"], "executing")
        with self.assertRaises(ValueError):
            self.store.claim_vehicle_action(first["id"], "phone", confirmed=True)

    def test_parameterized_controls_reconcile_only_the_requested_value(self) -> None:
        climate = {"state": "heat", "attributes": {"temperature": 22.0}}
        seat = {"state": "Heat Medium", "attributes": {}}
        update = {"state": "on", "attributes": {"in_progress": False}}

        self.assertTrue(
            VehicleService._observable_matches(
                "set_temperature", climate, {"temperature_c": 22}
            )
        )
        self.assertFalse(
            VehicleService._observable_matches(
                "set_temperature", climate, {"temperature_c": 24}
            )
        )
        self.assertTrue(
            VehicleService._observable_matches(
                "set_seat_heat", seat, {"level": 2}
            )
        )
        self.assertFalse(
            VehicleService._observable_matches("install_software", update)
        )


if __name__ == "__main__":
    unittest.main()
