from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg.rows import dict_row

from .battery import battery_health


class TeslaMateRepository:
    def __init__(self, database_url: str, *, statement_timeout_ms: int = 5_000):
        self.database_url = database_url
        self.statement_timeout_ms = statement_timeout_ms

    @contextmanager
    def _connection(self) -> Iterator[psycopg.Connection[Any]]:
        options = (
            "-c default_transaction_read_only=on "
            f"-c statement_timeout={self.statement_timeout_ms} "
            "-c lock_timeout=1000"
        )
        with psycopg.connect(
            self.database_url,
            autocommit=True,
            options=options,
            row_factory=dict_row,
        ) as connection:
            yield connection

    def ready(self) -> bool:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT current_setting('transaction_read_only') AS read_only"
            ).fetchone()
        return bool(row and row["read_only"] == "on")

    def cars(self) -> list[dict[str, Any]]:
        with self._connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT id, name, model, trim_badging AS trim,
                           marketing_name, exterior_color, wheel_type, efficiency
                      FROM cars
                     ORDER BY id
                     LIMIT 20
                    """
                ).fetchall()
            )

    def drives(
        self, car_id: int, *, limit: int, before_id: int | None
    ) -> list[dict[str, Any]]:
        cursor_clause = "" if before_id is None else "AND d.id < %s"
        parameters = (
            (car_id, limit + 1) if before_id is None else (car_id, before_id, limit + 1)
        )
        with self._connection() as connection:
            return list(
                connection.execute(
                    f"""
                    SELECT d.id, d.start_date, d.end_date, d.duration_min,
                           d.distance, d.start_km, d.end_km,
                           d.start_ideal_range_km, d.end_ideal_range_km,
                           d.start_rated_range_km, d.end_rated_range_km,
                           d.outside_temp_avg, d.inside_temp_avg,
                           d.speed_max, d.power_max, d.power_min,
                           d.ascent, d.descent,
                           car.efficiency * 1000 AS configured_efficiency_wh_per_km,
                           sp.battery_level AS start_battery_level,
                           ep.battery_level AS end_battery_level,
                           sa.name AS start_address, ea.name AS end_address
                      FROM drives d
                      JOIN cars car ON car.id = d.car_id
                 LEFT JOIN positions sp ON sp.id = d.start_position_id
                 LEFT JOIN positions ep ON ep.id = d.end_position_id
                 LEFT JOIN addresses sa ON sa.id = d.start_address_id
                 LEFT JOIN addresses ea ON ea.id = d.end_address_id
                     WHERE d.car_id = %s {cursor_clause}
                     ORDER BY d.id DESC
                     LIMIT %s
                    """,
                    parameters,
                ).fetchall()
            )

    def drive(self, car_id: int, drive_id: int) -> dict[str, Any] | None:
        rows = self.drives(car_id, limit=1, before_id=drive_id + 1)
        return rows[0] if rows and rows[0]["id"] == drive_id else None

    def drive_positions(
        self, car_id: int, drive_id: int, *, limit: int
    ) -> list[dict[str, Any]]:
        with self._connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT id, date, latitude, longitude, elevation,
                           speed, power, odometer, battery_level,
                           ideal_battery_range_km, rated_battery_range_km,
                           outside_temp, inside_temp
                      FROM positions
                     WHERE car_id = %s AND drive_id = %s
                     ORDER BY date, id
                     LIMIT %s
                    """,
                    (car_id, drive_id, limit),
                ).fetchall()
            )

    def charges(
        self, car_id: int, *, limit: int, before_id: int | None
    ) -> list[dict[str, Any]]:
        cursor_clause = "" if before_id is None else "AND cp.id < %s"
        parameters = (
            (car_id, limit + 1) if before_id is None else (car_id, before_id, limit + 1)
        )
        with self._connection() as connection:
            return list(
                connection.execute(
                    f"""
                    SELECT cp.id, cp.start_date, cp.end_date, cp.duration_min,
                           cp.start_battery_level, cp.end_battery_level,
                           cp.charge_energy_added, cp.charge_energy_used,
                           cp.start_ideal_range_km, cp.end_ideal_range_km,
                           cp.start_rated_range_km, cp.end_rated_range_km,
                           cp.outside_temp_avg, cp.cost,
                           a.name AS address,
                           max(c.charger_power) AS maximum_charger_power_kw,
                           max(c.charger_voltage) AS maximum_charger_voltage,
                           max(c.charger_phases) AS maximum_charger_phases,
                           max(c.fast_charger_present::int)::boolean AS dc_fast_charger
                      FROM charging_processes cp
                 LEFT JOIN addresses a ON a.id = cp.address_id
                 LEFT JOIN charges c ON c.charging_process_id = cp.id
                     WHERE cp.car_id = %s {cursor_clause}
                  GROUP BY cp.id, a.name
                     ORDER BY cp.id DESC
                     LIMIT %s
                    """,
                    parameters,
                ).fetchall()
            )

    def battery_health(
        self,
        car_id: int,
        *,
        manual_baseline_kwh: float | None = None,
    ) -> dict[str, Any]:
        with self._connection() as connection:
            car = connection.execute(
                "SELECT efficiency FROM cars WHERE id = %s", (car_id,)
            ).fetchone()
            rows = list(
                connection.execute(
                    """
                    SELECT id, start_date, end_date, duration_min,
                           start_battery_level,
                           end_battery_level, charge_energy_added,
                           start_rated_range_km, end_rated_range_km
                      FROM charging_processes
                     WHERE car_id = %s AND end_date IS NOT NULL
                       AND start_battery_level IS NOT NULL
                       AND end_battery_level IS NOT NULL
                       AND charge_energy_added IS NOT NULL
                       AND start_rated_range_km IS NOT NULL
                       AND end_rated_range_km IS NOT NULL
                     ORDER BY end_date DESC
                     LIMIT 2000
                    """,
                    (car_id,),
                ).fetchall()
            )
            capacity_rows = list(
                connection.execute(
                    """
                    SELECT cp.id AS charging_process_id, cp.end_date,
                           cp.charge_energy_added, c.date,
                           c.rated_battery_range_km, c.usable_battery_level
                      FROM charging_processes cp
                      JOIN charges c ON c.charging_process_id = cp.id
                     WHERE cp.car_id = %s AND cp.end_date IS NOT NULL
                       AND cp.charge_energy_added IS NOT NULL
                       AND c.rated_battery_range_km IS NOT NULL
                       AND c.usable_battery_level > 0
                     ORDER BY cp.end_date DESC, c.date DESC
                     LIMIT 10000
                    """,
                    (car_id,),
                ).fetchall()
            )
        configured = (
            float(car["efficiency"]) * 1000 if car and car["efficiency"] else None
        )
        return battery_health(
            rows,
            capacity_rows=capacity_rows,
            configured_efficiency_wh_per_km=configured,
            manual_baseline_kwh=manual_baseline_kwh,
        )
