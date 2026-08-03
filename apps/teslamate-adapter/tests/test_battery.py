from __future__ import annotations

import unittest

from teslamate_adapter.battery import battery_health


class BatteryHealthTests(unittest.TestCase):
    def test_returns_estimate_with_sample_coverage_and_manual_baseline(self) -> None:
        rows = [
            {
                "start_date": "2026-01-01T00:00:00Z",
                "end_date": f"2026-01-{day:02d}T02:00:00Z",
                "duration_min": 120,
                "start_battery_level": 20,
                "end_battery_level": 80,
                "charge_energy_added": 36.0,
                "start_rated_range_km": 100.0,
                "end_rated_range_km": 300.0,
            }
            for day in range(1, 4)
        ]

        result = battery_health(rows, manual_baseline_kwh=72.0)

        self.assertEqual(result["status"], "estimate")
        self.assertEqual(result["sample_count"], 3)
        self.assertEqual(result["derived_efficiency_wh_per_km"], 180)
        self.assertEqual(result["estimated_capacity_kwh"], 67.5)
        self.assertEqual(result["baseline_source"], "manual")
        self.assertEqual(result["estimated_degradation_percent"], 6.25)
        self.assertEqual(result["date_from"], "2026-01-01T02:00:00Z")
        self.assertEqual(result["date_to"], "2026-01-03T02:00:00Z")

    def test_rejects_unqualified_sessions_instead_of_fabricating_capacity(self) -> None:
        result = battery_health(
            [
                {
                    "end_date": "2026-01-01T02:00:00Z",
                    "duration_min": 20,
                    "start_battery_level": 60,
                    "end_battery_level": 65,
                    "charge_energy_added": 2.0,
                    "start_rated_range_km": 250.0,
                    "end_rated_range_km": 260.0,
                }
            ]
        )

        self.assertEqual(result["status"], "insufficient_data")
        self.assertEqual(result["sample_count"], 0)
        self.assertNotIn("estimated_capacity_kwh", result)

    def test_uses_only_latest_one_hundred_capacity_samples(self) -> None:
        rows = [
            {
                "end_date": f"2026-01-{index + 1:03d}",
                "duration_min": 120,
                "start_battery_level": 20,
                "end_battery_level": 80,
                "charge_energy_added": 36.0,
                "start_rated_range_km": 100.0,
                "end_rated_range_km": 300.0,
            }
            for index in range(120)
        ]

        result = battery_health(rows)

        self.assertEqual(result["status"], "estimate")
        self.assertEqual(result["sample_count"], 100)


if __name__ == "__main__":
    unittest.main()
