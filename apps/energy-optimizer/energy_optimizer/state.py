from __future__ import annotations

from collections import deque
from datetime import datetime
import json
from pathlib import Path
from typing import Any


class LearningState:
    """Small, inspectable rolling model persisted as JSON."""

    def __init__(self, path: Path):
        self.path = path
        self.data: dict[str, Any] = {
            "schema_version": 1,
            "load_slots": {},
            "solar_ratios": [1.008],
            "daily": {},
        }
        self.load()

    def load(self) -> None:
        try:
            raw = json.loads(self.path.read_text())
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return
        if raw.get("schema_version") == 1:
            self.data.update(raw)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.data, indent=2, sort_keys=True))
        temporary.replace(self.path)

    @staticmethod
    def _load_key(when: datetime) -> str:
        half_hour = when.hour * 2 + (1 if when.minute >= 30 else 0)
        return f"{when.weekday()}:{half_hour}"

    def update_load(self, when: datetime, base_load_kw: float) -> None:
        key = self._load_key(when)
        record = self.data["load_slots"].setdefault(key, {"mean": 1.67, "count": 0})
        count = min(96, int(record.get("count", 0)) + 1)
        alpha = 0.20 if count < 10 else 0.08
        record["mean"] = round((1 - alpha) * float(record.get("mean", 1.67)) + alpha * base_load_kw, 4)
        record["count"] = count

    def forecast_load(self, when: datetime) -> float:
        exact = self.data["load_slots"].get(self._load_key(when))
        if exact and int(exact.get("count", 0)) >= 3:
            return float(exact["mean"])
        generic_key = f"generic:{when.hour * 2 + (1 if when.minute >= 30 else 0)}"
        generic = self.data["load_slots"].get(generic_key)
        return float(generic.get("mean", 1.67)) if generic else 1.67

    def observe_solar_day(self, date_key: str, forecast_kwh: float, actual_kwh: float) -> None:
        if forecast_kwh <= 1 or actual_kwh <= 0:
            return
        daily = self.data["daily"].setdefault(date_key, {})
        daily["forecast_kwh"] = forecast_kwh
        daily["actual_kwh"] = max(float(daily.get("actual_kwh", 0.0)), actual_kwh)

    def finalize_previous_days(self, current_date_key: str) -> None:
        ratios = deque((float(item) for item in self.data.get("solar_ratios", [1.008])), maxlen=30)
        for date_key, record in self.data.get("daily", {}).items():
            if date_key >= current_date_key or record.get("finalized"):
                continue
            forecast = float(record.get("forecast_kwh", 0.0))
            actual = float(record.get("actual_kwh", 0.0))
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
