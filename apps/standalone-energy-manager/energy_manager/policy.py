from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
import math
from zoneinfo import ZoneInfo

from .config import Settings
from .economics import protected_surplus_export_economics, profitable_export_site_target_kw
from .ev import ev_requirement, opportunistic_fit_eligible
from .models import Command, DeviceState, PriceInterval, Telemetry, command_semantic_hash


def next_boundary(now: datetime, minutes: int = 5) -> datetime:
    epoch = int(now.timestamp())
    seconds = minutes * 60
    return datetime.fromtimestamp(((epoch // seconds) + 1) * seconds, UTC)


def protected_reserve_pct(settings: Settings, telemetry: Telemetry, now: datetime, overnight_load_kw: float = 1.5) -> float:
    local = now.astimezone(ZoneInfo(settings.timezone))
    tomorrow_7 = datetime.combine(local.date() + timedelta(days=1), time(7), tzinfo=local.tzinfo)
    today_7 = datetime.combine(local.date(), time(7), tzinfo=local.tzinfo)
    if local < today_7:
        hours = (today_7 - local).total_seconds() / 3600
    elif local.hour >= 16:
        hours = (tomorrow_7 - local).total_seconds() / 3600
    else:
        hours = 0.0
    effective = settings.battery_capacity_kwh * max(float(telemetry.soh_pct or 100), 1) / 100
    reserve_kwh = max(0.0, hours * overnight_load_kw)
    reserve_pct = settings.battery_floor_pct + reserve_kwh / max(effective * settings.battery_discharge_efficiency, 1) * 100
    return max(settings.battery_floor_pct, min(80.0, reserve_pct))


def ev_power_for_amps(amps: int, kw_per_amp: float = 0.69) -> float:
    return max(0, amps) * max(0.0, kw_per_amp)


def amps_for_power(power_kw: float, kw_per_amp: float = 0.69) -> int:
    return max(0, math.floor(max(0.0, power_kw) / max(kw_per_amp, 0.001) + 1e-9))


def fresh_price_value(settings: Settings, interval: PriceInterval | None, now: datetime) -> float | None:
    if interval is None:
        return None
    age = (now - interval.received_at).total_seconds()
    maximum_age = settings.amber_forecast_max_age_seconds if interval.estimate else 330
    if interval.start <= now < interval.end and 0 <= age <= maximum_age:
        return interval.price_per_kwh
    return None


class Policy:
    def __init__(self, settings: Settings):
        self.settings = settings

    def command(
        self,
        telemetry: Telemetry,
        devices: DeviceState,
        fit: PriceInterval | None,
        import_price: PriceInterval | None,
        expected_pv_kw: float,
        hot_water_runtime_hours: float,
        future_fit: list[PriceInterval] | None = None,
        now: datetime | None = None,
        protected_reserve_override_pct: float | None = None,
        expected_pv_measured_at: datetime | None = None,
        hot_water_scheduled: bool | None = None,
        ev_scheduled_kw: float | None = None,
        export_reserve_override_pct: float | None = None,
    ) -> Command:
        now = now or datetime.now(UTC)
        expires = next_boundary(now)
        reserve = max(
            protected_reserve_pct(self.settings, telemetry, now),
            float(protected_reserve_override_pct or self.settings.battery_floor_pct),
        )
        export_reserve = max(reserve, float(export_reserve_override_pct or reserve))
        fit_value = fresh_price_value(self.settings, fit, now)
        import_value = fresh_price_value(self.settings, import_price, now)
        negative = fit_value is not None and fit_value < 0
        load = max(0.0, float(telemetry.load_kw or 0))
        actual_pv = max(0.0, float(telemetry.pv_kw or 0))
        potential_age = (now - expected_pv_measured_at).total_seconds() if expected_pv_measured_at else float("inf")
        fresh_potential = 0 <= potential_age <= self.settings.irradiance_max_age_seconds
        potential_pv = max(actual_pv, expected_pv_kw if fresh_potential else 0.0)
        soc = float(telemetry.soc_pct or 0)
        ev_need = ev_requirement(self.settings, devices.ev_soc_pct, now)

        remaining_hw = max(0.0, self.settings.hot_water_target_hours - hot_water_runtime_hours)
        local = now.astimezone(ZoneInfo(self.settings.timezone))
        deadline = datetime.combine(local.date(), time(self.settings.hot_water_deadline_hour), tzinfo=local.tzinfo)
        rescue_start = deadline - timedelta(hours=remaining_hw)
        rescue = remaining_hw > 0 and local >= rescue_start
        # Expected uncurtailed output is usable during negative FIT because
        # anti-reflux may be suppressing the measured PV. At positive FIT,
        # only measured PV is trusted for starting a solar-only flexible load.
        dispatch_pv = potential_pv if negative else actual_pv
        existing_hot_water_kw = self.settings.hot_water_kw if devices.hot_water_on else max(0.0, devices.hot_water_power_kw)
        load_without_hot_water = max(0.0, load - existing_hot_water_kw)
        solar_surplus = dispatch_pv - load_without_hot_water
        has_hot_water_solar = solar_surplus >= self.settings.hot_water_kw + 0.5
        schedule_allows_hot_water = hot_water_scheduled is not False
        fixed_timer_active = (
            self.settings.hot_water_enabled
            and self.settings.hot_water_fixed_timer
            and self.settings.hot_water_timer_start_hour <= local.hour < self.settings.hot_water_timer_end_hour
        )
        if not self.settings.hot_water_enabled:
            hot_water_on = False
            hot_water_source = "away"
        elif self.settings.hot_water_fixed_timer:
            # Fixed mode is intentionally independent of forecasts, prices and
            # accumulated service time. The relay follows the wall clock.
            hot_water_on = fixed_timer_active
            hot_water_source = (
                "fixed_timer_solar"
                if hot_water_on and has_hot_water_solar
                else "fixed_timer_grid"
                if hot_water_on
                else "off"
            )
        else:
            hot_water_on = (
                remaining_hw > 0
                and local < deadline
                and ((has_hot_water_solar and schedule_allows_hot_water) or rescue)
            )
            hot_water_source = (
                "grid_rescue"
                if hot_water_on and rescue and solar_surplus < self.settings.hot_water_kw + 0.5
                else ("negative_fit" if negative else "solar")
                if hot_water_on
                else "off"
            )

        ordinary_nonflex_load = max(0.0, load - devices.ev_power_kw - existing_hot_water_kw)
        planned_hot_water_kw = self.settings.hot_water_kw if hot_water_on else 0.0
        non_ev_load = ordinary_nonflex_load + planned_hot_water_kw
        # Negative FIT has no export opportunity cost: use the fresh Ecowitt
        # expected-uncurtailed generation directly, then subtract the other
        # site loads. Positive low-FIT opportunities retain the conservative
        # attenuation. Measured grid/battery feedback below corrects either
        # estimate when clouds move faster than the irradiance signal.
        ev_solar_budget_kw = dispatch_pv if negative else self.settings.ev_pv_attenuation * dispatch_pv
        available_for_ev = ev_solar_budget_kw - non_ev_load
        ev_on = False
        ev_amps = 0
        ev_required = ev_need.mandatory
        at_reserve = soc <= reserve + 0.5
        deadline_grid = bool(
            ev_need.selected_profile
            and ev_need.latest_start_at is not None
            and now >= ev_need.latest_start_at
        )
        grid_permitted = deadline_grid if ev_need.selected_profile else self.settings.ev_grid_allowed
        below_target = devices.ev_soc_pct is None or devices.ev_soc_pct < ev_need.target_soc_pct
        opportunity_eligible = negative or opportunistic_fit_eligible(self.settings, fit_value)
        # Low/negative live FIT is an immediate operating permission. The
        # rolling plan describes the day, but must not veto a fresh Ecowitt
        # solar opportunity that appears inside the interval.
        schedule_allows_ev = (
            opportunity_eligible
            or ev_scheduled_kw is None
            or ev_scheduled_kw >= ev_power_for_amps(
                self.settings.ev_min_amps,
                self.settings.ev_three_phase_kw_per_amp,
            )
        )
        if devices.ev_home and devices.ev_ble_available and devices.ev_plugged and below_target and schedule_allows_ev:
            if ev_required and (not at_reserve or grid_permitted or available_for_ev >= ev_power_for_amps(self.settings.ev_min_amps, self.settings.ev_three_phase_kw_per_amp)):
                effective_capacity = self.settings.battery_capacity_kwh * max(float(telemetry.soh_pct or 100), 1) / 100
                energy_headroom_kw = max(0.0, (soc - reserve) / 100 * effective_capacity) * self.settings.battery_discharge_efficiency / (5 / 60)
                existing_site_deficit_kw = max(0.0, non_ev_load - dispatch_pv)
                battery_headroom_kw = min(
                    max(0.0, self.settings.max_discharge_kw - existing_site_deficit_kw),
                    energy_headroom_kw,
                ) if not at_reserve else 0.0
                desired_kw = max(available_for_ev, ev_power_for_amps(self.settings.ev_min_amps, self.settings.ev_three_phase_kw_per_amp))
                if ev_scheduled_kw is not None:
                    desired_kw = min(desired_kw, max(0.0, ev_scheduled_kw))
                if not grid_permitted:
                    desired_kw = min(desired_kw, max(0.0, available_for_ev) + battery_headroom_kw)
                if grid_permitted or desired_kw >= ev_power_for_amps(self.settings.ev_min_amps, self.settings.ev_three_phase_kw_per_amp):
                    ev_amps = max(self.settings.ev_min_amps, min(self.settings.ev_max_amps, amps_for_power(desired_kw, self.settings.ev_three_phase_kw_per_amp)))
                    ev_on = True
            elif opportunity_eligible:
                available_opportunistic_kw = max(0.0, available_for_ev)
                # During low/negative FIT this is deliberately based on the
                # fresh Ecowitt expected-uncurtailed PV calculation. Actual PV
                # is suppressed by anti-reflux and the rolling plan is not a
                # reliable live power meter. Measured grid/battery feedback
                # below remains the safety correction.
                ev_amps = min(self.settings.ev_max_amps, amps_for_power(available_opportunistic_kw, self.settings.ev_three_phase_kw_per_amp))
                ev_on = ev_amps >= self.settings.ev_min_amps

        # Actual stationary-battery discharge attenuates EV current, but does
        # not replace expected-PV feed-forward. Reduce before stopping.
        unwanted_battery_kw = max(0.0, float(telemetry.battery_kw or 0) - 0.3) if not ev_required else 0.0
        # The two-second site meter naturally flickers by a few hundred watts
        # around zero. A 0.1 kW threshold made the minimum 6 A charge stop on a
        # single harmless sample. Use the same 0.3 kW control deadband as the
        # stationary-battery guard; sustained excess still trims immediately.
        unwanted_grid_kw = max(0.0, float(telemetry.grid_kw or 0) - 0.3) if not grid_permitted else 0.0
        if ev_on and unwanted_battery_kw + unwanted_grid_kw > 0:
            trim = max(
                1,
                math.ceil(
                    (unwanted_battery_kw + unwanted_grid_kw)
                    / max(self.settings.ev_three_phase_kw_per_amp, 0.001)
                ),
            )
            ev_amps = max(0, ev_amps - trim)
            ev_on = ev_amps >= self.settings.ev_min_amps

        mode = "self_consume"
        battery_target = 0.0
        site_export_target = 0.0
        reason = "solar_first_self_consumption"

        min_sell = self.settings.min_sell_price_per_kwh
        # SOC above export_reserve is already proven surplus to the protected
        # house trajectory. Do not charge it with avoided import a second time.
        export_economics = protected_surplus_export_economics(self.settings)
        sell_eligible = (
            fit_value is not None
            and fit_value >= min_sell
            and fit_value > export_economics.marginal_cost_per_kwh
            and soc > export_reserve + 0.5
        )
        if sell_eligible:
            site_export_target = profitable_export_site_target_kw(
                self.settings,
                fit_value,
                [item.price_per_kwh for item in future_fit or [] if item.start > now],
            )
            battery_target = min(self.settings.max_discharge_kw, max(0.0, site_export_target + load - actual_pv))
            mode = "export"
            reason = "profitable_amber_export"

        # Grid-only hot-water rescue is a load-segregation command: battery
        # covers the estimated ordinary load, while the element tranche imports.
        if hot_water_on and hot_water_source in {"grid_rescue", "fixed_timer_grid"}:
            mode = "export"
            # Force only the ordinary-load shortfall. Solar still serves the
            # house first; the element tranche is left to solar/grid and the
            # inverter reserve prevents this command crossing protected SOC.
            battery_target = min(
                self.settings.max_discharge_kw,
                # A small non-zero target keeps SAJ in bounded force mode when
                # solar already covers ordinary load. Self-consume would be
                # free to discharge into the 3.7 kW element.
                max(0.1, ordinary_nonflex_load - actual_pv),
            )
            site_export_target = 0.0
            reason = "hot_water_fixed_timer_grid_only" if hot_water_source == "fixed_timer_grid" else "hot_water_grid_only_rescue"

        if negative:
            # Absorption has priority. Never force battery export in a negative interval.
            mode = "self_consume"
            battery_target = 0.0
            site_export_target = 0.0
            reason = "negative_fit_zero_export_absorb_locally"
            if hot_water_on and solar_surplus < self.settings.hot_water_kw + 0.5 and soc > reserve:
                # Anti-reflux prevents this controlled discharge from leaking
                # to grid. It supplies only the pre-existing site load so the
                # newly-added 3.7 kW element remains a grid/solar tranche.
                mode = "export"
                battery_target = max(0.0, load - (self.settings.hot_water_kw if devices.hot_water_on else 0.0))
                reason = "negative_fit_hot_water_battery_exclusion"

        if not telemetry.healthy:
            mode = "self_consume"
            battery_target = 0.0
            site_export_target = 0.0
            hot_water_on = False
            ev_on = False
            ev_amps = 0
            reason = "invalid_saj_telemetry"

        result = Command(
            mode=mode,
            battery_target_kw=round(battery_target, 2),
            site_export_target_kw=round(site_export_target, 2),
            protected_soc_pct=round(export_reserve if mode == "export" and reason == "profitable_amber_export" else reserve, 1),
            zero_export=negative,
            ev_on=ev_on,
            ev_amps=ev_amps,
            ev_target_soc_pct=ev_need.command_limit_pct,
            hot_water_on=hot_water_on,
            hot_water_source=hot_water_source,
            reason=reason,
            generated_at=now,
            expires_at=expires,
        )
        result.semantic_hash = command_semantic_hash(result)
        return result
