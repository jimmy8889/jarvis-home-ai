from __future__ import annotations

import unittest

from fastapi.testclient import TestClient
from teslamate_adapter.api import create_app
from teslamate_adapter.settings import Settings

TOKEN = "a" * 32


class FakeRepository:
    def __init__(self) -> None:
        self.read_only = True

    def ready(self) -> bool:
        return self.read_only

    def cars(self) -> list[dict[str, object]]:
        return [{"id": 1, "name": "Jarvis", "efficiency": 180}]

    def drives(
        self, car_id: int, *, limit: int, before_id: int | None
    ) -> list[dict[str, object]]:
        del car_id, before_id
        return [{"id": value, "distance": 10.0} for value in range(limit + 1, 0, -1)]

    def drive(self, car_id: int, drive_id: int) -> dict[str, object] | None:
        return {"id": drive_id, "car_id": car_id} if drive_id == 7 else None

    def drive_positions(
        self, car_id: int, drive_id: int, *, limit: int
    ) -> list[dict[str, object]]:
        del car_id, drive_id
        return [
            {"id": value, "latitude": -27.0, "longitude": 153.0}
            for value in range(limit)
        ]

    def charges(
        self, car_id: int, *, limit: int, before_id: int | None
    ) -> list[dict[str, object]]:
        del car_id, before_id
        return [
            {"id": value, "charge_energy_added": 20.0}
            for value in range(limit + 1, 0, -1)
        ]

    def battery_health(
        self, car_id: int, *, manual_baseline_kwh: float | None = None
    ) -> dict[str, object]:
        return {"status": "estimate", "car_id": car_id, "baseline": manual_baseline_kwh}


class AdapterApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = FakeRepository()
        app = create_app(
            Settings(database_url="postgresql://unused", bearer_token=TOKEN),
            self.repository,
        )
        self.client = TestClient(app, raise_server_exceptions=False)
        self.headers = {"Authorization": f"Bearer {TOKEN}"}

    def test_health_is_public_but_data_requires_bearer_token(self) -> None:
        self.assertEqual(self.client.get("/healthz").status_code, 200)
        self.assertEqual(self.client.get("/v1/cars").status_code, 401)
        response = self.client.get("/v1/cars", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"][0]["name"], "Jarvis")

    def test_ready_requires_database_read_only_mode(self) -> None:
        self.assertEqual(
            self.client.get("/readyz").json()["database_mode"], "read_only"
        )
        self.repository.read_only = False
        self.assertEqual(self.client.get("/readyz").status_code, 503)

    def test_pagination_is_bounded_and_opaque_provider_fields_are_absent(self) -> None:
        response = self.client.get("/v1/cars/1/drives?limit=2", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["items"]), 2)
        self.assertEqual(response.json()["next_cursor"], 2)
        self.assertEqual(
            self.client.get(
                "/v1/cars/1/drives?limit=201", headers=self.headers
            ).status_code,
            422,
        )

    def test_drive_positions_are_bounded(self) -> None:
        response = self.client.get(
            "/v1/cars/1/drives/7/positions?limit=2",
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["truncated"])
        self.assertEqual(len(response.json()["items"]), 2)

    def test_missing_drive_is_not_found(self) -> None:
        response = self.client.get("/v1/cars/1/drives/8", headers=self.headers)
        self.assertEqual(response.status_code, 404)

    def test_oversized_provider_response_is_rejected(self) -> None:
        class OversizedRepository(FakeRepository):
            def cars(self) -> list[dict[str, object]]:
                return [{"id": 1, "name": "x" * 2_000}]

        app = create_app(
            Settings(
                database_url="postgresql://unused",
                bearer_token=TOKEN,
                maximum_response_bytes=1_000,
            ),
            OversizedRepository(),
        )
        response = TestClient(app, raise_server_exceptions=False).get(
            "/v1/cars", headers=self.headers
        )
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["detail"], "bounded response limit exceeded")


if __name__ == "__main__":
    unittest.main()
