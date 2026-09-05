from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import gzip
import json
import math
from pathlib import Path
import shutil
import threading
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from .config import ENTITY, Settings
from .models import Plan
from .parsing import active_price_pair, floor_time, numeric_state


class OutcomeRecorder:
    """Integrate live telemetry into auditable five-minute outcome rows.

    Home Assistant exposes instantaneous powers rather than a complete set of
    five-minute energy counters.  Each row therefore records its measured
    coverage and uses zero-order-hold integration only for the covered seconds;
    gaps are explicit and are never silently replaced with plan predictions.
    """

    SCHEMA_VERSION = 2
    INTERVAL_MINUTES = 5

    def __init__(self, settings: Settings):
        self.settings = settings
        self.timezone = ZoneInfo(settings.timezone)
        self.state_path = settings.data_dir / "outcome-state.json"
        self.summary_path = settings.data_dir / "acceptance-summary.json"
        self.outcome_dir = settings.data_dir / "outcomes"
        self._lock = threading.Lock()
        self._state = self._load_state()
        self._summary = self._load_summary()

    @staticmethod
    def _parse_datetime(value: Any) -> datetime | None:
        if not value:
            return None
        try:
            result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
        if result.tzinfo is None:
            return None
        return result.astimezone(timezone.utc)

    def _parse_local_datetime(self, value: Any) -> datetime | None:
        """Parse HA input_datetime values, which may omit their timezone."""
        if not value:
            return None
        try:
            result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
        if result.tzinfo is None:
            result = result.replace(tzinfo=self.timezone)
        return result.astimezone(timezone.utc)

    @staticmethod
    def _finite(value: Any) -> float | None:
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None
        return result if math.isfinite(result) else None

    @staticmethod
    def _power_kw(states: dict[str, dict[str, Any]], entity_id: str) -> float | None:
        value = numeric_state(states, entity_id, float("nan"))
        if not math.isfinite(value):
            return None
        unit = str(
            states.get(entity_id, {}).get("attributes", {}).get("unit_of_measurement", "")
        ).strip().lower()
        if unit in {"w", "watt", "watts"}:
            return value / 1000
        if unit in {"kw", "kilowatt", "kilowatts"}:
            return value
        return value / 1000 if abs(value) > 100 else value

    def _load_state(self) -> dict[str, Any]:
        try:
            raw = json.loads(self.state_path.read_text())
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {"schema_version": self.SCHEMA_VERSION, "current": None}
        if raw.get("schema_version") != self.SCHEMA_VERSION:
            return {"schema_version": self.SCHEMA_VERSION, "current": None}
        current = raw.get("current")
        return {
            "schema_version": self.SCHEMA_VERSION,
            "current": current if isinstance(current, dict) else None,
        }

    def _load_summary(self) -> dict[str, Any]:
        try:
            raw = json.loads(self.summary_path.read_text())
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return self._empty_summary()
        if not isinstance(raw, dict) or raw.get("schema_version") != self.SCHEMA_VERSION:
            return self._empty_summary()
        return raw

    @classmethod
    def _empty_summary(cls) -> dict[str, Any]:
        return {
            "schema_version": cls.SCHEMA_VERSION,
            "generated_at": None,
            "status": "collecting",
            "daily": [],
            "rolling_7d": {},
            "rolling_30d": {},
        }

    @staticmethod
    def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False))
        temporary.replace(path)

    def _save_state(self) -> None:
        self._atomic_json(self.state_path, self._state)

    def _snapshot(
        self,
        states: dict[str, dict[str, Any]],
        plan: Plan | None,
        observed_at: datetime,
    ) -> dict[str, Any]:
        prices = active_price_pair(
            states.get(ENTITY["amber_fit"], {}),
            states.get(ENTITY["amber_import"], {}),
            observed_at.astimezone(self.timezone),
            self.timezone,
            self.settings.amber_interval_minutes,
        )
        fit, imports = prices if prices else (None, None)
        interval_start = floor_time(
            observed_at.astimezone(self.timezone),
            self.INTERVAL_MINUTES,
        ).astimezone(timezone.utc)
        planned_interval = None
        if plan is not None:
            planned_interval = next(
                (
                    item
                    for item in plan.intervals
                    if item.start <= observed_at.astimezone(item.start.tzinfo)
                    < item.start + timedelta(minutes=item.duration_minutes)
                ),
                None,
            )
        ev_power_readings = [
            self._power_kw(states, entity_id)
            for entity_id in (ENTITY["ev_power"], ENTITY["ev_power_local"])
        ]
        ev_power_readings = [
            value for value in ev_power_readings if value is not None
        ]
        return {
            "interval_start": interval_start.isoformat(),
            "observed_at": observed_at.astimezone(timezone.utc).isoformat(),
            "pv_kw": self._power_kw(states, ENTITY["pv_power"]),
            "load_kw": self._power_kw(states, ENTITY["home_load"]),
            "grid_kw": self._power_kw(states, ENTITY["grid_power"]),
            "battery_kw": self._power_kw(states, ENTITY["battery_soc_heartbeat"]),
            "hot_water_kw": self._power_kw(states, ENTITY["hot_water_power"]),
            "ev_kw": max(ev_power_readings) if ev_power_readings else None,
            "hot_water_source": str(
                states.get(ENTITY["hot_water_source"], {}).get("state", "unknown")
            ),
            "ev_source": str(
                states.get(ENTITY["ev_source"], {}).get("state", "unknown")
            ),
            "ev_soc_pct": self._finite(
                numeric_state(states, ENTITY["ev_soc"], float("nan"))
            ),
            "ev_departure": (
                parsed_departure.isoformat()
                if (
                    parsed_departure := self._parse_local_datetime(
                        states.get(ENTITY["ev_departure"], {}).get("state")
                    )
                )
                else None
            ),
            "ev_target_soc_pct": plan.ev_target_soc_pct if plan else None,
            "morning_takeover": (
                plan.morning_takeover.isoformat()
                if plan and plan.morning_takeover
                else None
            ),
            "evening_crossover": (
                plan.evening_crossover.isoformat()
                if plan and plan.evening_crossover
                else None
            ),
            "actuator_status": str(
                states.get(ENTITY["actuator_status"], {}).get("state", "unknown")
            ),
            "actuation_ready": (
                str(states.get(ENTITY["actuation_ready"], {}).get("state", "unknown"))
                == "on"
            ),
            "soc_pct": self._finite(numeric_state(states, ENTITY["battery_soc"], float("nan"))),
            "import_price": imports[0] if imports else None,
            "export_price": fit[0] if fit else None,
            "plan_id": plan.plan_id if plan else None,
            "plan_mode": plan.battery_mode if plan else None,
            "protected_soc_pct": plan.protected_soc_pct if plan else None,
            "ev_mandatory": plan.ev_mandatory if plan else False,
            "ev_unmet_kwh": plan.ev_unmet_kwh if plan else 0.0,
            "planned_battery_kw": planned_interval.battery_kw if planned_interval else None,
            "planned_site_grid_kw": planned_interval.site_grid_kw if planned_interval else None,
            "planned_soc_end_pct": planned_interval.soc_end_pct if planned_interval else None,
            "planned_net_benefit": -planned_interval.cost if planned_interval else None,
        }

    @staticmethod
    def _new_accumulator(snapshot: dict[str, Any]) -> dict[str, Any]:
        interval_start = datetime.fromisoformat(snapshot["interval_start"])
        return {
            "interval_start": snapshot["interval_start"],
            "interval_end": (
                interval_start + timedelta(minutes=OutcomeRecorder.INTERVAL_MINUTES)
            ).isoformat(),
            "first_observed_at": snapshot["observed_at"],
            "last_observed_at": snapshot["observed_at"],
            "values": snapshot,
            "telemetry_coverage_seconds": 0.0,
            "price_coverage_seconds": 0.0,
            "solar_kwh": 0.0,
            "load_kwh": 0.0,
            "grid_import_kwh": 0.0,
            "grid_export_kwh": 0.0,
            "battery_charge_kwh": 0.0,
            "battery_discharge_kwh": 0.0,
            "hot_water_kwh": 0.0,
            "hot_water_active_seconds": 0.0,
            "hot_water_coverage_seconds": 0.0,
            "ev_kwh": 0.0,
            "house_solar_kwh": 0.0,
            "house_battery_kwh": 0.0,
            "house_grid_kwh": 0.0,
            "hot_water_solar_kwh": 0.0,
            "hot_water_battery_kwh": 0.0,
            "hot_water_grid_kwh": 0.0,
            "ev_solar_kwh": 0.0,
            "ev_battery_kwh": 0.0,
            "ev_grid_kwh": 0.0,
            "import_cost": 0.0,
            "export_revenue": 0.0,
            "wear_cost": 0.0,
            "negative_fit_seconds": 0.0,
            "negative_fit_export_kwh": 0.0,
            "soc_start_pct": snapshot.get("soc_pct"),
            "soc_end_pct": snapshot.get("soc_pct"),
            "minimum_soc_pct": snapshot.get("soc_pct"),
            "plan_ids": [snapshot["plan_id"]] if snapshot.get("plan_id") else [],
            "protected_soc_pct": snapshot.get("protected_soc_pct"),
            "ev_mandatory": bool(snapshot.get("ev_mandatory")),
            "ev_unmet_kwh": snapshot.get("ev_unmet_kwh", 0.0),
            "planned_battery_kw": snapshot.get("planned_battery_kw"),
            "planned_site_grid_kw": snapshot.get("planned_site_grid_kw"),
            "planned_soc_end_pct": snapshot.get("planned_soc_end_pct"),
            "planned_net_benefit": snapshot.get("planned_net_benefit"),
            "morning_takeover": snapshot.get("morning_takeover"),
            "evening_crossover": snapshot.get("evening_crossover"),
            "ev_departure": snapshot.get("ev_departure"),
            "ev_target_soc_pct": snapshot.get("ev_target_soc_pct"),
            "ev_departure_soc_pct": None,
            "actuator_rejections": 0,
            "actuator_failures": 0,
            "actuator_unconfirmed_seconds": 0.0,
        }

    def _integrate_until(self, accumulator: dict[str, Any], end: datetime) -> None:
        last_at = self._parse_datetime(accumulator.get("last_observed_at"))
        interval_end = self._parse_datetime(accumulator.get("interval_end"))
        if last_at is None or interval_end is None:
            return
        end = min(end.astimezone(timezone.utc), interval_end)
        seconds = max(0.0, (end - last_at).total_seconds())
        if seconds <= 0:
            return
        hours = seconds / 3600
        values = accumulator.get("values", {})
        core = [values.get(key) for key in ("pv_kw", "load_kw", "grid_kw", "battery_kw")]
        if all(self._finite(value) is not None for value in core):
            accumulator["telemetry_coverage_seconds"] += seconds
        if self._finite(values.get("import_price")) is not None and self._finite(
            values.get("export_price")
        ) is not None:
            accumulator["price_coverage_seconds"] += seconds

        def add_energy(field: str, power_key: str) -> None:
            power = self._finite(values.get(power_key))
            if power is not None:
                accumulator[field] += max(0.0, power) * hours

        add_energy("solar_kwh", "pv_kw")
        add_energy("load_kwh", "load_kw")
        add_energy("hot_water_kwh", "hot_water_kw")
        add_energy("ev_kwh", "ev_kw")
        hot_water_power = max(
            0.0,
            self._finite(values.get("hot_water_kw")) or 0.0,
        )
        ev_power = max(0.0, self._finite(values.get("ev_kw")) or 0.0)
        for prefix, power, source in (
            (
                "hot_water",
                hot_water_power,
                str(values.get("hot_water_source", "unknown")),
            ),
            ("ev", ev_power, str(values.get("ev_source", "unknown"))),
        ):
            if source in {"solar", "battery", "grid"}:
                accumulator[f"{prefix}_{source}_kwh"] += power * hours

        # Source attribution follows the physical priority contract. Flexible
        # loads use their independently classified source; remaining measured
        # PV serves ordinary house load before stationary battery and grid.
        load_kw = max(0.0, self._finite(values.get("load_kw")) or 0.0)
        house_kw = max(0.0, load_kw - hot_water_power)
        pv_kw = max(0.0, self._finite(values.get("pv_kw")) or 0.0)
        battery_kw_for_house = max(
            0.0,
            self._finite(values.get("battery_kw")) or 0.0,
        )
        known_flexible_solar = (
            hot_water_power if values.get("hot_water_source") == "solar" else 0.0
        ) + (ev_power if values.get("ev_source") == "solar" else 0.0)
        house_solar_kw = min(house_kw, max(0.0, pv_kw - known_flexible_solar))
        house_battery_kw = min(
            max(0.0, house_kw - house_solar_kw),
            battery_kw_for_house,
        )
        accumulator["house_solar_kwh"] += house_solar_kw * hours
        accumulator["house_battery_kwh"] += house_battery_kw * hours
        accumulator["house_grid_kwh"] += max(
            0.0,
            house_kw - house_solar_kw - house_battery_kw,
        ) * hours
        actuator_status = str(values.get("actuator_status", ""))
        if actuator_status.startswith("rejected"):
            accumulator["actuator_rejections"] = 1
        if actuator_status.startswith("failed"):
            accumulator["actuator_failures"] = 1
        if not bool(values.get("actuation_ready")):
            accumulator["actuator_unconfirmed_seconds"] += seconds
        hot_water_kw = self._finite(values.get("hot_water_kw"))
        if hot_water_kw is not None:
            accumulator["hot_water_coverage_seconds"] += seconds
            if hot_water_kw >= 0.2:
                accumulator["hot_water_active_seconds"] += seconds
        grid_kw = self._finite(values.get("grid_kw"))
        import_price = self._finite(values.get("import_price"))
        export_price = self._finite(values.get("export_price"))
        if grid_kw is not None:
            imported = max(0.0, grid_kw) * hours
            exported = max(0.0, -grid_kw) * hours
            accumulator["grid_import_kwh"] += imported
            accumulator["grid_export_kwh"] += exported
            if import_price is not None:
                accumulator["import_cost"] += imported * import_price
            if export_price is not None:
                accumulator["export_revenue"] += exported * export_price
                if export_price < 0:
                    accumulator["negative_fit_seconds"] += seconds
                    accumulator["negative_fit_export_kwh"] += exported
        battery_kw = self._finite(values.get("battery_kw"))
        if battery_kw is not None:
            discharged = max(0.0, battery_kw) * hours
            accumulator["battery_discharge_kwh"] += discharged
            accumulator["battery_charge_kwh"] += max(0.0, -battery_kw) * hours
            accumulator["wear_cost"] += discharged * self.settings.battery_wear_per_kwh
        for timestamp_key, result_key, value_key in (
            ("morning_takeover", "morning_takeover_soc_pct", "soc_pct"),
            ("evening_crossover", "evening_crossover_soc_pct", "soc_pct"),
            ("ev_departure", "ev_departure_soc_pct", "ev_soc_pct"),
        ):
            event_at = self._parse_datetime(values.get(timestamp_key))
            if event_at is not None and last_at <= event_at < end:
                event_value = self._finite(values.get(value_key))
                if event_value is not None:
                    accumulator[result_key] = event_value
        accumulator["last_observed_at"] = end.isoformat()

    def _apply_snapshot(self, accumulator: dict[str, Any], snapshot: dict[str, Any]) -> None:
        accumulator["last_observed_at"] = snapshot["observed_at"]
        accumulator["values"] = snapshot
        soc = self._finite(snapshot.get("soc_pct"))
        if soc is not None:
            accumulator["soc_end_pct"] = soc
            previous_min = self._finite(accumulator.get("minimum_soc_pct"))
            accumulator["minimum_soc_pct"] = soc if previous_min is None else min(previous_min, soc)
        plan_id = snapshot.get("plan_id")
        if plan_id and plan_id not in accumulator["plan_ids"]:
            accumulator["plan_ids"].append(plan_id)
        for key in (
            "protected_soc_pct",
            "ev_mandatory",
            "ev_unmet_kwh",
            "planned_battery_kw",
            "planned_site_grid_kw",
            "planned_soc_end_pct",
            "planned_net_benefit",
            "morning_takeover",
            "evening_crossover",
            "ev_departure",
            "ev_target_soc_pct",
        ):
            if snapshot.get(key) is not None:
                accumulator[key] = snapshot[key]

    def _finalize(self, accumulator: dict[str, Any]) -> dict[str, Any]:
        coverage = min(300.0, float(accumulator["telemetry_coverage_seconds"]))
        price_coverage = min(300.0, float(accumulator["price_coverage_seconds"]))
        if coverage >= 240 and price_coverage >= 240:
            status = "measured"
        elif coverage > 0 or price_coverage > 0:
            status = "partial"
        else:
            status = "no_observation"
        protected = self._finite(accumulator.get("protected_soc_pct"))
        minimum_soc = self._finite(accumulator.get("minimum_soc_pct"))
        protected_breach = (
            protected is not None
            and minimum_soc is not None
            and minimum_soc < protected - 0.5
        )
        row = {
            "schema_version": self.SCHEMA_VERSION,
            "interval_start": accumulator["interval_start"],
            "interval_end": accumulator["interval_end"],
            "local_date": self._parse_datetime(accumulator["interval_start"])
            .astimezone(self.timezone)
            .date()
            .isoformat(),
            "status": status,
            "measurement_method": "zero_order_hold_live_telemetry",
            "telemetry_coverage_seconds": round(coverage, 1),
            "telemetry_coverage_pct": round(coverage / 3, 1),
            "price_coverage_seconds": round(price_coverage, 1),
            "plan_ids": accumulator.get("plan_ids", []),
            "solar_kwh": round(accumulator["solar_kwh"], 5),
            "load_kwh": round(accumulator["load_kwh"], 5),
            "grid_import_kwh": round(accumulator["grid_import_kwh"], 5),
            "grid_export_kwh": round(accumulator["grid_export_kwh"], 5),
            "battery_charge_kwh": round(accumulator["battery_charge_kwh"], 5),
            "battery_discharge_kwh": round(accumulator["battery_discharge_kwh"], 5),
            "hot_water_kwh": round(accumulator["hot_water_kwh"], 5),
            "hot_water_hours": round(
                accumulator["hot_water_active_seconds"] / 3600,
                5,
            ),
            "hot_water_coverage_seconds": round(
                min(300.0, accumulator["hot_water_coverage_seconds"]),
                1,
            ),
            "ev_kwh": round(accumulator["ev_kwh"], 5),
            "import_cost": round(accumulator["import_cost"], 6),
            "export_revenue": round(accumulator["export_revenue"], 6),
            "wear_cost": round(accumulator["wear_cost"], 6),
            "net_benefit_after_wear": round(
                accumulator["export_revenue"]
                - accumulator["import_cost"]
                - accumulator["wear_cost"],
                6,
            ),
            "soc_start_pct": accumulator.get("soc_start_pct"),
            "soc_end_pct": accumulator.get("soc_end_pct"),
            "minimum_soc_pct": accumulator.get("minimum_soc_pct"),
            "protected_soc_pct": accumulator.get("protected_soc_pct"),
            "protected_soc_breach": protected_breach,
            "negative_fit_seconds": round(accumulator["negative_fit_seconds"], 1),
            "negative_fit_export_kwh": round(accumulator["negative_fit_export_kwh"], 5),
            "negative_fit_zero_export_met": (
                accumulator["negative_fit_seconds"] <= 0
                or accumulator["negative_fit_export_kwh"] <= 0.01
            ),
            "ev_mandatory": bool(accumulator.get("ev_mandatory")),
            "ev_unmet_kwh": round(float(accumulator.get("ev_unmet_kwh", 0.0)), 3),
            "planned_battery_kw": accumulator.get("planned_battery_kw"),
            "planned_site_grid_kw": accumulator.get("planned_site_grid_kw"),
            "planned_soc_end_pct": accumulator.get("planned_soc_end_pct"),
            "planned_net_benefit": accumulator.get("planned_net_benefit"),
            "house_solar_kwh": round(accumulator["house_solar_kwh"], 5),
            "house_battery_kwh": round(accumulator["house_battery_kwh"], 5),
            "house_grid_kwh": round(accumulator["house_grid_kwh"], 5),
            "hot_water_solar_kwh": round(accumulator["hot_water_solar_kwh"], 5),
            "hot_water_battery_kwh": round(accumulator["hot_water_battery_kwh"], 5),
            "hot_water_grid_kwh": round(accumulator["hot_water_grid_kwh"], 5),
            "ev_solar_kwh": round(accumulator["ev_solar_kwh"], 5),
            "ev_battery_kwh": round(accumulator["ev_battery_kwh"], 5),
            "ev_grid_kwh": round(accumulator["ev_grid_kwh"], 5),
            "morning_takeover_soc_pct": accumulator.get("morning_takeover_soc_pct"),
            "evening_crossover_soc_pct": accumulator.get("evening_crossover_soc_pct"),
            "ev_departure_soc_pct": accumulator.get("ev_departure_soc_pct"),
            "ev_target_soc_pct": accumulator.get("ev_target_soc_pct"),
            "ev_departure_success": (
                accumulator.get("ev_departure_soc_pct") is not None
                and accumulator.get("ev_target_soc_pct") is not None
                and float(accumulator["ev_departure_soc_pct"])
                + 0.1
                >= float(accumulator["ev_target_soc_pct"])
            ),
            "actuator_rejections": int(accumulator["actuator_rejections"]),
            "actuator_failures": int(accumulator["actuator_failures"]),
            "actuator_unconfirmed_seconds": round(
                accumulator["actuator_unconfirmed_seconds"],
                1,
            ),
        }
        return row

    def _missing_row(self, interval_start: datetime) -> dict[str, Any]:
        accumulator = self._new_accumulator({
            "interval_start": interval_start.isoformat(),
            "observed_at": interval_start.isoformat(),
            "soc_pct": None,
            "plan_id": None,
            "protected_soc_pct": None,
            "ev_mandatory": False,
            "ev_unmet_kwh": 0.0,
            "planned_battery_kw": None,
            "planned_site_grid_kw": None,
            "planned_soc_end_pct": None,
        })
        accumulator["values"] = {}
        return self._finalize(accumulator)

    def _row_exists(self, path: Path, interval_start: str) -> bool:
        if not path.exists():
            return False
        try:
            lines: Iterable[str]
            if path.suffix == ".gz":
                with gzip.open(path, "rt") as handle:
                    lines = list(handle)
            else:
                lines = path.read_text().splitlines()
            for line in lines:
                try:
                    if json.loads(line).get("interval_start") == interval_start:
                        return True
                except json.JSONDecodeError:
                    continue
        except OSError:
            return False
        return False

    def _write_row(self, row: dict[str, Any]) -> bool:
        self.outcome_dir.mkdir(parents=True, exist_ok=True)
        path = self.outcome_dir / f"{row['local_date']}.jsonl"
        if self._row_exists(path, row["interval_start"]):
            return False
        with path.open("a") as handle:
            handle.write(json.dumps(row, separators=(",", ":"), allow_nan=False) + "\n")
        return True

    def observe(
        self,
        raw_states: list[dict[str, Any]],
        plan: Plan | None,
        observed_at: datetime | None = None,
    ) -> list[dict[str, Any]]:
        observed_at = (observed_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
        states = {str(item.get("entity_id", "")): item for item in raw_states}
        snapshot = self._snapshot(states, plan, observed_at)
        completed: list[dict[str, Any]] = []
        with self._lock:
            current = self._state.get("current")
            if not isinstance(current, dict):
                self._state["current"] = self._new_accumulator(snapshot)
                self._save_state()
                return completed
            current_start = self._parse_datetime(current.get("interval_start"))
            next_start = self._parse_datetime(snapshot.get("interval_start"))
            if current_start is None or next_start is None or next_start < current_start:
                self._state["current"] = self._new_accumulator(snapshot)
                self._save_state()
                return completed
            if next_start == current_start:
                self._integrate_until(current, observed_at)
                self._apply_snapshot(current, snapshot)
                self._save_state()
                return completed

            current_end = current_start + timedelta(minutes=self.INTERVAL_MINUTES)
            self._integrate_until(current, current_end)
            # A sample taken on the settlement boundary is also the best SOC
            # endpoint for the interval that just closed (power/prices belong
            # to the new interval and are deliberately not back-applied).
            if abs((observed_at - current_end).total_seconds()) <= 60:
                boundary_soc = self._finite(snapshot.get("soc_pct"))
                if boundary_soc is not None:
                    current["soc_end_pct"] = boundary_soc
                    previous_min = self._finite(current.get("minimum_soc_pct"))
                    current["minimum_soc_pct"] = (
                        boundary_soc
                        if previous_min is None
                        else min(previous_min, boundary_soc)
                    )
            row = self._finalize(current)
            if self._write_row(row):
                completed.append(row)
            missing_start = current_end
            while missing_start < next_start:
                missing = self._missing_row(missing_start)
                if self._write_row(missing):
                    completed.append(missing)
                missing_start += timedelta(minutes=self.INTERVAL_MINUTES)
            self._state["current"] = self._new_accumulator(snapshot)
            self._save_state()
            if completed:
                self._summary = self._build_summary(observed_at.astimezone(self.timezone).date())
                self._atomic_json(self.summary_path, self._summary)
                self._prune_and_compress(observed_at.astimezone(self.timezone).date())
            return completed

    def _iter_rows(self) -> Iterable[dict[str, Any]]:
        if not self.outcome_dir.exists():
            return
        for path in sorted(self.outcome_dir.glob("????-??-??.jsonl*")):
            try:
                if path.name.endswith(".jsonl.gz"):
                    handle_context = gzip.open(path, "rt")
                elif path.name.endswith(".jsonl"):
                    handle_context = path.open()
                else:
                    continue
                with handle_context as handle:
                    for line in handle:
                        try:
                            row = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if isinstance(row, dict):
                            yield row
            except OSError:
                continue

    @staticmethod
    def _aggregate(rows: list[dict[str, Any]], expected_intervals: int) -> dict[str, Any]:
        measured = [row for row in rows if row.get("status") == "measured"]
        negative = [row for row in measured if float(row.get("negative_fit_seconds", 0)) > 0]
        by_date: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            by_date.setdefault(str(row.get("local_date", "unknown")), []).append(row)
        hot_water_assessable_days = 0
        hot_water_completed_days = 0
        for day_rows in by_date.values():
            coverage_seconds = sum(
                float(row.get("hot_water_coverage_seconds", 0.0))
                for row in day_rows
            )
            if coverage_seconds < 24 * 3600 * 0.80:
                continue
            hot_water_assessable_days += 1
            hot_water_hours = sum(
                float(row.get("hot_water_hours", 0.0))
                for row in day_rows
                if row.get("status") == "measured"
            )
            if hot_water_hours + 1e-6 >= 3.0:
                hot_water_completed_days += 1
        negative_violations = sum(
            not bool(row.get("negative_fit_zero_export_met", False)) for row in negative
        )
        protected_breaches = sum(
            bool(row.get("protected_soc_breach", False)) for row in measured
        )
        morning_soc = [
            float(row["morning_takeover_soc_pct"])
            for row in measured
            if row.get("morning_takeover_soc_pct") is not None
        ]
        evening_soc = [
            float(row["evening_crossover_soc_pct"])
            for row in measured
            if row.get("evening_crossover_soc_pct") is not None
        ]
        ev_departures = [
            row for row in measured if row.get("ev_departure_soc_pct") is not None
        ]
        planned_benefit = sum(
            float(row.get("planned_net_benefit") or 0.0) for row in measured
        )
        realized_benefit = sum(
            float(row.get("net_benefit_after_wear", 0)) for row in measured
        )
        result = {
            "expected_intervals": expected_intervals,
            "recorded_intervals": len(rows),
            "measured_intervals": len(measured),
            "calendar_coverage_pct": round(100 * len(measured) / max(1, expected_intervals), 1),
            "recorded_quality_pct": round(100 * len(measured) / max(1, len(rows)), 1),
            "solar_kwh": round(sum(float(row.get("solar_kwh", 0)) for row in measured), 2),
            "load_kwh": round(sum(float(row.get("load_kwh", 0)) for row in measured), 2),
            "grid_import_kwh": round(sum(float(row.get("grid_import_kwh", 0)) for row in measured), 2),
            "grid_export_kwh": round(sum(float(row.get("grid_export_kwh", 0)) for row in measured), 2),
            "hot_water_hours": round(sum(float(row.get("hot_water_hours", 0)) for row in measured), 2),
            "ev_kwh": round(sum(float(row.get("ev_kwh", 0)) for row in measured), 2),
            "net_benefit_after_wear": round(realized_benefit, 2),
            "planned_net_benefit": round(planned_benefit, 2),
            "plan_value_variance": round(realized_benefit - planned_benefit, 2),
            "source_allocation_kwh": {
                source: round(sum(float(row.get(source, 0)) for row in measured), 2)
                for source in (
                    "house_solar_kwh",
                    "house_battery_kwh",
                    "house_grid_kwh",
                    "hot_water_solar_kwh",
                    "hot_water_battery_kwh",
                    "hot_water_grid_kwh",
                    "ev_solar_kwh",
                    "ev_battery_kwh",
                    "ev_grid_kwh",
                )
            },
            "negative_fit_intervals": len(negative),
            "negative_fit_export_violations": negative_violations,
            "negative_fit_zero_export_success_pct": (
                round(100 * (len(negative) - negative_violations) / len(negative), 1)
                if negative
                else None
            ),
            "protected_soc_breaches": protected_breaches,
            "protected_soc_compliance_pct": (
                round(100 * (len(measured) - protected_breaches) / len(measured), 1)
                if measured
                else None
            ),
            "hot_water_service_days_assessed": hot_water_assessable_days,
            "hot_water_service_days_completed": hot_water_completed_days,
            "hot_water_completion_pct": (
                round(100 * hot_water_completed_days / hot_water_assessable_days, 1)
                if hot_water_assessable_days
                else None
            ),
            "ev_requirement_shortfall_intervals": sum(
                bool(row.get("ev_mandatory")) and float(row.get("ev_unmet_kwh", 0)) > 0.05
                for row in measured
            ),
            "morning_takeovers_assessed": len(morning_soc),
            "morning_takeover_5_10_pct": sum(5 <= soc <= 10 for soc in morning_soc),
            "morning_takeover_target_pct": (
                round(100 * sum(5 <= soc <= 10 for soc in morning_soc) / len(morning_soc), 1)
                if morning_soc
                else None
            ),
            "evening_crossovers_assessed": len(evening_soc),
            "evening_crossover_98_pct": sum(soc >= 98 for soc in evening_soc),
            "evening_crossover_target_pct": (
                round(100 * sum(soc >= 98 for soc in evening_soc) / len(evening_soc), 1)
                if evening_soc
                else None
            ),
            "ev_departures_assessed": len(ev_departures),
            "ev_departures_successful": sum(
                bool(row.get("ev_departure_success")) for row in ev_departures
            ),
            "ev_departure_success_pct": (
                round(
                    100
                    * sum(bool(row.get("ev_departure_success")) for row in ev_departures)
                    / len(ev_departures),
                    1,
                )
                if ev_departures
                else None
            ),
            "actuator_rejections": sum(
                int(row.get("actuator_rejections", 0)) for row in measured
            ),
            "actuator_failures": sum(
                int(row.get("actuator_failures", 0)) for row in measured
            ),
            "actuator_unconfirmed_minutes": round(
                sum(float(row.get("actuator_unconfirmed_seconds", 0)) for row in measured)
                / 60,
                1,
            ),
        }
        return result

    def _build_summary(self, today: date) -> dict[str, Any]:
        cutoff = today - timedelta(days=29)
        unique: dict[str, dict[str, Any]] = {}
        for row in self._iter_rows():
            local_date = str(row.get("local_date", ""))
            if local_date < cutoff.isoformat() or local_date > today.isoformat():
                continue
            interval_start = str(row.get("interval_start", ""))
            if interval_start:
                unique[interval_start] = row
        rows = list(unique.values())
        daily = []
        for day_text in sorted({str(row.get("local_date")) for row in rows}):
            day_rows = [row for row in rows if row.get("local_date") == day_text]
            daily.append({"date": day_text, **self._aggregate(day_rows, 288)})

        def rolling(days: int) -> dict[str, Any]:
            window_start = (today - timedelta(days=days - 1)).isoformat()
            selected = [row for row in rows if window_start <= str(row.get("local_date")) <= today.isoformat()]
            return self._aggregate(selected, days * 288)

        seven = rolling(7)
        thirty = rolling(30)
        if (
            thirty["calendar_coverage_pct"] < 80
            or thirty["hot_water_service_days_assessed"] < 24
        ):
            status = "collecting"
        elif (
            thirty["negative_fit_export_violations"] > 0
            or thirty["protected_soc_breaches"] > 0
            or (
                thirty["hot_water_service_days_assessed"] > 0
                and thirty["hot_water_service_days_completed"]
                < thirty["hot_water_service_days_assessed"]
            )
        ):
            status = "attention"
        else:
            status = "passing"
        return {
            "schema_version": self.SCHEMA_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "assessment_scope": "realized dispatch, source, crossover, EV and actuator evidence",
            "unassessed_criteria": [
                "net-benefit delta against a matched baseline",
            ],
            "daily": daily[-30:],
            "rolling_7d": seven,
            "rolling_30d": thirty,
        }

    def _prune_and_compress(self, today: date) -> None:
        cutoff = today - timedelta(days=max(1, self.settings.journal_retention_days) - 1)
        for path in self.outcome_dir.glob("????-??-??.jsonl"):
            try:
                day = datetime.strptime(path.stem, "%Y-%m-%d").date()
            except ValueError:
                continue
            if day < cutoff:
                path.unlink(missing_ok=True)
            elif day < today:
                compressed = path.with_suffix(".jsonl.gz")
                if compressed.exists():
                    continue
                temporary = compressed.with_name(f".{compressed.name}.tmp")
                with path.open("rb") as source, gzip.open(temporary, "wb") as destination:
                    shutil.copyfileobj(source, destination)
                temporary.replace(compressed)
                path.unlink()
        for path in self.outcome_dir.glob("????-??-??.jsonl.gz"):
            try:
                day = datetime.strptime(path.name.removesuffix(".jsonl.gz"), "%Y-%m-%d").date()
            except ValueError:
                continue
            if day < cutoff:
                path.unlink(missing_ok=True)

    def summary(self) -> dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self._summary))
