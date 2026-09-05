from __future__ import annotations

from collections import deque
from datetime import datetime
import json
import math
from pathlib import Path
from typing import Any


class LearningState:
    """Small, inspectable rolling model persisted as JSON."""

    SCHEMA_VERSION = 3

    def __init__(self, path: Path):
        self.path = path
        self.data: dict[str, Any] = self._empty_state()
        self.load()

    @classmethod
    def _empty_state(cls) -> dict[str, Any]:
        return {
            "schema_version": cls.SCHEMA_VERSION,
            "load_slots": {},
            "solar_ratios": [1.008],
            "daily": {},
            "solar_power_observation": {},
            "roof_solar_bins": {"north": {}, "south": {}},
            "last_roof_observation_bucket": {},
            "last_load_observation_bucket": None,
            "migration": {},
        }

    def load(self) -> None:
        try:
            raw = json.loads(self.path.read_text())
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return
        version = raw.get("schema_version")
        if version == self.SCHEMA_VERSION:
            self.data = self._validated_v3(raw)
            return
        if version == 2:
            self.data = self._validated_v3(raw)
            self.data["migration"] = {
                **self.data.get("migration", {}),
                "from_schema_version": 2,
                "roof_calibration_started": True,
            }
            return
        if version == 1:
            self.data = self._migrate_v1(raw)

    def _validated_v3(self, raw: dict[str, Any]) -> dict[str, Any]:
        validated = self._empty_state()
        load_slots = raw.get("load_slots")
        if isinstance(load_slots, dict):
            for key, value in load_slots.items():
                if not isinstance(value, dict):
                    continue
                try:
                    mean = float(value.get("mean", 1.67))
                    count = int(value.get("count", 0))
                except (TypeError, ValueError):
                    continue
                if not 0 <= mean <= 100:
                    continue
                validated["load_slots"][str(key)] = {
                    "mean": round(mean, 4),
                    "count": min(96, max(0, count)),
                }
        ratios = raw.get("solar_ratios")
        if isinstance(ratios, list):
            clean_ratios: list[float] = []
            for value in ratios[-30:]:
                try:
                    ratio = float(value)
                except (TypeError, ValueError):
                    continue
                if 0.5 <= ratio <= 1.4:
                    clean_ratios.append(ratio)
            if clean_ratios:
                validated["solar_ratios"] = clean_ratios
        daily = raw.get("daily")
        if isinstance(daily, dict):
            for key, value in daily.items():
                if not isinstance(value, dict):
                    continue
                try:
                    datetime.fromisoformat(str(key))
                except ValueError:
                    continue
                record: dict[str, Any] = {}
                for field in ("forecast_kwh", "actual_kwh", "curtailed_kwh"):
                    if field not in value:
                        continue
                    try:
                        reading = float(value[field])
                    except (TypeError, ValueError):
                        continue
                    if math.isfinite(reading) and 0 <= reading <= 500:
                        record[field] = reading
                observed_at = value.get("actual_observed_at")
                try:
                    parsed_observation = (
                        datetime.fromisoformat(str(observed_at))
                        if observed_at
                        else None
                    )
                except ValueError:
                    parsed_observation = None
                if parsed_observation is not None and parsed_observation.tzinfo is not None:
                    record["actual_observed_at"] = parsed_observation.isoformat()
                if value.get("finalized") is True:
                    record["finalized"] = True
                if record:
                    validated["daily"][str(key)] = record
        observation = raw.get("solar_power_observation")
        if isinstance(observation, dict):
            try:
                observation_at = datetime.fromisoformat(str(observation.get("at")))
                curtailed_kw = float(observation.get("curtailed_kw", 0.0))
            except (TypeError, ValueError):
                observation_at = None
                curtailed_kw = 0.0
            if (
                observation_at is not None
                and observation_at.tzinfo is not None
                and math.isfinite(curtailed_kw)
                and 0 <= curtailed_kw <= 100
            ):
                validated["solar_power_observation"] = {
                    "at": observation_at.isoformat(),
                    "curtailed_kw": curtailed_kw,
                    "curtailed": bool(observation.get("curtailed")),
                }
        bucket = raw.get("last_load_observation_bucket")
        if isinstance(bucket, str):
            try:
                parsed_bucket = datetime.fromisoformat(bucket)
            except ValueError:
                parsed_bucket = None
            if parsed_bucket is not None and parsed_bucket.tzinfo is not None:
                validated["last_load_observation_bucket"] = parsed_bucket.isoformat()
        migration = raw.get("migration")
        if isinstance(migration, dict):
            validated["migration"] = migration
        roof_bins = raw.get("roof_solar_bins")
        if isinstance(roof_bins, dict):
            for roof in ("north", "south"):
                source = roof_bins.get(roof, {})
                if not isinstance(source, dict):
                    continue
                for key, values in source.items():
                    if not isinstance(values, list):
                        continue
                    clean = []
                    for value in values[-60:]:
                        try:
                            ratio = float(value)
                        except (TypeError, ValueError):
                            continue
                        if math.isfinite(ratio) and 0.3 <= ratio <= 1.7:
                            clean.append(round(ratio, 4))
                    if clean:
                        validated["roof_solar_bins"][roof][str(key)] = clean
        roof_buckets = raw.get("last_roof_observation_bucket")
        if isinstance(roof_buckets, dict):
            for roof in ("north", "south"):
                value = roof_buckets.get(roof)
                try:
                    parsed = datetime.fromisoformat(str(value)) if value else None
                except ValueError:
                    parsed = None
                if parsed is not None and parsed.tzinfo is not None:
                    validated["last_roof_observation_bucket"][roof] = parsed.isoformat()
        return validated

    def _migrate_v1(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Migrate without carrying known duplicated counter observations.

        Version 1 sampled the same daily-energy counter and load value on every
        replan.  Retaining its daily records could finalize yesterday's value as
        today's production, while retaining large load counts would preserve
        false confidence.  Existing load means remain useful, so they are kept
        with their counts capped; daily/calibration observations are reset.
        """
        migrated = self._empty_state()
        load_slots = raw.get("load_slots", {})
        if isinstance(load_slots, dict):
            for key, value in load_slots.items():
                if not isinstance(value, dict):
                    continue
                try:
                    mean = max(0.0, float(value.get("mean", 1.67)))
                    count = min(3, max(0, int(value.get("count", 0))))
                except (TypeError, ValueError):
                    continue
                migrated["load_slots"][str(key)] = {
                    "mean": round(mean, 4),
                    "count": count,
                }
        migrated["migration"] = {
            "from_schema_version": 1,
            "daily_observations_reset": True,
            "solar_ratios_reset": True,
            "load_counts_capped_at": 3,
        }
        return migrated

    def reset(self) -> None:
        """Reset learned observations while retaining an explicit audit marker."""
        self.data = self._empty_state()
        self.data["migration"] = {"manual_reset_at": datetime.now().astimezone().isoformat()}
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.data, indent=2, sort_keys=True))
        temporary.replace(self.path)

    @staticmethod
    def _load_key(when: datetime) -> str:
        half_hour = when.hour * 2 + (1 if when.minute >= 30 else 0)
        return f"{when.weekday()}:{half_hour}"

    @staticmethod
    def _observation_bucket(when: datetime) -> str:
        minute = when.minute - when.minute % 5
        return when.replace(minute=minute, second=0, microsecond=0).isoformat()

    def update_load(self, when: datetime, base_load_kw: float) -> bool:
        if (
            when.tzinfo is None
            or not math.isfinite(base_load_kw)
            or not 0 <= base_load_kw <= 100
        ):
            return False
        bucket = self._observation_bucket(when)
        previous_bucket = self.data.get("last_load_observation_bucket")
        if previous_bucket:
            try:
                previous_at = datetime.fromisoformat(str(previous_bucket))
                bucket_at = datetime.fromisoformat(bucket)
            except ValueError:
                previous_at = None
                bucket_at = None
            if previous_at is not None and bucket_at is not None and bucket_at <= previous_at:
                return False
        key = self._load_key(when)
        record = self.data["load_slots"].setdefault(key, {"mean": 1.67, "count": 0})
        count = min(96, int(record.get("count", 0)) + 1)
        alpha = 0.20 if count < 10 else 0.08
        record["mean"] = round((1 - alpha) * float(record.get("mean", 1.67)) + alpha * base_load_kw, 4)
        record["count"] = count
        self.data["last_load_observation_bucket"] = bucket
        return True

    def forecast_load(self, when: datetime) -> float:
        exact = self.data["load_slots"].get(self._load_key(when))
        if exact and int(exact.get("count", 0)) >= 3:
            return float(exact["mean"])
        generic_key = f"generic:{when.hour * 2 + (1 if when.minute >= 30 else 0)}"
        generic = self.data["load_slots"].get(generic_key)
        return float(generic.get("mean", 1.67)) if generic else 1.67

    def observe_solar_day(
        self,
        date_key: str,
        forecast_kwh: float,
        actual_kwh: float,
        *,
        observed_at: datetime | None = None,
    ) -> bool:
        if (
            not math.isfinite(forecast_kwh)
            or not math.isfinite(actual_kwh)
            or forecast_kwh <= 1
            or actual_kwh <= 0
        ):
            return False
        if observed_at is not None and observed_at.date().isoformat() != date_key:
            return False
        daily = self.data["daily"].setdefault(date_key, {})
        if observed_at is not None:
            previous = daily.get("actual_observed_at")
            try:
                previous_at = datetime.fromisoformat(str(previous)) if previous else None
            except (TypeError, ValueError):
                previous_at = None
            if previous_at is not None:
                if previous_at.tzinfo is None and observed_at.tzinfo is not None:
                    previous_at = previous_at.replace(tzinfo=observed_at.tzinfo)
                elif previous_at.tzinfo is not None and observed_at.tzinfo is None:
                    observed_at = observed_at.replace(tzinfo=previous_at.tzinfo)
                if observed_at <= previous_at:
                    return False
        daily["forecast_kwh"] = forecast_kwh
        daily["actual_kwh"] = max(float(daily.get("actual_kwh", 0.0)), actual_kwh)
        if observed_at is not None:
            daily["actual_observed_at"] = observed_at.isoformat()
        return True

    def observe_solar_power(
        self,
        when: datetime,
        *,
        actual_kw: float,
        potential_kw: float,
        curtailed: bool,
    ) -> None:
        """Integrate a curtailment-independent daily available-energy trace."""
        if (
            when.tzinfo is None
            or not math.isfinite(actual_kw)
            or not math.isfinite(potential_kw)
            or actual_kw < 0
            or potential_kw < 0
        ):
            return
        date_key = when.date().isoformat()
        daily = self.data["daily"].setdefault(date_key, {})
        previous = self.data.get("solar_power_observation", {})
        try:
            previous_at = datetime.fromisoformat(str(previous.get("at")))
        except (TypeError, ValueError):
            previous_at = None
        if previous_at and previous_at.tzinfo and when <= previous_at:
            return
        if previous_at and previous_at.tzinfo and previous_at.date() == when.date():
            duration_h = (when - previous_at).total_seconds() / 3600
            if 0 < duration_h <= 10 / 60:
                previous_curtailed = max(0.0, float(previous.get("curtailed_kw", 0.0)))
                curtailed_kw = max(0.0, potential_kw - actual_kw) if curtailed else 0.0
                daily["curtailed_kwh"] = round(
                    float(daily.get("curtailed_kwh", 0.0))
                    + (previous_curtailed + curtailed_kw) * 0.5 * duration_h,
                    5,
                )
        curtailed_kw = max(0.0, potential_kw - actual_kw) if curtailed else 0.0
        self.data["solar_power_observation"] = {
            "at": when.isoformat(),
            "curtailed_kw": round(curtailed_kw, 4),
            "curtailed": bool(curtailed),
        }

    @staticmethod
    def _roof_bin(when: datetime) -> str:
        return str(when.hour * 2 + (1 if when.minute >= 30 else 0))

    def observe_roof_power(
        self,
        when: datetime,
        *,
        roof: str,
        expected_kw: float,
        actual_kw: float,
        uncurtailed: bool,
    ) -> bool:
        """Learn per-roof, half-hour bias only from uncurtailed production."""
        if (
            roof not in {"north", "south"}
            or when.tzinfo is None
            or not uncurtailed
            or not math.isfinite(expected_kw)
            or not math.isfinite(actual_kw)
            or expected_kw < 0.25
            or actual_kw < 0
        ):
            return False
        bucket = self._observation_bucket(when)
        previous = self.data["last_roof_observation_bucket"].get(roof)
        try:
            if previous and datetime.fromisoformat(previous) >= datetime.fromisoformat(bucket):
                return False
        except ValueError:
            pass
        ratio = min(1.7, max(0.3, actual_kw / expected_kw))
        values = self.data["roof_solar_bins"][roof].setdefault(
            self._roof_bin(when),
            [],
        )
        values.append(round(ratio, 4))
        del values[:-60]
        self.data["last_roof_observation_bucket"][roof] = bucket
        return True

    def roof_correction(self, when: datetime, roof: str) -> float:
        values = self.data.get("roof_solar_bins", {}).get(roof, {}).get(
            self._roof_bin(when),
            [],
        )
        if len(values) < 3:
            return 1.0
        ordered = sorted(float(value) for value in values)
        middle = len(ordered) // 2
        return (
            ordered[middle]
            if len(ordered) % 2
            else (ordered[middle - 1] + ordered[middle]) / 2
        )

    @property
    def roof_calibration_report(self) -> dict[str, Any]:
        report: dict[str, Any] = {}
        for roof in ("north", "south"):
            values = [
                float(value)
                for samples in self.data.get("roof_solar_bins", {}).get(roof, {}).values()
                for value in samples
            ]
            ordered = sorted(values)
            if not ordered:
                report[roof] = {"observations": 0, "bias": None, "low": None, "high": None}
                continue
            quantile = lambda q: ordered[min(len(ordered) - 1, round((len(ordered) - 1) * q))]
            report[roof] = {
                "observations": len(ordered),
                "bias": round(quantile(0.5), 3),
                "low": round(quantile(0.1), 3),
                "high": round(quantile(0.9), 3),
                "time_bins": sum(
                    len(samples) >= 3
                    for samples in self.data["roof_solar_bins"][roof].values()
                ),
            }
        return report

    def finalize_previous_days(self, current_date_key: str) -> None:
        ratios = deque(
            (
                float(item)
                for item in self.data.get("solar_ratios", [1.008])
                if isinstance(item, (int, float)) and math.isfinite(float(item))
            ),
            maxlen=30,
        )
        for date_key, record in self.data.get("daily", {}).items():
            if date_key >= current_date_key or record.get("finalized"):
                continue
            try:
                forecast = float(record.get("forecast_kwh", 0.0))
                actual = (
                    float(record.get("actual_kwh", 0.0))
                    + float(record.get("curtailed_kwh", 0.0))
                )
            except (TypeError, ValueError):
                continue
            if forecast > 1 and actual > 0:
                ratios.append(min(1.4, max(0.5, actual / forecast)))
                record["finalized"] = True
        self.data["solar_ratios"] = list(ratios)
        keep = sorted(self.data.get("daily", {}))[-45:]
        self.data["daily"] = {key: self.data["daily"][key] for key in keep}

    @property
    def solar_calibration_ratio(self) -> float:
        ratios = sorted(float(item) for item in self.data.get("solar_ratios", [1.008]))
        if not ratios:
            return 1.008
        middle = len(ratios) // 2
        return ratios[middle] if len(ratios) % 2 else (ratios[middle - 1] + ratios[middle]) / 2

    @property
    def solar_confidence(self) -> float:
        ratios = self.data.get("solar_ratios", [])
        return min(0.95, 0.60 + 0.012 * len(ratios))
