from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
import json
import math
from pathlib import Path
import sqlite3
from typing import Any
from zoneinfo import ZoneInfo


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=FULL;
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS commands (id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, semantic_hash TEXT NOT NULL, phase TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS plans (id INTEGER PRIMARY KEY AUTOINCREMENT, plan_id TEXT NOT NULL UNIQUE, generated_at TEXT NOT NULL, expires_at TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS leases (resource TEXT PRIMARY KEY, updated_at TEXT NOT NULL, expires_at TEXT, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS price_observations (id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL, channel TEXT NOT NULL, interval_start TEXT NOT NULL, interval_end TEXT NOT NULL, price REAL NOT NULL, received_at TEXT NOT NULL, published_at TEXT, estimate INTEGER NOT NULL, raw TEXT NOT NULL, UNIQUE(source, channel, interval_start, received_at));
CREATE TABLE IF NOT EXISTS five_minute_outcomes (interval_start TEXT PRIMARY KEY, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS daily_outcomes (local_date TEXT PRIMARY KEY, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS outbox (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, destination TEXT NOT NULL, topic TEXT NOT NULL, payload TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS hot_water_daily (local_date TEXT PRIMARY KEY, confirmed_seconds REAL NOT NULL DEFAULT 0, energy_kwh REAL NOT NULL DEFAULT 0, completed_at TEXT);
CREATE TABLE IF NOT EXISTS outages (epoch TEXT PRIMARY KEY, lost_at TEXT NOT NULL, restored_at TEXT, duration_seconds REAL, min_ups_charge_pct REAL, min_ups_runtime_seconds REAL, highest_stage TEXT NOT NULL, shutdown_signals TEXT NOT NULL DEFAULT '{}', recovery_result TEXT, payload TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS ups_daily (local_date TEXT PRIMARY KEY, rack_output_kwh REAL NOT NULL DEFAULT 0, office_output_kwh REAL NOT NULL DEFAULT 0, conversion_loss_kwh REAL NOT NULL DEFAULT 0, wall_input_kwh REAL NOT NULL DEFAULT 0, updated_at TEXT NOT NULL);
"""


_DAILY_MAX_FIELDS = {"max_abs_meter_balance_error_kw"}
_DAILY_CONFIDENCE_FIELDS = {"export_attribution_confidence_score"}
_DAILY_CUMULATIVE_SUFFIXES = (
    "_kwh",
    "_revenue",
    "_cost",
    "_benefit",
    "_aud",
    "_hours",
    "_seconds",
)


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _duration_weighted(
    previous: Any,
    previous_hours: float,
    current: float,
    current_hours: float,
) -> float:
    previous_value = _finite_number(previous)
    total_hours = previous_hours + current_hours
    if previous_value is not None and previous_hours > 0 and current_hours > 0:
        return (previous_value * previous_hours + current * current_hours) / total_hours
    if current_hours > 0 or previous_value is None:
        return current
    return previous_value


def _confidence_label(score: float) -> str:
    return "high" if score >= 0.9 else "medium" if score >= 0.6 else "low"


def _roll_up_daily_interval(daily: dict[str, Any], interval: dict[str, Any]) -> dict[str, Any]:
    """Apply one completed interval using unit-aware aggregation semantics."""

    previous_hours = max(0.0, _finite_number(daily.get("duration_hours")) or 0.0)
    interval_hours = max(0.0, _finite_number(interval.get("duration_hours")) or 0.0)
    daily["intervals"] = int(daily.get("intervals", 0)) + 1

    interval_start = interval.get("interval_start")
    if interval_start is not None:
        start = str(interval_start)
        daily["first_interval_start"] = min(str(daily.get("first_interval_start", start)), start)
        daily["last_interval_start"] = max(str(daily.get("last_interval_start", start)), start)

    confidence_seen = False
    for key, value in interval.items():
        if key in {"interval_start", "intervals"}:
            continue

        number = _finite_number(value)
        if number is None:
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                # Never persist NaN or infinity as metadata or confidence.
                continue
            # Descriptive metadata follows the most recently completed interval;
            # a missing value cannot erase previously useful context.
            if value is not None and key != "export_attribution_confidence_label":
                daily[key] = value
            continue

        if key.startswith("average_"):
            daily[key] = _duration_weighted(
                daily.get(key), previous_hours, number, interval_hours
            )
        elif key in _DAILY_CONFIDENCE_FIELDS:
            confidence_seen = True
            score = min(1.0, max(0.0, number))
            daily[key] = min(
                1.0,
                max(
                    0.0,
                    _duration_weighted(daily.get(key), previous_hours, score, interval_hours),
                ),
            )
        elif key in _DAILY_MAX_FIELDS:
            previous = abs(_finite_number(daily.get(key)) or 0.0)
            daily[key] = max(previous, abs(number))
        elif key == "duration_hours" or key.endswith(_DAILY_CUMULATIVE_SUFFIXES):
            daily[key] = (_finite_number(daily.get(key)) or 0.0) + number
        else:
            # Numeric metadata such as schema versions or completion flags is
            # state, not energy. Preserve its latest observed value.
            daily[key] = value

    confidence = _finite_number(daily.get("export_attribution_confidence_score"))
    if confidence_seen or confidence is not None:
        confidence = min(1.0, max(0.0, confidence or 0.0))
        daily["export_attribution_confidence_score"] = confidence
        daily["export_attribution_confidence_label"] = _confidence_label(confidence)
    return daily


class Storage:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = asyncio.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        async with self._lock:
            self._db.execute(sql, params)
            self._db.commit()

    async def event(self, kind: str, payload: dict[str, Any]) -> None:
        await self.execute(
            "INSERT INTO events(at,kind,payload) VALUES(?,?,?)",
            (datetime.now(UTC).isoformat(), kind, json.dumps(payload, separators=(",", ":"), default=str)),
        )

    async def command(self, semantic_hash: str, phase: str, payload: dict[str, Any]) -> None:
        await self.execute(
            "INSERT INTO commands(at,semantic_hash,phase,payload) VALUES(?,?,?,?)",
            (datetime.now(UTC).isoformat(), semantic_hash, phase, json.dumps(payload, separators=(",", ":"), default=str)),
        )

    async def plan(
        self,
        plan_id: str,
        generated_at: str,
        expires_at: str,
        payload: dict[str, Any],
        retain: int = 48,
    ) -> None:
        """Store a plan revision and prune old large payloads atomically."""

        async with self._lock:
            try:
                self._db.execute("BEGIN IMMEDIATE")
                self._db.execute(
                    "INSERT OR REPLACE INTO plans(plan_id,generated_at,expires_at,payload) VALUES(?,?,?,?)",
                    (plan_id, generated_at, expires_at, json.dumps(payload, separators=(",", ":"), default=str)),
                )
                self._db.execute(
                    "DELETE FROM plans WHERE id NOT IN (SELECT id FROM plans ORDER BY generated_at DESC, id DESC LIMIT ?)",
                    (max(1, int(retain)),),
                )
                self._db.commit()
            except Exception:
                self._db.rollback()
                raise

    async def plan_count(self) -> int:
        async with self._lock:
            row = self._db.execute("SELECT COUNT(*) AS count FROM plans").fetchone()
        return int(row["count"])

    async def latest_plan(self) -> dict[str, Any] | None:
        async with self._lock:
            row = self._db.execute("SELECT payload FROM plans ORDER BY generated_at DESC LIMIT 1").fetchone()
        return json.loads(row["payload"]) if row else None

    async def lease(self, resource: str, expires_at: datetime | None, payload: dict[str, Any]) -> None:
        await self.execute(
            "INSERT INTO leases(resource,updated_at,expires_at,payload) VALUES(?,?,?,?) ON CONFLICT(resource) DO UPDATE SET updated_at=excluded.updated_at, expires_at=excluded.expires_at, payload=excluded.payload",
            (resource, datetime.now(UTC).isoformat(), expires_at.isoformat() if expires_at else None, json.dumps(payload, separators=(",", ":"), default=str)),
        )

    async def clear_leases(self, *resources: str) -> None:
        if resources:
            placeholders = ",".join("?" for _ in resources)
            await self.execute(f"DELETE FROM leases WHERE resource IN ({placeholders})", tuple(resources))
        else:
            await self.execute("DELETE FROM leases")

    async def record_price(self, payload: tuple[Any, ...]) -> bool:
        """Store the first receipt of an interval/price revision only."""
        source, channel, interval_start, interval_end, price, received_at, published_at, estimate, raw = payload
        async with self._lock:
            exists = self._db.execute(
                "SELECT 1 FROM price_observations WHERE source=? AND channel=? AND interval_start=? AND price=? AND estimate=? LIMIT 1",
                (source, channel, interval_start, price, estimate),
            ).fetchone()
            if exists:
                return False
            self._db.execute(
                "INSERT INTO price_observations(source,channel,interval_start,interval_end,price,received_at,published_at,estimate,raw) VALUES(?,?,?,?,?,?,?,?,?)",
                (source, channel, interval_start, interval_end, price, received_at, published_at, estimate, raw),
            )
            self._db.commit()
        return True

    async def add_daily_outcome(self, local_date: date, interval: dict[str, Any]) -> dict[str, Any]:
        async with self._lock:
            row = self._db.execute("SELECT payload FROM daily_outcomes WHERE local_date=?", (local_date.isoformat(),)).fetchone()
            daily = json.loads(row["payload"]) if row else {"local_date": local_date.isoformat(), "intervals": 0}
            _roll_up_daily_interval(daily, interval)
            self._db.execute(
                "INSERT INTO daily_outcomes(local_date,payload) VALUES(?,?) ON CONFLICT(local_date) DO UPDATE SET payload=excluded.payload",
                (local_date.isoformat(), json.dumps(daily, separators=(",", ":"))),
            )
            self._db.commit()
        return daily

    async def merge_daily_outcome(self, local_date: date, values: dict[str, Any]) -> dict[str, Any]:
        """Merge non-interval outcome metadata without changing interval count."""
        async with self._lock:
            row = self._db.execute("SELECT payload FROM daily_outcomes WHERE local_date=?", (local_date.isoformat(),)).fetchone()
            daily = json.loads(row["payload"]) if row else {"local_date": local_date.isoformat(), "intervals": 0}
            daily.update(values)
            self._db.execute(
                "INSERT INTO daily_outcomes(local_date,payload) VALUES(?,?) ON CONFLICT(local_date) DO UPDATE SET payload=excluded.payload",
                (local_date.isoformat(), json.dumps(daily, separators=(",", ":"), default=str)),
            )
            self._db.commit()
        return daily

    async def rebuild_daily_outcome(self, local_date: date, timezone: str) -> dict[str, Any]:
        """Rebuild one local day's roll-up from authoritative interval rows."""

        zone = ZoneInfo(timezone)
        start = datetime.combine(local_date, datetime.min.time(), tzinfo=zone).astimezone(UTC)
        end = (datetime.combine(local_date, datetime.min.time(), tzinfo=zone) + timedelta(days=1)).astimezone(UTC)
        async with self._lock:
            rows = self._db.execute(
                "SELECT payload FROM five_minute_outcomes WHERE interval_start>=? AND interval_start<? ORDER BY interval_start",
                (start.isoformat(), end.isoformat()),
            ).fetchall()
            if not rows:
                raise ValueError(f"no five-minute outcomes available for {local_date.isoformat()}")
            daily: dict[str, Any] = {"local_date": local_date.isoformat(), "intervals": 0}
            for row in rows:
                _roll_up_daily_interval(daily, json.loads(row["payload"]))
            self._db.execute(
                "INSERT INTO daily_outcomes(local_date,payload) VALUES(?,?) ON CONFLICT(local_date) DO UPDATE SET payload=excluded.payload",
                (local_date.isoformat(), json.dumps(daily, separators=(",", ":"), default=str)),
            )
            self._db.commit()
        return daily

    async def recent_outcomes(self, limit: int = 288) -> list[dict[str, Any]]:
        async with self._lock:
            rows = self._db.execute(
                "SELECT payload FROM five_minute_outcomes ORDER BY interval_start DESC LIMIT ?", (limit,)
            ).fetchall()
        return [json.loads(row["payload"]) for row in reversed(rows)]

    async def daily_series(self, limit: int = 30) -> list[dict[str, Any]]:
        async with self._lock:
            rows = self._db.execute(
                "SELECT payload FROM daily_outcomes ORDER BY local_date DESC LIMIT ?", (limit,)
            ).fetchall()
        return [json.loads(row["payload"]) for row in reversed(rows)]

    async def setting(self, key: str, default: Any) -> Any:
        async with self._lock:
            row = self._db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return default if row is None else json.loads(row["value"])

    async def set_setting(self, key: str, value: Any) -> None:
        await self.execute(
            "INSERT INTO settings(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, json.dumps(value), datetime.now(UTC).isoformat()),
        )

    async def set_settings(self, values: dict[str, Any]) -> None:
        """Persist one logical settings revision atomically."""
        updated_at = datetime.now(UTC).isoformat()
        async with self._lock:
            try:
                self._db.execute("BEGIN IMMEDIATE")
                self._db.executemany(
                    "INSERT INTO settings(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                    [(key, json.dumps(value), updated_at) for key, value in values.items()],
                )
                self._db.commit()
            except Exception:
                self._db.rollback()
                raise

    async def add_hot_water_seconds(self, local_date: date, seconds: float) -> None:
        energy = 3.7 * seconds / 3600
        await self.execute(
            "INSERT INTO hot_water_daily(local_date,confirmed_seconds,energy_kwh) VALUES(?,?,?) ON CONFLICT(local_date) DO UPDATE SET confirmed_seconds=confirmed_seconds+excluded.confirmed_seconds, energy_kwh=energy_kwh+excluded.energy_kwh",
            (local_date.isoformat(), seconds, energy),
        )

    async def hot_water_today(self, local_date: date) -> dict[str, Any]:
        async with self._lock:
            row = self._db.execute("SELECT * FROM hot_water_daily WHERE local_date=?", (local_date.isoformat(),)).fetchone()
        return dict(row) if row else {"local_date": local_date.isoformat(), "confirmed_seconds": 0.0, "energy_kwh": 0.0, "completed_at": None}

    async def recent_events(self, limit: int = 100) -> list[dict[str, Any]]:
        async with self._lock:
            rows = self._db.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [{**dict(row), "payload": json.loads(row["payload"])} for row in rows]

    async def start_outage(self, epoch: str, lost_at: datetime, payload: dict[str, Any]) -> None:
        await self.execute(
            "INSERT OR IGNORE INTO outages(epoch,lost_at,highest_stage,payload) VALUES(?,?,?,?)",
            (epoch, lost_at.isoformat(), "grid_outage_monitoring", json.dumps(payload, separators=(",", ":"), default=str)),
        )

    async def update_outage(self, epoch: str, *, stage: str, charge_pct: float | None, runtime_seconds: float | None, payload: dict[str, Any]) -> None:
        async with self._lock:
            row = self._db.execute("SELECT min_ups_charge_pct,min_ups_runtime_seconds FROM outages WHERE epoch=?", (epoch,)).fetchone()
            if row is None:
                return
            charge = charge_pct if row["min_ups_charge_pct"] is None else min(float(row["min_ups_charge_pct"]), charge_pct) if charge_pct is not None else row["min_ups_charge_pct"]
            runtime = runtime_seconds if row["min_ups_runtime_seconds"] is None else min(float(row["min_ups_runtime_seconds"]), runtime_seconds) if runtime_seconds is not None else row["min_ups_runtime_seconds"]
            self._db.execute(
                "UPDATE outages SET min_ups_charge_pct=?,min_ups_runtime_seconds=?,highest_stage=?,payload=? WHERE epoch=?",
                (charge, runtime, stage, json.dumps(payload, separators=(",", ":"), default=str), epoch),
            )
            self._db.commit()

    async def finish_outage(self, epoch: str, restored_at: datetime, recovery_result: str, payload: dict[str, Any]) -> None:
        await self.execute(
            "UPDATE outages SET restored_at=?,duration_seconds=(julianday(?) - julianday(lost_at))*86400,recovery_result=?,payload=? WHERE epoch=?",
            (restored_at.isoformat(), restored_at.isoformat(), recovery_result, json.dumps(payload, separators=(",", ":"), default=str), epoch),
        )

    async def recent_outages(self, limit: int = 100) -> list[dict[str, Any]]:
        async with self._lock:
            rows = self._db.execute("SELECT * FROM outages ORDER BY lost_at DESC LIMIT ?", (limit,)).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["shutdown_signals"] = json.loads(item["shutdown_signals"] or "{}")
            item["payload"] = json.loads(item["payload"] or "{}")
            result.append(item)
        return result

    async def ups_daily(self, local_date: date) -> dict[str, Any]:
        async with self._lock:
            row = self._db.execute("SELECT * FROM ups_daily WHERE local_date=?", (local_date.isoformat(),)).fetchone()
        return dict(row) if row else {
            "local_date": local_date.isoformat(), "rack_output_kwh": 0.0,
            "office_output_kwh": 0.0, "conversion_loss_kwh": 0.0,
            "wall_input_kwh": 0.0, "updated_at": None,
        }

    async def set_ups_daily(self, values: dict[str, Any]) -> None:
        await self.execute(
            "INSERT INTO ups_daily(local_date,rack_output_kwh,office_output_kwh,conversion_loss_kwh,wall_input_kwh,updated_at) VALUES(?,?,?,?,?,?) ON CONFLICT(local_date) DO UPDATE SET rack_output_kwh=excluded.rack_output_kwh,office_output_kwh=excluded.office_output_kwh,conversion_loss_kwh=excluded.conversion_loss_kwh,wall_input_kwh=excluded.wall_input_kwh,updated_at=excluded.updated_at",
            (values["local_date"], values["rack_output_kwh"], values["office_output_kwh"], values["conversion_loss_kwh"], values["wall_input_kwh"], values["updated_at"]),
        )

    async def enqueue_outbox(self, destination: str, topic: str, payload: str) -> None:
        await self.execute(
            "INSERT INTO outbox(created_at,destination,topic,payload) VALUES(?,?,?,?)",
            (datetime.now(UTC).isoformat(), destination, topic, payload),
        )
        # Bound outage growth to roughly five days of two-second power rows.
        await self.execute(
            "DELETE FROM outbox WHERE id IN (SELECT id FROM outbox ORDER BY id DESC LIMIT -1 OFFSET 220000)"
        )

    async def pending_outbox(self, destination: str, limit: int = 250) -> list[dict[str, Any]]:
        async with self._lock:
            rows = self._db.execute(
                "SELECT * FROM outbox WHERE destination=? ORDER BY id LIMIT ?",
                (destination, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    async def ack_outbox(self, ids: list[int]) -> None:
        if not ids:
            return
        placeholders = ",".join("?" for _ in ids)
        await self.execute(f"DELETE FROM outbox WHERE id IN ({placeholders})", tuple(ids))

    async def fail_outbox(self, ids: list[int]) -> None:
        if not ids:
            return
        placeholders = ",".join("?" for _ in ids)
        await self.execute(f"UPDATE outbox SET attempts=attempts+1 WHERE id IN ({placeholders})", tuple(ids))

    async def outbox_count(self, destination: str) -> int:
        async with self._lock:
            row = self._db.execute("SELECT COUNT(*) AS count FROM outbox WHERE destination=?", (destination,)).fetchone()
        return int(row["count"])
