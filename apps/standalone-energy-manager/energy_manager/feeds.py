from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import logging
import math
from typing import Any

import aiohttp
import pandas as pd
import pvlib

from .config import Settings
from .models import PriceInterval

LOG = logging.getLogger(__name__)


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


class AmberFeed:
    def __init__(self, settings: Settings, session: aiohttp.ClientSession):
        self.settings = settings
        self.session = session
        self.site_id: str | None = None
        self.current: dict[str, PriceInterval] = {}
        self.forecast: dict[str, list[PriceInterval]] = {}
        self.last_error: str | None = None
        self.rate_limit_until: datetime | None = None

    async def _headers(self) -> dict[str, str]:
        token = self.settings.secret("amber_token")
        if not token:
            raise RuntimeError("amber_token secret is missing")
        return {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    async def discover_site(self) -> str:
        if self.site_id:
            return self.site_id
        async with self.session.get(f"{self.settings.amber_api_url}/sites", headers=await self._headers()) as response:
            response.raise_for_status()
            sites = await response.json()
        active = [site for site in sites if site.get("status") == "active"] or sites
        if not active:
            raise RuntimeError("Amber returned no sites")
        self.site_id = str(active[0]["id"])
        return self.site_id

    def _interval(self, raw: dict[str, Any]) -> PriceInterval | None:
        kind = raw.get("type", "")
        if kind not in {"CurrentInterval", "ForecastInterval", "ActualInterval"}:
            return None
        advanced = raw.get("advancedPrice") or {}
        cents = advanced.get("predicted", raw.get("perKwh"))
        if cents is None:
            return None
        start = parse_time(raw["startTime"])
        end = parse_time(raw["endTime"])
        # Amber occasionally reports a CurrentInterval one second after the
        # settlement boundary. The NEM interval still begins exactly five
        # minutes before its aligned end, so eliminate that one-second hole.
        duration = (end - start).total_seconds()
        if 295 <= duration <= 300 and int(end.timestamp()) % 300 == 0:
            start = end - timedelta(minutes=5)
        channel = str(raw.get("channelType", "unknown"))
        raw_cents = float(cents)
        # Public API feed-in values use the retailer billing sign: a payment
        # to the customer is negative. Internally and on the dashboard FIT is
        # customer-centric, matching Home Assistant: positive earns money and
        # negative means the customer pays to export.
        customer_cents = -raw_cents if channel in {"feedIn", "feed_in"} else raw_cents
        return PriceInterval(
            source="amber",
            channel=channel,
            start=start,
            end=end,
            price_per_kwh=customer_cents / 100,
            received_at=datetime.now(UTC),
            estimate=bool(raw.get("estimate", kind != "CurrentInterval")),
            raw_price=float(raw.get("perKwh", cents)),
            metadata={
                "type": kind,
                "nem_time": raw.get("nemTime"),
                "spot_per_kwh_cents": raw.get("spotPerKwh"),
                "descriptor": raw.get("descriptor"),
                "advanced_price": advanced,
                "raw_billing_price_cents": raw_cents,
            },
        )

    async def poll(self, next_intervals: int = 288) -> list[PriceInterval]:
        site = await self.discover_site()
        # Retain the last two settled intervals so AEMO's latest completed
        # interval can be compared to the matching Amber customer tariff.
        params = {"next": str(next_intervals), "previous": "2", "resolution": "5"}
        try:
            async with self.session.get(
                f"{self.settings.amber_api_url}/sites/{site}/prices/current",
                params=params,
                headers=await self._headers(),
            ) as response:
                if response.status == 429:
                    delay = int(response.headers.get("Retry-After", "60"))
                    self.rate_limit_until = datetime.now(UTC) + timedelta(seconds=delay)
                    raise RuntimeError(f"Amber rate limited for {delay}s")
                response.raise_for_status()
                payload = await response.json()
            intervals = [item for raw in payload if (item := self._interval(raw)) is not None]
            now = datetime.now(UTC)
            grouped: dict[str, list[PriceInterval]] = {}
            for item in intervals:
                grouped.setdefault(item.channel, []).append(item)
                if item.start <= now < item.end and item.metadata["type"] == "CurrentInterval":
                    self.current[item.channel] = item
            self.forecast = {key: sorted(values, key=lambda item: item.start) for key, values in grouped.items()}
            self.last_error = None
            return intervals
        except Exception as exc:
            self.last_error = str(exc)
            raise


class AemoFeed:
    def __init__(self, settings: Settings, session: aiohttp.ClientSession):
        self.settings = settings
        self.session = session
        self.current: PriceInterval | None = None
        self.forecast: list[PriceInterval] = []
        self.last_error: str | None = None

    async def poll(self) -> list[PriceInterval]:
        received = datetime.now(UTC)
        async with self.session.get(f"{self.settings.aemo_api_url}/NEM_DASHBOARD_CUMUL_PRICE") as response:
            response.raise_for_status()
            payload = await response.json()
        rows = payload.get("NEM_DASHBOARD_CUMUL_PRICE")
        if not isinstance(rows, list):
            raise ValueError("AEMO cumulative-price schema changed")
        qld = [row for row in rows if row.get("R") == "QLD1"]
        if not qld:
            raise ValueError("AEMO returned no QLD1 records")
        result: list[PriceInterval] = []
        for row in qld:
            actual = int(row.get("A", -1)) == 1
            end = parse_time(row["DT"] + "+10:00")
            duration = timedelta(minutes=5 if actual else 30)
            item = PriceInterval(
                source="aemo",
                channel="wholesale",
                start=end - duration,
                end=end,
                price_per_kwh=float(row["P"]) / 1000,
                received_at=received,
                estimate=not actual,
                raw_price=float(row["P"]),
                metadata={"cumulative_price": row.get("CP"), "period_type": "actual" if actual else "forecast"},
            )
            result.append(item)
        actuals = [item for item in result if not item.estimate]
        if actuals:
            self.current = max(actuals, key=lambda item: item.end)
        self.forecast = sorted((item for item in result if item.estimate), key=lambda item: item.start)
        self.last_error = None
        return result

    async def summary(self) -> dict[str, Any]:
        async with self.session.get(f"{self.settings.aemo_api_url}/ELEC_NEM_SUMMARY") as response:
            response.raise_for_status()
            payload = await response.json()
        rows = payload.get("ELEC_NEM_SUMMARY")
        if not isinstance(rows, list):
            raise ValueError("AEMO summary schema changed")
        row = next((item for item in rows if item.get("REGIONID") == "QLD1"), None)
        if row is None:
            raise ValueError("AEMO summary missing QLD1")
        required = {"SETTLEMENTDATE", "REGIONID", "PRICE", "PRICE_STATUS"}
        if not required.issubset(row):
            raise ValueError("AEMO summary missing required fields")
        return row


class SolarForecasts:
    def __init__(self, settings: Settings, session: aiohttp.ClientSession):
        self.settings = settings
        self.session = session
        self.providers: dict[str, dict[str, Any]] = {}
        self.combined: list[dict[str, Any]] = []

    @staticmethod
    def _forecast_solar_azimuth(north_clockwise: float) -> float:
        return ((north_clockwise - 180 + 180) % 360) - 180

    @staticmethod
    def _forecast_solar_power(payload: dict[str, Any]) -> dict[str, Any]:
        """Normalise Forecast.Solar's power-only response.

        The official ``/estimate/watts`` endpoint returns the timestamp-to-watt
        mapping directly in ``result``.  Keep the manager's existing internal
        roof contract (``{"watts": ...}``) so cached forecasts and planner
        consumers remain compatible.
        """

        if not isinstance(payload, dict):
            raise ValueError("Forecast.Solar response is not an object")
        message = payload.get("message")
        if isinstance(message, dict) and message.get("code") not in {None, 0}:
            raise ValueError(f"Forecast.Solar returned error code {message.get('code')}")
        raw_watts = payload.get("result")
        if not isinstance(raw_watts, dict) or not raw_watts:
            raise ValueError("Forecast.Solar watts response has no result mapping")

        watts: dict[str, float] = {}
        for raw_at, raw_value in raw_watts.items():
            if not isinstance(raw_at, str):
                raise ValueError("Forecast.Solar watts timestamp is not a string")
            try:
                parsed_at = datetime.fromisoformat(raw_at.replace("Z", "+00:00"))
                value = float(raw_value)
            except (TypeError, ValueError) as exc:
                raise ValueError("Forecast.Solar watts response contains an invalid point") from exc
            if not math.isfinite(value) or value < 0:
                raise ValueError("Forecast.Solar watts response contains invalid power")
            # ``time=utc`` promises offset-aware ISO 8601 timestamps.  Reject
            # a silent provider contract regression instead of guessing a zone.
            if parsed_at.tzinfo is None:
                raise ValueError("Forecast.Solar watts timestamp has no UTC offset")
            watts[raw_at] = value

        # Do not retain response-time/rate-limit metadata in the forecast
        # cache.  Those fields change on every identical fetch and would make
        # the semantic plan digest churn despite unchanged power values.
        return {"watts": watts}

    async def forecast_solar(self) -> dict[str, Any]:
        roofs = {
            "north": (self.settings.north_azimuth_deg, self.settings.north_capacity_kwp),
            "south": (self.settings.south_azimuth_deg, self.settings.south_capacity_kwp),
        }
        result: dict[str, Any] = {"issued_at": datetime.now(UTC).isoformat(), "roofs": {}}
        for name, (azimuth, capacity) in roofs.items():
            path = "/estimate/watts/{lat}/{lon}/{dec}/{az}/{kwp}".format(
                lat=self.settings.latitude,
                lon=self.settings.longitude,
                dec=self.settings.roof_tilt_deg,
                az=self._forecast_solar_azimuth(azimuth),
                kwp=capacity,
            )
            async with self.session.get(
                self.settings.forecast_solar_url + path,
                params={"time": "utc"},
                headers={"Accept": "application/json"},
            ) as response:
                if response.status == 429:
                    raise RuntimeError("Forecast.Solar rate limited")
                response.raise_for_status()
                payload = await response.json()
            result["roofs"][name] = self._forecast_solar_power(payload)
        # Commit only after both roof calls parse successfully.  A transient
        # provider/schema failure therefore leaves the last good cache intact.
        self.providers["forecast-solar"] = result
        return result

    async def solcast(self) -> dict[str, Any]:
        key = self.settings.secret("solcast_api_key")
        if not key:
            raise RuntimeError("solcast_api_key secret is missing")
        async with self.session.get(
            f"{self.settings.solcast_url}/rooftop_sites",
            params={"format": "json", "api_key": key},
        ) as response:
            response.raise_for_status()
            sites_payload = await response.json()
        site_ids = [str(site["resource_id"]) for site in sites_payload.get("sites", [])][:2]
        roofs: dict[str, Any] = {}
        for index, site_id in enumerate(site_ids):
            async with self.session.get(
                f"{self.settings.solcast_url}/rooftop_sites/{site_id}/forecasts",
                params={"format": "json", "hours": "48", "api_key": key},
            ) as response:
                response.raise_for_status()
                payload = await response.json()
            roofs["north" if index == 0 else "south"] = payload.get("forecasts", [])
        result = {"issued_at": datetime.now(UTC).isoformat(), "roofs": roofs}
        self.providers["solcast"] = result
        return result


class EcowittIrradiance:
    """Direct GW1100C LAN polling and roof plane-of-array conversion."""

    def __init__(self, settings: Settings, session: aiohttp.ClientSession):
        self.settings = settings
        self.session = session
        self.measured_at: datetime | None = None
        self.ghi_wm2: float | None = None
        self.poa_north_wm2: float | None = None
        self.poa_south_wm2: float | None = None
        self.expected_uncurtailed_kw: float | None = None
        self.last_error: str | None = None

    async def poll(self) -> dict[str, float]:
        if not self.settings.ecowitt_host:
            raise RuntimeError("Ecowitt host is not configured")
        async with self.session.get(f"http://{self.settings.ecowitt_host}/get_livedata_info") as response:
            response.raise_for_status()
            payload = await response.json(content_type=None)
        solar = next(
            (item for item in payload.get("common_list", []) if str(item.get("id")).lower() == "0x15"),
            None,
        )
        if solar is None:
            raise ValueError("Ecowitt response has no solar-radiation field 0x15")
        ghi = max(0.0, float(str(solar["val"]).split()[0]))
        now = datetime.now(UTC)
        times = pd.DatetimeIndex([now])
        location = pvlib.location.Location(self.settings.latitude, self.settings.longitude, tz="UTC")
        position = location.get_solarposition(times).iloc[0]
        zenith = float(position["apparent_zenith"])
        azimuth = float(position["azimuth"])
        if ghi <= 0 or zenith >= 90:
            dni = dhi = 0.0
        else:
            decomposition = pvlib.irradiance.erbs(pd.Series([ghi], index=times), pd.Series([zenith], index=times), times)
            dni = max(0.0, float(decomposition.iloc[0]["dni"]))
            dhi = max(0.0, float(decomposition.iloc[0]["dhi"]))

        def poa(surface_azimuth: float) -> float:
            result = pvlib.irradiance.get_total_irradiance(
                self.settings.roof_tilt_deg,
                surface_azimuth,
                zenith,
                azimuth,
                dni,
                ghi,
                dhi,
                model="isotropic",
            )
            return max(0.0, float(result["poa_global"]))

        poa_north = poa(self.settings.north_azimuth_deg)
        poa_south = poa(self.settings.south_azimuth_deg)
        # Initial DC-to-AC/system-performance factor. It is subsequently
        # calibrated only from intervals proven not to be curtailed.
        performance_ratio = 0.84
        expected = performance_ratio * (
            self.settings.north_capacity_kwp * poa_north / 1000
            + self.settings.south_capacity_kwp * poa_south / 1000
        )
        self.measured_at = now
        self.ghi_wm2 = ghi
        self.poa_north_wm2 = poa_north
        self.poa_south_wm2 = poa_south
        self.expected_uncurtailed_kw = max(0.0, expected)
        self.last_error = None
        return {
            "ghi_wm2": ghi,
            "poa_north_wm2": poa_north,
            "poa_south_wm2": poa_south,
            "expected_uncurtailed_kw": self.expected_uncurtailed_kw,
        }


def _covering_amber(feed: AmberFeed, channel: str, now: datetime) -> PriceInterval | None:
    """Return the best tariff covering *now*, including a cached forecast.

    Amber can publish the replacement CurrentInterval shortly after the NEM
    boundary. The already-cached ForecastInterval is therefore authoritative
    for the boundary action until the current value arrives and supersedes it.
    """
    aliases = (channel, "feed_in") if channel == "feedIn" else (channel,)
    candidates: list[PriceInterval] = []
    for alias in aliases:
        current = feed.current.get(alias)
        if current and current.start <= now < current.end:
            candidates.append(current)
        candidates.extend(item for item in feed.forecast.get(alias, []) if item.start <= now < item.end)
    if not candidates:
        return None
    rank = {"CurrentInterval": 3, "ForecastInterval": 2, "ActualInterval": 1}
    return max(candidates, key=lambda item: (rank.get(str(item.metadata.get("type")), 0), item.received_at))


def amber_channels(feed: AmberFeed, now: datetime | None = None) -> tuple[PriceInterval | None, PriceInterval | None]:
    now = now or datetime.now(UTC)
    return _covering_amber(feed, "feedIn", now), _covering_amber(feed, "general", now)
