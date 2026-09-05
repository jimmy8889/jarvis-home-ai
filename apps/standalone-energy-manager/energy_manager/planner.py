from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
import math
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from .config import Settings
from .economics import protected_surplus_export_economics, profitable_export_site_target_kw
from .ev import ev_requirement, opportunistic_fit_eligible
from .feeds import AmberFeed, SolarForecasts
from .flows import conserved_power_flow
from .models import DeviceState, PriceInterval, Telemetry
from .policy import protected_reserve_pct


INTERVAL_HOURS = 5 / 60


def floor_interval(at: datetime) -> datetime:
    return datetime.fromtimestamp(int(at.timestamp()) // 300 * 300, UTC)


def covering(intervals: Iterable[PriceInterval], at: datetime) -> PriceInterval | None:
    return next((item for item in intervals if item.start <= at < item.end), None)


def _parse_time(value: Any, timezone: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=ZoneInfo(timezone))
        return parsed.astimezone(UTC)
    except (TypeError, ValueError):
        return None


def provider_power(solar: SolarForecasts | None, at: datetime, timezone: str) -> dict[str, float]:
    roof: dict[str, dict[str, float]] = {
        "north": {"solcast_kw": 0.0, "forecast_solar_kw": 0.0},
        "south": {"solcast_kw": 0.0, "forecast_solar_kw": 0.0},
    }
    if solar:
        for name, intervals in solar.providers.get("solcast", {}).get("roofs", {}).items():
            for item in intervals:
                end = _parse_time(item.get("period_end"), timezone)
                if end and end - timedelta(minutes=30) <= at < end:
                    roof.setdefault(name, {})["solcast_kw"] = max(0.0, float(item.get("pv_estimate", 0)))
                    break
        for name, result in solar.providers.get("forecast-solar", {}).get("roofs", {}).items():
            watts = result.get("watts", {}) if isinstance(result, dict) else {}
            candidates = [
                (parsed, float(value) / 1000)
                for key, value in watts.items()
                if (parsed := _parse_time(key, timezone)) is not None
            ]
            if candidates:
                closest = min(candidates, key=lambda pair: abs((pair[0] - at).total_seconds()))
                if abs((closest[0] - at).total_seconds()) <= 3600:
                    roof.setdefault(name, {})["forecast_solar_kw"] = max(0.0, closest[1])

    def ensemble(values: dict[str, float]) -> float:
        solcast = values.get("solcast_kw", 0.0)
        forecast_solar = values.get("forecast_solar_kw", 0.0)
        return 0.75 * solcast + 0.25 * forecast_solar if solcast and forecast_solar else max(solcast, forecast_solar)

    north_kw = ensemble(roof["north"])
    south_kw = ensemble(roof["south"])
    solcast_kw = sum(values.get("solcast_kw", 0.0) for values in roof.values())
    forecast_solar_kw = sum(values.get("forecast_solar_kw", 0.0) for values in roof.values())
    expected = 0.75 * solcast_kw + 0.25 * forecast_solar_kw if solcast_kw and forecast_solar_kw else max(solcast_kw, forecast_solar_kw)
    return {
        "solcast_kw": solcast_kw,
        "forecast_solar_kw": forecast_solar_kw,
        "expected_kw": expected,
        "north_kw": north_kw,
        "south_kw": south_kw,
        "pv1_kw": north_kw,
        "pv2_kw": south_kw / 3.0,
        "pv3_kw": south_kw * 2.0 / 3.0,
    }


def default_house_load_kw(at: datetime, timezone: str) -> float:
    hour = at.astimezone(ZoneInfo(timezone)).hour
    if 0 <= hour < 5:
        return 1.35
    if 5 <= hour < 9:
        return 2.4
    if 16 <= hour < 22:
        return 2.8
    return 1.7


def _windows(points: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    windows: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for point in points:
        if point[key] and current is None:
            current = {
                "start": point["start"],
                "end": point["end"],
                "max_price_per_kwh": point.get("fit_per_kwh"),
                "min_price_per_kwh": point.get("fit_per_kwh"),
                "max_power_kw": point.get("site_export_target_kw", 0),
                "battery_export_kwh": 0.0,
                "solar_export_kwh": 0.0,
                "battery_export_revenue": 0.0,
                "battery_export_wear_cost": 0.0,
                "battery_export_retained_value": 0.0,
                "battery_export_net_benefit": 0.0,
                "solar_export_revenue": 0.0,
                "total_export_revenue": 0.0,
            }
        if point[key] and current is not None:
            current["end"] = point["end"]
            current["max_price_per_kwh"] = max(current["max_price_per_kwh"] or 0, point.get("fit_per_kwh") or 0)
            current["min_price_per_kwh"] = min(current["min_price_per_kwh"] if current["min_price_per_kwh"] is not None else float("inf"), point.get("fit_per_kwh") if point.get("fit_per_kwh") is not None else float("inf"))
            current["max_power_kw"] = max(current["max_power_kw"], point.get("site_export_target_kw", 0))
            for field in (
                "battery_export_kwh", "solar_export_kwh", "battery_export_revenue", "battery_export_wear_cost",
                "battery_export_retained_value", "battery_export_net_benefit",
                "solar_export_revenue", "total_export_revenue",
            ):
                current[field] += float(point.get(field, 0.0))
        elif current is not None:
            for field in tuple(current):
                if field not in {"start", "end", "min_price_per_kwh", "max_price_per_kwh", "max_power_kw"}:
                    current[field] = round(float(current[field]), 3)
            windows.append(current)
            current = None
    if current is not None:
        for field in tuple(current):
            if field not in {"start", "end", "min_price_per_kwh", "max_price_per_kwh", "max_power_kw"}:
                current[field] = round(float(current[field]), 3)
        windows.append(current)
    return windows


class RollingPlanner:
    def __init__(self, settings: Settings):
        self.settings = settings

    def build(
        self,
        now: datetime,
        telemetry: Telemetry,
        devices: DeviceState,
        amber: AmberFeed,
        solar: SolarForecasts | None,
        hot_water_runtime_hours: float,
        server_rack_kw: float = 0.0,
    ) -> dict[str, Any]:
        start = floor_interval(now)
        fit_intervals = amber.forecast.get("feedIn", [])
        import_intervals = amber.forecast.get("general", [])
        points: list[dict[str, Any]] = []
        for offset in range(36 * 12):
            at = start + timedelta(minutes=5 * offset)
            fit = covering(fit_intervals, at)
            general = covering(import_intervals, at)
            power = provider_power(solar, at, self.settings.timezone)
            house_kw = default_house_load_kw(at, self.settings.timezone)
            points.append({
                "start": at,
                "end": at + timedelta(minutes=5),
                "fit_per_kwh": fit.price_per_kwh if fit else None,
                "import_per_kwh": general.price_per_kwh if general else None,
                "pv_kw": power["expected_kw"],
                "load_kw": house_kw,
                "server_rack_kw": min(max(0.0, server_rack_kw), house_kw),
                "hot_water": False,
                "ev_kw": 0.0,
                "ev_source": "off",
                "export": False,
                "battery_target_kw": 0.0,
                "site_export_target_kw": 0.0,
                "battery_charge_deferred": False,
                "export_protected_soc_pct": self.settings.battery_floor_pct,
            })

        # Schedule each Brisbane-local service day represented by the horizon.
        # Today's confirmed runtime applies only to today; every future date
        # receives a fresh 3.05-hour service allocation.
        local_now = now.astimezone(ZoneInfo(self.settings.timezone))

        def opportunity(point: dict[str, Any]) -> tuple[float, datetime]:
            fit = point["fit_per_kwh"]
            shortfall = max(0.0, self.settings.hot_water_kw + 0.5 - (point["pv_kw"] - point["load_kw"]))
            # Once the element is running, keep the current block committed.
            # A small forecast/price revision must not make an already-started
            # service chase a later five-minute slot.
            continuation_bias = -1000.0 if devices.hot_water_on and point["start"] == start else 0.0
            return ((fit if fit is not None else 10.0) + shortfall * 10 + continuation_bias, point["start"])

        daily_hot_water: list[dict[str, Any]] = []
        local_dates = sorted({
            point["start"].astimezone(ZoneInfo(self.settings.timezone)).date()
            for point in points
        })
        for local_date in local_dates:
            local_deadline = datetime.combine(
                local_date,
                time(self.settings.hot_water_deadline_hour),
                tzinfo=local_now.tzinfo,
            )
            deadline_utc = local_deadline.astimezone(UTC)
            confirmed_hours = hot_water_runtime_hours if local_date == local_now.date() else 0.0
            remaining_hours = max(0.0, self.settings.hot_water_target_hours - confirmed_hours)
            # A missed current-day deadline cannot be repaired retrospectively.
            schedulable_hours = 0.0 if local_date == local_now.date() and local_now >= local_deadline else remaining_hours
            required_slots = max(0, math.ceil(schedulable_hours * 12 - 1e-9))
            candidates = [
                point for point in points
                # ``now`` normally arrives a few milliseconds/seconds after an
                # Amber boundary. Comparing the rounded point start with that
                # exact timestamp excluded the active interval and moved the
                # hot-water start forward at every replan. ``start`` is the
                # beginning of the active settlement interval.
                if point["start"] >= start
                and point["start"] < deadline_utc
                and point["start"].astimezone(ZoneInfo(self.settings.timezone)).date() == local_date
            ]
            fixed_timer_mode = self.settings.hot_water_fixed_timer or not self.settings.control_enabled
            if not self.settings.hot_water_enabled:
                selected = []
                required_slots = 0
            elif fixed_timer_mode:
                selected = [
                    point for point in candidates
                    if self.settings.hot_water_timer_start_hour
                    <= point["start"].astimezone(ZoneInfo(self.settings.timezone)).hour
                    < self.settings.hot_water_timer_end_hour
                ] if required_slots else []
                required_slots = len(selected)
            else:
                selected = sorted(
                    [
                        point for point in candidates
                        if point["pv_kw"] - point["load_kw"] >= self.settings.hot_water_kw + 0.5
                        or (devices.hot_water_on and point["start"] == start)
                    ],
                    key=opportunity,
                )[:required_slots]
            for point in selected:
                point["hot_water"] = True
            if self.settings.hot_water_enabled and not fixed_timer_mode and len(selected) < required_slots:
                fallback = [point for point in candidates if not point["hot_water"]]
                for point in fallback[-(required_slots - len(selected)):]:
                    point["hot_water"] = True
            scheduled = sorted(
                (point for point in candidates if point["hot_water"]),
                key=lambda point: point["start"],
            )
            daily_hot_water.append({
                "local_date": local_date.isoformat(),
                "deadline": deadline_utc,
                "confirmed_hours": round(confirmed_hours, 3),
                "remaining_hours": round(remaining_hours, 3),
                "required_blocks": required_slots,
                "scheduled_blocks": len(scheduled),
                "planned_start": scheduled[0]["start"] if scheduled else None,
                "planned_end": scheduled[-1]["end"] if scheduled else None,
                "complete": remaining_hours <= 1e-6,
                "missed": bool(local_date == local_now.date() and local_now >= local_deadline and remaining_hours > 0),
            })

        next_hot_water_day = next(
            (day for day in daily_hot_water if day["required_blocks"] > 0),
            daily_hot_water[0] if daily_hot_water else None,
        )

        effective_capacity = self.settings.battery_capacity_kwh * float(telemetry.soh_pct or 100) / 100
        energy = effective_capacity * float(telemetry.soc_pct or 0) / 100
        hard_floor_energy = effective_capacity * self.settings.battery_floor_pct / 100
        requirement = ev_requirement(self.settings, devices.ev_soc_pct, now)
        ev_remaining_input_kwh = requirement.required_input_kwh
        connected = bool(devices.ev_home and devices.ev_plugged)

        for point in points:
            fit = point["fit_per_kwh"]
            pv = float(point["pv_kw"])
            base_load = float(point["load_kw"]) + (self.settings.hot_water_kw if point["hot_water"] else 0.0)
            local_point = point["start"].astimezone(ZoneInfo(self.settings.timezone))
            later_points = [
                future for future in points
                if point["end"] <= future["start"]
                and future["start"].astimezone(ZoneInfo(self.settings.timezone)).date() == local_point.date()
                and future["start"].astimezone(ZoneInfo(self.settings.timezone)).hour < self.settings.hot_water_deadline_hour
            ]
            later_conservative_ac_kwh = sum(
                min(
                    self.settings.max_charge_kw,
                    max(0.0, 0.75 * float(future["pv_kw"]) - float(future["load_kw"]) - (self.settings.hot_water_kw if future["hot_water"] else 0.0)),
                ) * INTERVAL_HOURS for future in later_points
            )
            later_confident_ac_kwh = sum(
                min(
                    self.settings.max_charge_kw,
                    max(
                        0.0,
                        self.settings.morning_defer_solar_confidence * float(future["pv_kw"])
                        - float(future["load_kw"])
                        - (self.settings.hot_water_kw if future["hot_water"] else 0.0),
                    ),
                ) * INTERVAL_HOURS for future in later_points
            )
            reserve_pct = protected_reserve_pct(self.settings, telemetry, point["start"])
            export_reserve_pct = reserve_pct
            if 7 <= local_point.hour < self.settings.hot_water_deadline_hour:
                evening_start = datetime.combine(local_point.date(), time(self.settings.hot_water_deadline_hour), tzinfo=local_point.tzinfo).astimezone(UTC)
                morning_end = datetime.combine(local_point.date() + timedelta(days=1), time(7), tzinfo=local_point.tzinfo).astimezone(UTC)
                overnight_ac_kwh = sum(
                    float(future["load_kw"]) * INTERVAL_HOURS
                    for future in points if evening_start <= future["start"] < morning_end
                )
                overnight_target_energy = hard_floor_energy + overnight_ac_kwh / max(self.settings.battery_discharge_efficiency, 0.01)
                mandatory_ev_claim_kwh = ev_remaining_input_kwh if requirement.mandatory else 0.0
                later_battery_charge_ac_kwh = max(0.0, later_conservative_ac_kwh - mandatory_ev_claim_kwh)
                solar_stored_later = later_battery_charge_ac_kwh * self.settings.battery_charge_efficiency
                evening_target_energy = effective_capacity * self.settings.battery_evening_target_pct / 100
                # Existing stored energy cannot be sold if the conservative,
                # non-double-booked later solar budget cannot restore both the
                # 99% evening target and the forecast overnight house reserve.
                house_protected_energy = max(
                    hard_floor_energy,
                    overnight_target_energy - solar_stored_later,
                )
                export_protected_energy = max(
                    house_protected_energy,
                    evening_target_energy - solar_stored_later,
                )
                reserve_pct = max(reserve_pct, min(99.0, house_protected_energy / max(effective_capacity, 0.01) * 100))
                export_reserve_pct = max(
                    reserve_pct,
                    min(99.0, export_protected_energy / max(effective_capacity, 0.01) * 100),
                )
            reserve_energy = effective_capacity * reserve_pct / 100
            export_reserve_energy = effective_capacity * export_reserve_pct / 100
            before_departure = requirement.departure_at is None or point["start"] < requirement.departure_at
            if connected and before_departure and ev_remaining_input_kwh > 0.001:
                available_solar_kw = max(0.0, self.settings.ev_pv_attenuation * pv - base_load)
                available_battery_kw = min(
                    self.settings.max_discharge_kw,
                    max(0.0, energy - reserve_energy) * self.settings.battery_discharge_efficiency / INTERVAL_HOURS,
                )
                deadline_grid = bool(
                    requirement.selected_profile
                    and requirement.latest_start_at is not None
                    and point["start"] >= requirement.latest_start_at
                )
                if requirement.mandatory:
                    permitted_kw = available_solar_kw + available_battery_kw
                    source = "solar_battery"
                    if (self.settings.ev_grid_allowed and not requirement.selected_profile) or deadline_grid:
                        permitted_kw = self.settings.ev_max_amps * self.settings.ev_three_phase_kw_per_amp
                        source = "grid_deadline" if deadline_grid else "grid_allowed"
                elif opportunistic_fit_eligible(self.settings, fit):
                    permitted_kw = available_solar_kw
                    source = "opportunistic_solar"
                else:
                    permitted_kw = 0.0
                    source = "off"
                available_amps = min(self.settings.ev_max_amps, int(permitted_kw / self.settings.ev_three_phase_kw_per_amp))
                if available_amps >= self.settings.ev_min_amps:
                    point["ev_kw"] = round(min(
                        available_amps * self.settings.ev_three_phase_kw_per_amp,
                        ev_remaining_input_kwh / INTERVAL_HOURS,
                    ), 3)
                    point["ev_source"] = source
                    ev_remaining_input_kwh = max(0.0, ev_remaining_input_kwh - point["ev_kw"] * INTERVAL_HOURS)

            total_load = base_load + float(point["ev_kw"])
            solar_to_load = min(pv, total_load)
            deficit = max(0.0, total_load - solar_to_load)
            available_discharge = max(0.0, energy - reserve_energy) * self.settings.battery_discharge_efficiency / INTERVAL_HOURS
            battery_to_load = min(deficit, self.settings.max_discharge_kw, available_discharge)
            grid_import = max(0.0, deficit - battery_to_load)
            energy -= battery_to_load * INTERVAL_HOURS / self.settings.battery_discharge_efficiency

            surplus = max(0.0, pv - solar_to_load)
            charge_room_kw = max(0.0, effective_capacity - energy) / max(self.settings.battery_charge_efficiency * INTERVAL_HOURS, 0.001)
            ac_needed_for_evening = max(
                0.0,
                effective_capacity * self.settings.battery_evening_target_pct / 100 - energy,
            ) / max(self.settings.battery_charge_efficiency, 0.01)
            lower_fit_points = [
                future for future in later_points
                if fit is not None
                and future["fit_per_kwh"] is not None
                and float(future["fit_per_kwh"]) <= (
                    float(fit) - self.settings.morning_defer_min_price_gap_per_kwh
                )
            ]
            lower_fit_charge_ac_kwh = sum(
                min(
                    self.settings.max_charge_kw,
                    max(
                        0.0,
                        self.settings.morning_defer_solar_confidence * float(future["pv_kw"])
                        - float(future["load_kw"])
                        - (self.settings.hot_water_kw if future["hot_water"] else 0.0),
                    ),
                ) * INTERVAL_HOURS for future in lower_fit_points
            )
            mandatory_ev_claim_kwh = ev_remaining_input_kwh if requirement.mandatory else 0.0
            later_confident_charge_ac_kwh = max(0.0, later_confident_ac_kwh - mandatory_ev_claim_kwh)
            later_economic_charge_ac_kwh = max(0.0, lower_fit_charge_ac_kwh - mandatory_ev_claim_kwh)
            current_shiftable_charge_kwh = min(
                surplus,
                self.settings.max_charge_kw,
                charge_room_kw,
            ) * INTERVAL_HOURS
            defer_charge = bool(
                local_point.hour < 12
                and fit is not None and fit > 0
                and later_confident_charge_ac_kwh
                    >= ac_needed_for_evening * self.settings.morning_defer_energy_margin
                and later_economic_charge_ac_kwh
                    >= current_shiftable_charge_kwh * self.settings.morning_defer_energy_margin
            )
            point["battery_charge_deferred"] = defer_charge
            point["battery_charge_defer_budget_kwh"] = round(later_confident_charge_ac_kwh, 3)
            point["battery_charge_lower_fit_budget_kwh"] = round(later_economic_charge_ac_kwh, 3)
            point["battery_charge_required_to_evening_kwh"] = round(ac_needed_for_evening, 3)
            battery_charge = 0.0 if defer_charge else min(surplus, self.settings.max_charge_kw, charge_room_kw)
            energy += battery_charge * INTERVAL_HOURS * self.settings.battery_charge_efficiency
            surplus -= battery_charge
            solar_export = surplus if fit is not None and fit >= 0 else 0.0
            curtailed = max(0.0, surplus - solar_export)

            export_economics = protected_surplus_export_economics(self.settings)
            retained_value = export_economics.retained_value_per_kwh
            marginal_cost = export_economics.marginal_cost_per_kwh
            sell = fit is not None and fit >= self.settings.min_sell_price_per_kwh and fit > marginal_cost
            battery_export = 0.0
            if sell and energy > export_reserve_energy:
                available_export = max(0.0, energy - export_reserve_energy) * self.settings.battery_discharge_efficiency / INTERVAL_HOURS
                dispatch_site_target = profitable_export_site_target_kw(
                    self.settings,
                    float(fit),
                    [
                        float(future["fit_per_kwh"])
                        for future in points
                        if future["start"] > point["start"] and future["fit_per_kwh"] is not None
                    ],
                )
                dispatch_battery_target = max(0.0, dispatch_site_target + total_load - pv)
                dispatch_battery_export = max(0.0, dispatch_battery_target - battery_to_load)
                battery_export = min(
                    max(0.0, self.settings.max_discharge_kw - battery_to_load),
                    available_export,
                    dispatch_battery_export,
                )
                energy -= battery_export * INTERVAL_HOURS / self.settings.battery_discharge_efficiency

            energy = max(hard_floor_energy, min(effective_capacity, energy))
            discharge = battery_to_load + battery_export
            grid_export = solar_export + battery_export
            battery_export_kwh_interval = battery_export * INTERVAL_HOURS
            battery_export_revenue_interval = battery_export_kwh_interval * float(fit or 0)
            battery_export_wear_interval = battery_export_kwh_interval * self.settings.battery_wear_per_kwh
            battery_export_retained_interval = battery_export_kwh_interval * retained_value
            battery_export_net_interval = battery_export_revenue_interval - battery_export_wear_interval - battery_export_retained_interval
            solar_export_revenue_interval = solar_export * INTERVAL_HOURS * float(fit or 0)
            point.update({
                "battery_charge_kw": round(battery_charge, 3),
                "battery_discharge_kw": round(discharge, 3),
                "battery_export_kw": round(battery_export, 3),
                "solar_export_kw": round(solar_export, 3),
                "grid_import_kw": round(grid_import, 3),
                "curtailed_kw": round(curtailed, 3),
                "export": grid_export > 0.05,
                "battery_target_kw": round(discharge, 2),
                "site_export_target_kw": round(grid_export, 2),
                "battery_export_kwh": battery_export_kwh_interval,
                "solar_export_kwh": solar_export * INTERVAL_HOURS,
                "battery_export_revenue": battery_export_revenue_interval,
                "battery_export_wear_cost": battery_export_wear_interval,
                "battery_export_retained_value": battery_export_retained_interval,
                "battery_export_net_benefit": battery_export_net_interval,
                "solar_export_revenue": solar_export_revenue_interval,
                "total_export_revenue": battery_export_revenue_interval + solar_export_revenue_interval,
                "predicted_soc_pct": round(energy / max(effective_capacity, 0.01) * 100, 1),
                "protected_soc_pct": round(reserve_pct, 1),
                "export_protected_soc_pct": round(export_reserve_pct, 1),
            })
            point["flow"] = conserved_power_flow(
                pv_kw=pv,
                battery_kw=discharge - battery_charge,
                grid_kw=grid_import - grid_export,
                ordinary_house_kw=point["load_kw"],
                hot_water_kw=self.settings.hot_water_kw if point["hot_water"] else 0.0,
                ev_kw=point["ev_kw"],
                server_rack_kw=point["server_rack_kw"],
                at=point["start"],
                expected=True,
            )

        hot_water_points = [point for point in points if point["hot_water"]]
        ev_points = [point for point in points if point["ev_kw"] > 0.05]
        export_windows = _windows(points, "export")
        pv_peak = max(points, key=lambda point: point["pv_kw"], default=None)
        soc_values = [float(point["predicted_soc_pct"]) for point in points]
        solar_export_kwh = sum(float(point["solar_export_kw"]) * INTERVAL_HOURS for point in points)
        battery_export_kwh = sum(float(point["battery_export_kw"]) * INTERVAL_HOURS for point in points)
        solar_export_revenue = sum(float(point["solar_export_kw"]) * INTERVAL_HOURS * float(point["fit_per_kwh"] or 0) for point in points)
        battery_export_revenue = sum(float(point["battery_export_kw"]) * INTERVAL_HOURS * float(point["fit_per_kwh"] or 0) for point in points)
        battery_export_wear_cost = sum(float(point["battery_export_wear_cost"]) for point in points)
        battery_export_retained_value = sum(float(point["battery_export_retained_value"]) for point in points)
        battery_export_net_benefit = sum(float(point["battery_export_net_benefit"]) for point in points)
        import_kwh = sum(float(point["grid_import_kw"]) * INTERVAL_HOURS for point in points)
        import_cost = sum(float(point["grid_import_kw"]) * INTERVAL_HOURS * float(point["import_per_kwh"] or 0) for point in points)
        price_coverage_end = max((item.end for item in fit_intervals), default=start)

        if devices.ev_soc_pct is None:
            recommendation = "Waiting for vehicle SOC"
        elif not connected:
            recommendation = "No charging planned while the vehicle is away or unplugged"
        elif requirement.selected_profile:
            recommendation = f"Prepare {requirement.label} by the next 7am departure"
        elif devices.ev_soc_pct < self.settings.ev_min_soc_pct:
            recommendation = "Charge immediately to at least 40% while reserve permits"
        elif ev_points:
            recommendation = "Charge from forecast solar below the opportunistic FIT threshold"
        else:
            recommendation = "Wait for solar below the opportunistic FIT threshold"

        headline = (
            "Preparing the battery and flexible loads around the next profitable export window."
            if export_windows else
            "Using the lowest-value available energy while protecting the overnight house reserve."
        )
        def activity_windows(key: str) -> list[tuple[datetime, datetime]]:
            result: list[tuple[datetime, datetime]] = []
            active_start: datetime | None = None
            active_end: datetime | None = None
            for point in points:
                if bool(point[key]):
                    active_start = active_start or point["start"]
                    active_end = point["end"]
                elif active_start is not None and active_end is not None:
                    result.append((active_start, active_end))
                    active_start = active_end = None
            if active_start is not None and active_end is not None:
                result.append((active_start, active_end))
            return result

        local_reference = now.astimezone(ZoneInfo(self.settings.timezone))
        def group_for(at: datetime) -> str:
            if at <= now + timedelta(minutes=5):
                return "Now"
            if at <= now + timedelta(hours=2):
                return "Next"
            if at.astimezone(ZoneInfo(self.settings.timezone)).date() == local_reference.date():
                return "Today"
            return "Overnight"

        next_actions: list[dict[str, Any]] = []
        for window in export_windows:
            next_actions.append({
                "group": group_for(window["start"]), "start": window["start"].isoformat(), "end": window["end"].isoformat(),
                "title": "Export profitable energy", "reason": "FIT clears the sell floor, wear, and retained-energy value",
                "source": "solar_and_battery", "target": {"site_export_kw": window["max_power_kw"], "battery_export_kwh": window["battery_export_kwh"]},
                "price_range": {"min_per_kwh": window["min_price_per_kwh"], "max_per_kwh": window["max_price_per_kwh"]},
                "confidence": {"score": 0.75, "label": "medium"},
            })
        for action_start, action_end in activity_windows("hot_water"):
            matching = [point for point in points if action_start <= point["start"] < action_end]
            prices = [point["fit_per_kwh"] for point in matching if point["fit_per_kwh"] is not None]
            next_actions.append({
                "group": group_for(action_start), "start": action_start.isoformat(), "end": action_end.isoformat(),
                "title": "Run hot water", "reason": "Lowest forecast solar opportunity cost before the service deadline",
                "source": "solar_or_grid_rescue", "target": {"power_kw": self.settings.hot_water_kw},
                "price_range": {"min_per_kwh": min(prices) if prices else None, "max_per_kwh": max(prices) if prices else None},
                "confidence": {"score": 0.7, "label": "medium"},
            })
        for action_start, action_end in activity_windows("ev_kw"):
            matching = [point for point in points if action_start <= point["start"] < action_end]
            prices = [point["fit_per_kwh"] for point in matching if point["fit_per_kwh"] is not None]
            next_actions.append({
                "group": group_for(action_start), "start": action_start.isoformat(), "end": action_end.isoformat(),
                "title": f"Charge EV toward {requirement.target_soc_pct:.0f}%", "reason": recommendation,
                "source": matching[0]["ev_source"] if matching else "planned_energy", "target": {"soc_pct": requirement.target_soc_pct, "max_power_kw": max((point["ev_kw"] for point in matching), default=0)},
                "price_range": {"min_per_kwh": min(prices) if prices else None, "max_per_kwh": max(prices) if prices else None},
                "confidence": {"score": 0.7, "label": "medium"},
            })
        for action_start, action_end in activity_windows("battery_charge_deferred"):
            matching = [point for point in points if action_start <= point["start"] < action_end]
            prices = [point["fit_per_kwh"] for point in matching if point["fit_per_kwh"] is not None]
            next_actions.append({
                "group": group_for(action_start), "start": action_start.isoformat(), "end": action_end.isoformat(),
                "title": "Defer battery charging for morning FIT", "reason": "Conservative later solar has enough energy and charging time to reach the evening target",
                "source": "morning_solar_export", "target": {"evening_soc_pct": self.settings.battery_evening_target_pct},
                "price_range": {"min_per_kwh": min(prices) if prices else None, "max_per_kwh": max(prices) if prices else None},
                "confidence": {"score": 0.75, "label": "medium"},
            })
        next_actions.sort(key=lambda action: action["start"])
        narrative = {
            "headline": headline,
            "current_summary": next_actions[0]["title"] if next_actions and next_actions[0]["group"] == "Now" else "Normal house supply is active; waiting for the next planned action.",
            "next_actions": next_actions,
            "groups": {name: [action for action in next_actions if action["group"] == name] for name in ("Now", "Next", "Today", "Overnight")},
            "house": "Solar serves normal loads first; the battery covers remaining house load above its protected reserve.",
            "battery": "Battery export is planned only above the sell floor and retained-energy value.",
            "ev": f"{requirement.label}: target {requirement.target_soc_pct:.0f}%" + (f" by {requirement.departure_at.isoformat()}." if requirement.departure_at else " with no fixed deadline."),
            "hot_water": (
                f"{len(hot_water_points)} five-minute hot-water blocks are scheduled across the 36-hour horizon."
                if hot_water_points else "No hot-water blocks remain in the current horizon."
            ),
            "export": f"{len(export_windows)} profitable export window(s) are currently planned." if export_windows else "No battery export window currently clears the economic threshold.",
        }

        return {
            "schema_version": 3,
            "software_revision": self.settings.software_revision,
            "configuration_revision": self.settings.configuration_revision(),
            "generated_at": now.isoformat(),
            "horizon_end": (start + timedelta(hours=36)).isoformat(),
            "forecast_coverage_end": price_coverage_end.isoformat(),
            "protected_reserve_pct": points[0]["protected_soc_pct"] if points else round(protected_reserve_pct(self.settings, telemetry, now), 1),
            "export_protected_reserve_pct": points[0]["export_protected_soc_pct"] if points else round(protected_reserve_pct(self.settings, telemetry, now), 1),
            "narrative": narrative,
            "predicted_soc_path": [{"at": point["end"].isoformat(), "soc_pct": point["predicted_soc_pct"]} for point in points[::6]],
            "export_windows": [{**window, "start": window["start"].isoformat(), "end": window["end"].isoformat()} for window in export_windows],
            "hot_water": {
                "remaining_hours": round(float(next_hot_water_day["remaining_hours"]), 2) if next_hot_water_day else 0.0,
                "planned_start": next_hot_water_day["planned_start"].isoformat() if next_hot_water_day and next_hot_water_day["planned_start"] else None,
                "planned_end": next_hot_water_day["planned_end"].isoformat() if next_hot_water_day and next_hot_water_day["planned_end"] else None,
                "deadline": next_hot_water_day["deadline"].isoformat() if next_hot_water_day else None,
                "blocks": int(next_hot_water_day["scheduled_blocks"]) if next_hot_water_day else 0,
                "horizon_blocks": len(hot_water_points),
                "daily_schedules": [
                    {
                        **day,
                        "deadline": day["deadline"].isoformat(),
                        "planned_start": day["planned_start"].isoformat() if day["planned_start"] else None,
                        "planned_end": day["planned_end"].isoformat() if day["planned_end"] else None,
                    }
                    for day in daily_hot_water
                ],
            },
            "ev": {
                **requirement.as_dict(),
                "trip_profile": requirement.mode.value,
                "trip_requirement": requirement.label,
                "charge_limit_pct": requirement.command_limit_pct,
                "grid_allowed": self.settings.ev_grid_allowed,
                "opportunistic_fit_max_per_kwh": self.settings.ev_opportunistic_fit_max_per_kwh,
                "recommendation": recommendation,
                "planned_start": ev_points[0]["start"].isoformat() if ev_points else None,
                "planned_end": ev_points[-1]["end"].isoformat() if ev_points else None,
                "planned_input_kwh": round(sum(float(point["ev_kw"]) for point in ev_points) * INTERVAL_HOURS, 2),
                "unmet_input_kwh": round(max(0.0, ev_remaining_input_kwh), 2),
                "source_energy_kwh": {
                    source: round(sum(float(point["ev_kw"]) * INTERVAL_HOURS for point in ev_points if point["ev_source"] == source), 2)
                    for source in ("solar_battery", "opportunistic_solar", "grid_allowed", "grid_deadline")
                },
            },
            "summary": {
                "expected_pv_kwh": round(sum(float(point["pv_kw"]) for point in points) * INTERVAL_HOURS, 2),
                "expected_ordinary_house_load_kwh": round(sum(float(point["load_kw"]) for point in points) * INTERVAL_HOURS, 2),
                "expected_house_load_kwh": round(sum(
                    float(point["load_kw"])
                    + float(point["ev_kw"])
                    + (self.settings.hot_water_kw if point["hot_water"] else 0.0)
                    for point in points
                ) * INTERVAL_HOURS, 2),
                "expected_total_house_load_kwh": round(sum(
                    float(point["load_kw"])
                    + float(point["ev_kw"])
                    + (self.settings.hot_water_kw if point["hot_water"] else 0.0)
                    for point in points
                ) * INTERVAL_HOURS, 2),
                "expected_server_rack_kwh": round(sum(float(point["server_rack_kw"]) for point in points) * INTERVAL_HOURS, 2),
                "expected_hot_water_kwh": round(len(hot_water_points) * self.settings.hot_water_kw * INTERVAL_HOURS, 2),
                "expected_ev_input_kwh": round(sum(float(point["ev_kw"]) for point in ev_points) * INTERVAL_HOURS, 2),
                "solar_export_kwh": round(solar_export_kwh, 2),
                "battery_export_kwh": round(battery_export_kwh, 2),
                "total_export_kwh": round(solar_export_kwh + battery_export_kwh, 2),
                "solar_export_revenue": round(solar_export_revenue, 2),
                "battery_export_revenue": round(battery_export_revenue, 2),
                "battery_export_wear_cost": round(battery_export_wear_cost, 2),
                "battery_export_retained_value": round(battery_export_retained_value, 2),
                "battery_export_net_benefit": round(
                    round(battery_export_revenue, 2)
                    - round(battery_export_wear_cost, 2)
                    - round(battery_export_retained_value, 2),
                    2,
                ),
                "total_export_revenue": round(solar_export_revenue + battery_export_revenue, 2),
                "grid_import_kwh": round(import_kwh, 2),
                "grid_import_cost": round(import_cost, 2),
                "predicted_soc_min_pct": round(min(soc_values), 1) if soc_values else None,
                "predicted_soc_max_pct": round(max(soc_values), 1) if soc_values else None,
                "predicted_soc_end_pct": round(soc_values[-1], 1) if soc_values else None,
                "expected_pv_peak_kw": round(float(pv_peak["pv_kw"]), 2) if pv_peak else None,
                "expected_pv_peak_at": pv_peak["start"].isoformat() if pv_peak else None,
                "priced_horizon_hours": round(max(0.0, (price_coverage_end - start).total_seconds() / 3600), 1),
            },
            "points": [{**point, "start": point["start"].isoformat(), "end": point["end"].isoformat()} for point in points],
        }
