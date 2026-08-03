from __future__ import annotations

import os
import unittest

import psycopg

from teslamate_adapter.database import TeslaMateRepository


class TeslaMate401SchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        admin_url = os.environ["TESLAMATE_FIXTURE_ADMIN_URL"]
        with psycopg.connect(admin_url, autocommit=True) as connection:
            connection.execute("INSERT INTO car_settings (id) VALUES (1)")
            connection.execute(
                """INSERT INTO cars
                   (id, eid, vid, model, efficiency, inserted_at, updated_at,
                    name, settings_id)
                   VALUES (1, 1001, 2001, '3', 0.180,
                           '2026-08-01 00:00:00', '2026-08-01 00:00:00',
                           'Jarvis', 1)"""
            )
            connection.execute(
                """INSERT INTO addresses
                   (id, name, latitude, longitude, inserted_at, updated_at)
                   VALUES
                     (1, 'Home', -27.470000, 153.020000,
                      '2026-08-01 00:00:00', '2026-08-01 00:00:00'),
                     (2, 'Work', -27.380000, 153.050000,
                      '2026-08-01 00:00:00', '2026-08-01 00:00:00')"""
            )
            connection.execute(
                """INSERT INTO drives
                   (id, start_date, end_date, distance, duration_min, car_id,
                    start_address_id, end_address_id, start_rated_range_km,
                    end_rated_range_km, speed_max, inside_temp_avg,
                    outside_temp_avg)
                   VALUES (1, '2026-08-01 01:00:00', '2026-08-01 01:30:00',
                           20, 30, 1, 1, 2, 400, 360, 92, 21.5, 18.0)"""
            )
            connection.execute(
                """INSERT INTO positions
                   (id, date, latitude, longitude, speed, power, car_id,
                    drive_id, battery_level, rated_battery_range_km,
                    ideal_battery_range_km)
                   VALUES
                     (1, '2026-08-01 01:00:00', -27.470000, 153.020000,
                      0, 0, 1, 1, 80, 400, 420),
                     (2, '2026-08-01 01:30:00', -27.380000, 153.050000,
                      0, 0, 1, 1, 70, 360, 378)"""
            )
            connection.execute(
                "UPDATE drives SET start_position_id = 1, end_position_id = 2 WHERE id = 1"
            )
            connection.execute(
                """INSERT INTO charging_processes
                   (id, start_date, end_date, charge_energy_added,
                    charge_energy_used, start_battery_level, end_battery_level,
                    duration_min, car_id, position_id, address_id,
                    start_rated_range_km, end_rated_range_km)
                   VALUES (1, '2026-08-01 03:00:00', '2026-08-01 04:00:00',
                           20, 22, 20, 80, 60, 1, 1, 1, 100, 220)"""
            )
            connection.execute(
                """INSERT INTO charges
                   (id, date, charge_energy_added, charger_power,
                    ideal_battery_range_km, charging_process_id,
                    rated_battery_range_km, usable_battery_level,
                    fast_charger_present)
                   VALUES (1, '2026-08-01 04:00:00', 20, 11, 230, 1,
                           220, 80, false)"""
            )
            connection.execute(
                "CREATE ROLE pilot_fixture_reader LOGIN PASSWORD 'fixture-reader'"
            )
            connection.execute(
                "ALTER ROLE pilot_fixture_reader SET default_transaction_read_only = on"
            )
            connection.execute(
                "ALTER ROLE pilot_fixture_reader SET statement_timeout = '5s'"
            )
            connection.execute(
                "GRANT CONNECT ON DATABASE teslamate TO pilot_fixture_reader"
            )
            connection.execute("GRANT USAGE ON SCHEMA public TO pilot_fixture_reader")
            connection.execute(
                """GRANT SELECT ON cars, drives, positions, addresses, geofences,
                   charging_processes, charges TO pilot_fixture_reader"""
            )
        cls.reader_url = admin_url.replace(
            "postgres:fixture-postgres", "pilot_fixture_reader:fixture-reader"
        )
        cls.repository = TeslaMateRepository(cls.reader_url)

    def test_all_bounded_queries_compile_against_teslamate_401(self) -> None:
        self.assertTrue(self.repository.ready())
        self.assertEqual(len(self.repository.cars()), 1)
        self.assertEqual(len(self.repository.drives(1, limit=10, before_id=None)), 1)
        self.assertIsNotNone(self.repository.drive(1, 1))
        self.assertEqual(len(self.repository.drive_positions(1, 1, limit=10)), 2)
        self.assertEqual(len(self.repository.charges(1, limit=10, before_id=None)), 1)
        health = self.repository.battery_health(1)
        self.assertEqual(health["status"], "estimate")

    def test_results_match_teslamate_dashboard_fixture(self) -> None:
        drive = self.repository.drive(1, 1)
        assert drive is not None
        self.assertEqual(drive["start_address"], "Home")
        self.assertEqual(drive["end_address"], "Work")
        self.assertEqual(drive["start_battery_level"], 80)
        self.assertEqual(drive["end_battery_level"], 70)
        self.assertEqual(drive["configured_efficiency_wh_per_km"], 180)

        charge = self.repository.charges(1, limit=10, before_id=None)[0]
        self.assertEqual(charge["address"], "Home")
        self.assertEqual(charge["charge_energy_added"], 20)
        self.assertEqual(charge["charge_energy_used"], 22)
        self.assertEqual(charge["maximum_charger_power_kw"], 11)

        health = self.repository.battery_health(1)
        self.assertEqual(health["sample_count"], 1)
        self.assertEqual(health["baseline_source"], "observed_maximum")
        self.assertEqual(health["estimated_degradation_percent"], 0)

    def test_database_role_cannot_write(self) -> None:
        with psycopg.connect(self.reader_url, autocommit=True) as connection:
            with self.assertRaises(psycopg.errors.ReadOnlySqlTransaction):
                connection.execute("DELETE FROM cars")


if __name__ == "__main__":
    unittest.main()
