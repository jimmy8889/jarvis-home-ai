from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, time, timedelta
from bisect import bisect_left, bisect_right
import hashlib
import math
from typing import Any
from zoneinfo import ZoneInfo

from .config import ENTITY, Settings
from .models import DispatchInterval, Plan, Slot, TelemetryHealth
from .parsing import active_price_pair, build_slots, numeric_state, parse_datetime, state_is_on
from .state import LearningState


@dataclass
class _Transition:
    previous_level: int
    battery_kw: float
    grid_kwh: float
    interval_cost: float
    revenue: float
    wear_cost: float
    curtailed_kwh: float


@dataclass
class _EVSchedule:
    target_soc_pct: float
    required_kwh: float
    action: str
    charge_start: datetime | None
    charge_end: datetime | None
    estimated_cost: float
    solar_energy_kwh: float
    fallback_energy_kwh: float


class EnergyOptimizer:
    def __init__(self, settings: Settings, learning: LearningState):
        self.settings = settings
        self.learning = learning
        self.timezone = ZoneInfo(settings.timezone)

    def build_plan(
        self,
        raw_states: list[dict[str, Any]],
        now: datetime | None = None,
        *,
        telemetry_health: TelemetryHealth | None = None,
    ) -> Plan:
        now = (now or datetime.now(self.timezone)).astimezone(self.timezone)
        states = {item.get("entity_id", ""): item for item in raw_states}
        solar_context = self._solar_potential_context(states, now)
        self._update_learning(states, now, solar_context)

        fit_entity = states.get(ENTITY["amber_fit"], {})
        import_entity = states.get(ENTITY["amber_import"], {})
        solar_entities = [states.get(ENTITY["solcast_today"], {}), states.get(ENTITY["solcast_tomorrow"], {})]
        weather = str(states.get(ENTITY["weather"], {}).get("state", "unknown"))
        slots = build_slots(
            now=now,
            horizon_hours=self.settings.horizon_hours,
            slot_minutes=self.settings.slot_minutes,
            amber_interval_minutes=self.settings.amber_interval_minutes,
            amber_fine_horizon_minutes=self.settings.amber_fine_horizon_minutes,
            timezone=self.timezone,
            fit_entity=fit_entity,
            import_entity=import_entity,
            solar_entities=solar_entities,
            load_forecast=self.learning.forecast_load,
            calibration_ratio=self.learning.solar_calibration_ratio,
            weather_condition=weather,
            live_solar_correction_factor=solar_context[3],
            live_solar_correction_minutes=self.settings.solar_live_correction_minutes,
        )

        morning, evening = self._detect_crossovers(slots, now)
        raw_soc = numeric_state(states, ENTITY["battery_soc"], float("nan"))
        soc = raw_soc if math.isfinite(raw_soc) and 0.0 <= raw_soc <= 100.0 else 50.0
        capacity = numeric_state(states, ENTITY["battery_usable"], self.settings.battery_capacity_kwh)
        capacity = min(60.0, max(35.0, capacity))
        self._schedule_hot_water(slots, states, now, evening)
        ev = self._schedule_ev(slots, states, now, soc, capacity, evening)
        intervals = self._dispatch(slots, soc, capacity, evening, morning)

        first = intervals[0]
        site_export = max(0.0, -first.site_grid_kw)
        if first.pv_curtailment_kw > 0.5:
            action = "curtail_pv"
            reason = f"Curtail {first.pv_curtailment_kw:.1f} kW rather than export at FIT ${first.export_price:.3f}/kWh"
        elif first.battery_kw > 0.5 and site_export > max(0.5, first.solar_kw - first.load_kw):
            action = "discharge_export"
            reason = f"Export target {site_export:.1f} kW at FIT ${first.export_price:.3f}/kWh"
        elif first.battery_kw > 0.5:
            action = "self_consumption"
            reason = f"Cover household load at import ${first.import_price:.3f}/kWh"
        elif first.battery_kw < -0.5 and first.site_grid_kw > 0.2:
            action = "grid_charge"
            reason = f"Profitable grid charge at ${first.import_price:.3f}/kWh"
        elif first.battery_kw < -0.5:
            action = "pv_charge"
            reason = "Store forecast solar surplus for higher-value use"
        else:
            action = "idle"
            reason = "No battery movement clears losses, wear and uncertainty"

        mode = str(states.get(ENTITY["mode"], {}).get("state", "Shadow")).lower()
        manual_override = state_is_on(states, ENTITY["manual_override"])
        battery_enabled = state_is_on(states, ENTITY["battery_control"])
        rollout_approved = state_is_on(states, ENTITY["rollout_approved"])
        current_price_valid = bool(slots) and slots[0].price_source == "amber_live"
        telemetry_issue = self._actuation_telemetry_issue(states, telemetry_health)
        actuation_allowed = (
            mode == "active"
            and battery_enabled
            and rollout_approved
            and not manual_override
            and current_price_valid
            and telemetry_issue is None
        )
        warnings: list[str] = []
        if telemetry_issue:
            warnings.append(f"{telemetry_issue}; battery actuation is disabled")
        if not current_price_valid:
            warnings.append(
                "Current Amber five-minute FIT/import interval is invalid; battery actuation is disabled"
            )
        price_warning_horizon = now + timedelta(hours=6)
        if any(
            not slot.price_source.startswith("amber")
            for slot in slots
            if slot.start < price_warning_horizon
        ):
            warnings.append("Amber forecast horizon is incomplete; historical price fallback is in use")
        if not solar_entities[0].get("attributes", {}).get("detailedForecast"):
            warnings.append("Solcast detailed forecast is unavailable")
        if manual_override:
            warnings.append("Manual override is enabled")
        if not rollout_approved:
            warnings.append("Rollout approval is off")
        if not battery_enabled:
            warnings.append("Battery control is off")
        if mode != "active":
            warnings.append(f"{mode.title()} mode: no optimiser battery command may be actuated")

        confidence = self.learning.solar_confidence
        if warnings:
            confidence = max(0.25, confidence - 0.08 * len(warnings))
        generated = now.astimezone(self.timezone)
        first_interval_end = first.start + timedelta(minutes=first.duration_minutes)
        valid_until = max(
            generated + timedelta(seconds=1),
            min(generated + timedelta(minutes=10), first_interval_end),
        )
        plan_seed = f"{generated.isoformat()}:{first.battery_kw:.3f}:{first.site_grid_kw:.3f}"
        plan_id = f"eop-{generated:%Y%m%dT%H%M%S}-{hashlib.sha256(plan_seed.encode()).hexdigest()[:8]}"
        expected_cost = sum(max(0.0, item.site_grid_kw) * item.duration_minutes / 60 * item.import_price for item in intervals)
        expected_revenue = sum(max(0.0, -item.site_grid_kw) * item.duration_minutes / 60 * item.export_price for item in intervals)
        expected_wear = sum(item.wear_cost if hasattr(item, "wear_cost") else max(0.0, item.battery_kw) * item.duration_minutes / 60 * self.settings.battery_wear_per_kwh for item in intervals)

        return Plan(
            plan_id=plan_id,
            generated_at=generated,
            valid_until=valid_until,
            mode=mode,
            actuation_allowed=actuation_allowed,
            action=action,
            reason=reason,
            confidence=confidence,
            battery_power_target_kw=max(-self.settings.battery_max_charge_kw, min(self.settings.battery_max_discharge_kw, first.battery_kw)),
            site_export_target_kw=site_export,
            pv_export_command="curtail" if first.pv_curtailment_kw > 0.5 else "allow",
            pv_curtailment_target_kw=first.pv_curtailment_kw,
            hot_water_command="on" if first.hot_water_kw > 0 else "off",
            ev_action=ev.action if first.ev_kw <= 0 else (
                "charge"
                if state_is_on(states, ENTITY["ev_plugged"]) and state_is_on(states, ENTITY["ev_home"])
                else "recommend_charge"
            ),
            ev_target_soc_pct=ev.target_soc_pct,
            ev_required_kwh=ev.required_kwh,
            ev_charge_amps_target=slots[0].ev_charge_amps if first.ev_kw > 0 else 0,
            ev_power_target_kw=slots[0].ev_power_target_kw if first.ev_kw > 0 else 0.0,
            ev_charge_source=slots[0].ev_charge_source if first.ev_kw > 0 else "none",
            ev_solar_energy_kwh=ev.solar_energy_kwh,
            ev_fallback_energy_kwh=ev.fallback_energy_kwh,
            ev_charge_start=ev.charge_start,
            ev_charge_end=ev.charge_end,
            ev_estimated_cost=ev.estimated_cost,
            morning_takeover=morning,
            evening_crossover=evening,
            expected_cost=expected_cost,
            expected_revenue=expected_revenue,
            expected_wear_cost=expected_wear,
            warnings=warnings,
            intervals=intervals,
            solar_potential_kw=solar_context[0],
            solar_actual_kw=solar_context[1],
            solar_curtailed_estimate_kw=solar_context[2],
            solar_live_correction_factor=solar_context[3],
            solar_potential_source=solar_context[4],
        )

    def build_fast_price_plan(
        self,
        base_plan: Plan,
        raw_states: list[dict[str, Any]],
        *,
        now: datetime | None = None,
        telemetry_health: TelemetryHealth | None = None,
        force_safe_reason: str | None = None,
    ) -> Plan:
        """Refresh only the live five-minute command from a retained full plan.

        This path intentionally does not invent a new 36-hour trajectory.  It
        preserves the cached plan's morning reserve and higher-value future
        allocations, while allowing a newly exceptional live FIT to use the
        energy that is genuinely available above that reserve.  The complete
        dynamic programme follows asynchronously and replaces this short-lived
        plan.
        """
        now = (now or datetime.now(self.timezone)).astimezone(self.timezone)
        states = {item.get("entity_id", ""): item for item in raw_states}
        mode = str(states.get(ENTITY["mode"], {}).get("state", "Shadow")).lower()
        gates_allowed = (
            mode == "active"
            and state_is_on(states, ENTITY["battery_control"])
            and state_is_on(states, ENTITY["rollout_approved"])
            and not state_is_on(states, ENTITY["manual_override"])
        )
        plan_age_seconds = max(
            0.0,
            (now - base_plan.generated_at.astimezone(self.timezone)).total_seconds(),
        )
        active_pair = active_price_pair(
            states.get(ENTITY["amber_fit"], {}),
            states.get(ENTITY["amber_import"], {}),
            now,
            self.timezone,
            self.settings.amber_interval_minutes,
        )
        fit_live, import_live = active_pair if active_pair else (None, None)
        telemetry_issue = self._actuation_telemetry_issue(states, telemetry_health)
        safe_reason = force_safe_reason or telemetry_issue
        if safe_reason is None:
            if plan_age_seconds > self.settings.fast_dispatch_plan_max_age_seconds:
                safe_reason = "cached horizon is stale"
            elif not fit_live or not import_live:
                safe_reason = "live Amber interval is unavailable or stale"
            elif not gates_allowed or not base_plan.actuation_allowed:
                safe_reason = "production battery gates are not all enabled"

        active_end = min(
            fit_live[2] if fit_live else now + timedelta(minutes=self.settings.amber_interval_minutes),
            import_live[2] if import_live else now + timedelta(minutes=self.settings.amber_interval_minutes),
        )
        duration_h = max(1 / 3600, (active_end - now).total_seconds() / 3600)
        matching = next(
            (
                item
                for item in base_plan.intervals
                if item.start <= now
                < item.start + timedelta(minutes=item.duration_minutes)
            ),
            next((item for item in base_plan.intervals if item.start > now), base_plan.intervals[0]),
        )
        fit = fit_live[0] if fit_live else matching.export_price
        import_price = import_live[0] if import_live else matching.import_price
        capacity = numeric_state(states, ENTITY["battery_usable"], 0.0)
        raw_soc = numeric_state(states, ENTITY["battery_soc"], -1.0)
        if not 35.0 <= capacity <= 60.0 or not 0.0 <= raw_soc <= 100.0:
            safe_reason = "live battery SOC or capacity is unavailable"
            capacity = min(60.0, max(35.0, capacity or self.settings.battery_capacity_kwh))
            raw_soc = max(self.settings.battery_min_soc_pct, raw_soc)
        live_pv_w = numeric_state(states, ENTITY["pv_power"], float("nan"))
        live_load_w = numeric_state(states, ENTITY["home_load"], float("nan"))
        if not math.isfinite(live_pv_w) or not math.isfinite(live_load_w):
            safe_reason = "live PV or household load telemetry is unavailable"

        # Reduce SOC by the maximum energy the inverter could have discharged
        # since the last same-source heartbeat.  This remains conservative
        # without mistaking an unchanged SOC value for a failed integration.
        unobserved_discharge_kwh = (
            max(
                0.0,
                telemetry_health.soc_source_heartbeat_age_seconds
                if telemetry_health
                and telemetry_health.soc_source_heartbeat_age_seconds is not None
                and math.isfinite(telemetry_health.soc_source_heartbeat_age_seconds)
                else self.settings.fast_dispatch_state_max_age_seconds,
            )
            / 3600
            * self.settings.battery_max_discharge_kw
            / self.settings.battery_discharge_efficiency
        )
        safe_soc = max(
            self.settings.battery_min_soc_pct,
            raw_soc - 100 * unobserved_discharge_kwh / capacity,
        )
        reserve_horizon = base_plan.morning_takeover
        reserve_intervals = [
            item
            for item in base_plan.intervals
            if item.start >= now
            and (reserve_horizon is None or item.start < reserve_horizon)
        ]
        trajectory_floor_soc = min(
            (item.soc_end_pct for item in reserve_intervals),
            default=self.settings.battery_morning_target_soc_pct,
        )
        reserve_soc = max(
            self.settings.battery_min_soc_pct,
            min(trajectory_floor_soc, self.settings.battery_morning_target_soc_pct),
        )
        available_output_kwh = (
            max(0.0, safe_soc - reserve_soc)
            / 100
            * capacity
            * self.settings.battery_discharge_efficiency
        )
        available_discharge_kw = min(
            self.settings.battery_max_discharge_kw,
            available_output_kwh / duration_h,
        )
        future_allocated_values: list[float] = []
        for item in reserve_intervals:
            if item.start < active_end or item.battery_kw <= 0.5:
                continue
            # Reconstruct demand before battery dispatch.  The household
            # portion of future battery output avoids the import tariff; only
            # output beyond that demand earns FIT.  Taking max(import, FIT) for
            # every future kW can materially overstate its retained value when
            # the planned interval is already exporting.
            pre_battery_grid_kw = item.site_grid_kw + item.battery_kw
            future_household_kw = min(
                item.battery_kw,
                max(0.0, pre_battery_grid_kw),
            )
            future_export_kw = max(
                0.0,
                item.battery_kw - future_household_kw,
            )
            if future_household_kw > 1e-6:
                future_allocated_values.append(item.import_price)
            if future_export_kw > 1e-6:
                future_allocated_values.append(item.export_price)
        retained_value = max(
            self.settings.battery_wear_per_kwh,
            max(future_allocated_values, default=0.0),
        )
        live_pv_kw = max(0.0, live_pv_w / 1000) if math.isfinite(live_pv_w) else 0.0
        live_load_kw = max(0.0, live_load_w / 1000) if math.isfinite(live_load_w) else 0.0
        # SAJ home load already includes the active hot-water element and EV.
        # Adding their planned values here would double-count flexible demand.
        household_deficit_kw = max(0.0, live_load_kw - live_pv_kw)

        battery_kw = 0.0
        site_export_kw = 0.0
        pv_curtailment_kw = 0.0
        action = "idle"
        reason = f"Fast safety stop: {safe_reason}" if safe_reason else "Fast live-price refresh"
        pv_export_command = "allow"
        actuation_allowed = gates_allowed and base_plan.actuation_allowed and safe_reason is None
        if safe_reason is None and fit < 0:
            action = "curtail_pv"
            pv_export_command = "curtail"
            pv_curtailment_kw = max(0.0, live_pv_kw - live_load_kw)
            reason = f"Immediate negative-FIT stop/curtail at ${fit:.3f}/kWh"
        elif safe_reason is None:
            economically_positive = fit > self.settings.battery_wear_per_kwh
            exceptional_export_now = fit >= (
                retained_value + self.settings.grid_charge_uncertainty_per_kwh
            )
            exceptional_household_now = import_price >= (
                retained_value + self.settings.grid_charge_uncertainty_per_kwh
            )
            planned_discharge_kw = max(0.0, matching.battery_kw)
            if exceptional_export_now:
                battery_kw = available_discharge_kw
            else:
                # A live price revision must revalue the two marginal uses of
                # cached discharge independently.  Supplying the house avoids
                # the live import price; exporting earns the live FIT.  Retain
                # either portion only when its current value both covers wear
                # and is at least as valuable as battery energy already
                # allocated to a later interval.  This prevents a formerly
                # profitable cached export from consuming energy reserved for
                # a subsequent higher-price window after FIT moves down.
                planned_household_kw = min(
                    planned_discharge_kw,
                    household_deficit_kw,
                )
                planned_export_kw = max(
                    0.0,
                    planned_discharge_kw - planned_household_kw,
                )
                household_value_positive = (
                    import_price > self.settings.battery_wear_per_kwh
                    and import_price >= retained_value
                )
                export_value_positive = (
                    economically_positive and fit >= retained_value
                )
                household_kw = (
                    min(available_discharge_kw, household_deficit_kw)
                    if exceptional_household_now
                    else (
                        planned_household_kw
                        if household_value_positive
                        else 0.0
                    )
                )
                battery_kw = min(
                    available_discharge_kw,
                    household_kw
                    + (planned_export_kw if export_value_positive else 0.0),
                )
            predicted_grid_kw = live_load_kw - live_pv_kw - battery_kw
            site_export_kw = max(0.0, -predicted_grid_kw)
            if battery_kw > 0.5 and site_export_kw > max(0.5, live_pv_kw - live_load_kw):
                action = "discharge_export"
                reason = (
                    f"Immediate profitable export at live FIT ${fit:.3f}/kWh; "
                    f"preserve {reserve_soc:.1f}% planned reserve"
                )
            elif battery_kw > 0.5:
                action = "self_consumption"
                site_export_kw = 0.0
                reason = f"Immediate household supply at import ${import_price:.3f}/kWh"
            else:
                site_export_kw = max(0.0, live_pv_kw - live_load_kw)
                reason = f"Live FIT ${fit:.3f}/kWh does not beat retained battery value"

        discharged_kwh = max(0.0, battery_kw) * duration_h
        soc_end = max(
            self.settings.battery_min_soc_pct,
            safe_soc
            - 100
            * discharged_kwh
            / self.settings.battery_discharge_efficiency
            / capacity,
        )
        fast_interval = replace(
            matching,
            start=now,
            duration_minutes=round(duration_h * 60, 3),
            solar_kw=round(live_pv_kw, 3),
            solar_low_kw=round(live_pv_kw, 3),
            load_kw=round(live_load_kw, 3),
            import_price=round(import_price, 5),
            export_price=round(fit, 5),
            battery_kw=round(battery_kw, 3),
            site_grid_kw=round(-site_export_kw, 3),
            pv_curtailment_kw=round(pv_curtailment_kw, 3),
            soc_start_pct=round(safe_soc, 1),
            soc_end_pct=round(soc_end, 1),
            cost=round(
                -site_export_kw * duration_h * fit
                + discharged_kwh * self.settings.battery_wear_per_kwh,
                4,
            ),
            price_source="amber_live" if fit_live and import_live else "invalid_live_price",
        )
        future_intervals = [item for item in base_plan.intervals if item.start >= active_end]
        generated = now
        plan_seed = (
            f"fast:{generated.isoformat()}:{fit:.6f}:{import_price:.6f}:"
            f"{battery_kw:.3f}:{site_export_kw:.3f}:{safe_reason or ''}"
        )
        warnings = list(base_plan.warnings)
        warnings.append(
            "Fast dispatch from cached horizon; full optimisation pending"
            if safe_reason is None
            else reason
        )
        return replace(
            base_plan,
            plan_id=(
                f"eop-fast-{generated:%Y%m%dT%H%M%S}-"
                f"{hashlib.sha256(plan_seed.encode()).hexdigest()[:8]}"
            ),
            generated_at=generated,
            valid_until=max(generated + timedelta(seconds=1), active_end),
            mode=mode,
            actuation_allowed=actuation_allowed,
            action=action,
            reason=reason,
            battery_power_target_kw=round(battery_kw, 3),
            site_export_target_kw=round(site_export_kw, 3),
            pv_export_command=pv_export_command,
            pv_curtailment_target_kw=round(pv_curtailment_kw, 3),
            hot_water_command="on" if matching.hot_water_kw > 0 else "off",
            warnings=warnings,
            intervals=[fast_interval, *future_intervals],
        )

    def _actuation_telemetry_issue(
        self,
        states: dict[str, dict[str, Any]],
        health: TelemetryHealth | None,
    ) -> str | None:
        """Return the first fail-closed source-health or value error."""
        soc = numeric_state(states, ENTITY["battery_soc"], float("nan"))
        if not math.isfinite(soc) or not 0.0 <= soc <= 100.0:
            return "Battery SOC is unavailable or outside 0-100%"

        heartbeat = numeric_state(
            states,
            ENTITY["battery_soc_heartbeat"],
            float("nan"),
        )
        if not math.isfinite(heartbeat):
            return "SAJ SOC-source heartbeat is unavailable"

        pv_power = numeric_state(states, ENTITY["pv_power"], float("nan"))
        load_power = numeric_state(states, ENTITY["home_load"], float("nan"))
        if not math.isfinite(pv_power):
            return "Live PV telemetry is unavailable"
        if not 0.0 <= pv_power <= 100_000.0:
            return "Live PV telemetry is outside 0-100 kW"
        if not math.isfinite(load_power):
            return "Live household-load telemetry is unavailable"
        if not 0.0 <= load_power <= 100_000.0:
            return "Live household-load telemetry is outside 0-100 kW"

        if health is None:
            return "Actuation telemetry freshness is unavailable"
        freshness = (
            ("SAJ SOC-source heartbeat", health.soc_source_heartbeat_age_seconds),
            ("Live PV telemetry", health.pv_age_seconds),
            ("Live household-load telemetry", health.load_age_seconds),
        )
        for label, age_seconds in freshness:
            if age_seconds is None or not math.isfinite(age_seconds):
                return f"{label} freshness is unavailable"
            if age_seconds > self.settings.fast_dispatch_state_max_age_seconds:
                return f"{label} is stale ({age_seconds:.0f}s old)"
        return None

    def _solar_potential_context(
        self,
        states: dict[str, dict[str, Any]],
        now: datetime,
    ) -> tuple[float, float, float, float, str]:
        """Return potential, actual, curtailed estimate, correction, and source.

        The two local expected-power entities are derived independently from
        measured irradiance projected onto the 9-degree north and 171-degree
        south roof planes.  They remain meaningful when the inverter has been
        asked to curtail and are therefore safer than actual PV for cloud-now
        correction and learning during those periods.
        """
        expected_entities = (
            ENTITY["solar_expected_north"],
            ENTITY["solar_expected_south"],
        )

        def fresh_watts(entity_id: str) -> float | None:
            entity = states.get(entity_id, {})
            value = numeric_state(states, entity_id, float("nan"))
            timestamp = parse_datetime(
                entity.get("last_reported")
                or entity.get("last_updated")
                or entity.get("last_changed"),
                self.timezone,
            )
            if not math.isfinite(value) or value < 0 or timestamp is None:
                return None
            age = (now - timestamp.astimezone(self.timezone)).total_seconds()
            if age < -60 or age > self.settings.fast_dispatch_state_max_age_seconds:
                return None
            return value

        components = [fresh_watts(entity_id) for entity_id in expected_entities]
        actual_w = numeric_state(states, ENTITY["pv_power"], 0.0)
        actual_kw = max(0.0, actual_w / 1000) if math.isfinite(actual_w) else 0.0
        if any(value is None for value in components):
            return actual_kw, actual_kw, 0.0, 1.0, "actual_fallback"

        potential_kw = sum(float(value) for value in components) / 1000
        solcast_now_w = numeric_state(states, ENTITY["solcast_power_now"], float("nan"))
        if math.isfinite(solcast_now_w) and solcast_now_w >= 250 and potential_kw >= 0.1:
            correction = min(1.65, max(0.35, potential_kw / (solcast_now_w / 1000)))
        else:
            correction = 1.0

        fit = numeric_state(states, ENTITY["amber_fit"], 0.0)
        export_disabled = (
            ENTITY["export_enabled"] in states
            and not state_is_on(states, ENTITY["export_enabled"])
        )
        curtailment_likely = (
            potential_kw > actual_kw + 0.3
            and (export_disabled or fit <= 0.0)
        )
        curtailed_kw = max(0.0, potential_kw - actual_kw) if curtailment_likely else 0.0
        return potential_kw, actual_kw, curtailed_kw, correction, "local_two_plane_poa"

    def _update_learning(
        self,
        states: dict[str, dict[str, Any]],
        now: datetime,
        solar_context: tuple[float, float, float, float, str],
    ) -> None:
        home = numeric_state(states, ENTITY["home_load"], 1670.0) / 1000
        hot_water = numeric_state(states, ENTITY["hot_water_power"], 0.0)
        ev = numeric_state(states, ENTITY["ev_power"], 0.0)
        base = max(0.2, home - max(0.0, hot_water) - max(0.0, ev))
        self.learning.update_load(now, base)
        today = states.get(ENTITY["solcast_today"], {})
        forecast = numeric_state({ENTITY["solcast_today"]: today}, ENTITY["solcast_today"], 0.0)
        actual = numeric_state(states, ENTITY["pv_energy_today"], 0.0)
        date_key = now.date().isoformat()
        self.learning.observe_solar_day(date_key, forecast, actual)
        potential_kw, actual_kw, curtailed_kw, _, source = solar_context
        if source == "local_two_plane_poa":
            self.learning.observe_solar_power(
                now,
                actual_kw=actual_kw,
                potential_kw=potential_kw,
                curtailed=curtailed_kw > 0,
            )
        self.learning.finalize_previous_days(date_key)
        self.learning.save()

    @staticmethod
    def _detect_crossovers(slots: list[Slot], now: datetime) -> tuple[datetime | None, datetime | None]:
        morning = None
        evening = None
        for index in range(len(slots) - 1):
            slot = slots[index]
            following = slots[index + 1]
            local_hour = slot.start.hour + slot.start.minute / 60
            above = slot.solar_kw >= slot.load_kw + 0.3 and following.solar_kw >= following.load_kw + 0.3
            below = slot.solar_kw < slot.load_kw and following.solar_kw < following.load_kw
            if morning is None and slot.start >= now and 5 <= local_hour <= 10.5 and above:
                morning = slot.start
            if evening is None and slot.start >= now and 13 <= local_hour <= 20 and below:
                earlier_above = any(item.solar_kw >= item.load_kw + 0.3 for item in slots[max(0, index - 10):index])
                if earlier_above:
                    evening = slot.start
        return morning, evening

    def _schedule_hot_water(
        self,
        slots: list[Slot],
        states: dict[str, dict[str, Any]],
        now: datetime,
        evening: datetime | None,
    ) -> None:
        runtime = numeric_state(states, ENTITY["hot_water_runtime"], 0.0)
        required_h = max(0.0, self.settings.hot_water_required_hours - runtime)
        if required_h <= 0:
            return
        latest = datetime.combine(now.date(), time(self.settings.hot_water_latest_hour), self.timezone)
        if evening and evening.date() == now.date():
            latest = min(latest, evening)
        candidates = [
            slot for slot in slots
            if slot.start.date() == now.date()
            and slot.start + timedelta(hours=slot.duration_h) > now
            and slot.start + timedelta(hours=slot.duration_h) <= latest
        ]
        if not candidates:
            return

        # Build indivisible, contiguous blocks of at least 15 minutes.  The
        # near-term Amber grid contains five-minute slots, but the element must
        # not chatter just because a single settlement interval is attractive.
        blocks: list[list[Slot]] = []
        current_block: list[Slot] = []
        current_duration_h = 0.0
        expected_start: datetime | None = None
        for slot in sorted(candidates, key=lambda item: item.start):
            if expected_start and abs((slot.start - expected_start).total_seconds()) > 1:
                if current_block:
                    if current_duration_h + 1e-9 >= 0.25 or not blocks:
                        blocks.append(current_block)
                    else:
                        blocks[-1].extend(current_block)
                current_block = []
                current_duration_h = 0.0
            current_block.append(slot)
            current_duration_h += slot.duration_h
            expected_start = slot.start + timedelta(hours=slot.duration_h)
            if current_duration_h + 1e-9 >= 0.25:
                blocks.append(current_block)
                current_block = []
                current_duration_h = 0.0
                expected_start = None
        if current_block:
            if blocks:
                blocks[-1].extend(current_block)
            elif current_duration_h + 1e-9 >= 0.25:
                blocks.append(current_block)

        def opportunity_cost(block: list[Slot]) -> tuple[float, datetime]:
            duration_h = sum(slot.duration_h for slot in block)
            weighted_cost = 0.0
            for slot in block:
                solar_surplus = slot.solar_low_kw - slot.load_kw
                price = (
                    max(0.0, slot.export_price)
                    if solar_surplus >= self.settings.hot_water_kw
                    else slot.import_price
                )
                weighted_cost += price * slot.duration_h
            return weighted_cost / max(duration_h, 1e-9), block[0].start

        scheduled_h = 0.0
        for block in sorted(blocks, key=opportunity_cost):
            for slot in block:
                slot.hot_water_kw = self.settings.hot_water_kw
                scheduled_h += slot.duration_h
            if scheduled_h + 1e-9 >= required_h:
                break

    def _departure(self, states: dict[str, dict[str, Any]], now: datetime) -> datetime:
        raw = states.get(ENTITY["ev_departure"], {}).get("state")
        parsed = parse_datetime(raw, self.timezone)
        if parsed and parsed > now:
            return parsed
        departure = datetime.combine(now.date(), time(self.settings.ev_default_departure_hour), self.timezone)
        if departure <= now:
            departure += timedelta(days=1)
        return departure

    def _schedule_ev(
        self,
        slots: list[Slot],
        states: dict[str, dict[str, Any]],
        now: datetime,
        battery_soc_pct: float = 50.0,
        battery_capacity_kwh: float = 47.0,
        evening: datetime | None = None,
    ) -> _EVSchedule:
        selection = str(states.get(ENTITY["ev_trip"], {}).get("state", "Unanswered")).lower()
        distances = {"no trip": 0.0, "local / 50 km": 50.0, "100 km": 100.0, "200 km": 200.0}
        if "custom" in selection:
            distance = numeric_state(states, ENTITY["ev_custom_km"], 0.0)
        else:
            distance = distances.get(selection, 0.0)
        explicit_trip_required = (
            selection in {"local / 50 km", "100 km", "200 km"}
            or ("custom" in selection and distance > 0)
        )
        trip_energy = distance * self.settings.ev_kwh_per_km * self.settings.ev_trip_margin
        configured_limit = numeric_state(
            states,
            ENTITY["ev_charge_limit"],
            numeric_state(states, ENTITY["ev_limit"], 80.0),
        )
        configured_limit = min(100.0, max(40.0, configured_limit))
        opportunistic_only = "unanswered" in selection
        target = max(
            self.settings.ev_minimum_departure_soc_pct,
            self.settings.ev_arrival_reserve_pct + 100 * trip_energy / self.settings.ev_usable_capacity_kwh,
        )
        target = min(target, configured_limit)
        if opportunistic_only:
            # There is no declared trip requirement, but the car may absorb
            # otherwise-low-value solar all the way to its editable limit.
            target = configured_limit
        current = numeric_state(states, ENTITY["ev_soc"], target)
        required = max(0.0, (target - current) / 100 * self.settings.ev_usable_capacity_kwh / 0.90)
        departure = self._departure(states, now)
        connected = state_is_on(states, ENTITY["ev_plugged"]) and state_is_on(states, ENTITY["ev_home"])
        candidates = [
            slot for slot in slots
            if slot.start < departure
            and slot.start + timedelta(hours=slot.duration_h) > now
        ]
        planned_energy: dict[int, float] = {}
        planned_amps: dict[int, int] = {}
        planned_source: dict[int, str] = {}
        estimated_cost = 0.0
        solar_energy = 0.0
        fallback_energy = 0.0
        remaining = required

        # Tranche one is strictly direct solar.  Its commanded three-phase
        # power can never exceed the calibrated low-solar surplus after house
        # load and hot water, so the battery or grid cannot silently make up a
        # shortfall.  Signed FIT is deliberately used for ordering: consuming
        # solar during the most-negative FIT periods is preferred first.
        solar_candidates: list[tuple[Slot, int]] = []
        battery_energy = battery_capacity_kwh * battery_soc_pct / 100
        full_energy = battery_capacity_kwh * self.settings.battery_evening_target_soc_pct / 100
        for slot in candidates:
            surplus_kw = max(0.0, slot.solar_low_kw - slot.load_kw - slot.hot_water_kw)
            if opportunistic_only:
                if slot.export_price > self.settings.ev_opportunistic_fit_max:
                    continue
                refill_deadline = evening or (slot.start + timedelta(hours=8))
                future_surplus = sum(
                    max(0.0, later.solar_low_kw - later.load_kw - later.hot_water_kw)
                    * later.duration_h * self.settings.battery_charge_efficiency
                    for later in slots
                    if slot.start < later.start < refill_deadline
                )
                # Do not divert solar if the remaining conservative forecast
                # cannot refill the house battery by evening.
                if future_surplus + 1e-6 < max(0.0, full_energy - battery_energy):
                    continue
            available_amps = self._ev_amps_for_power(surplus_kw, round_up=False)
            if available_amps >= self.settings.ev_min_charge_amps:
                solar_candidates.append((slot, available_amps))

        for slot, available_amps in sorted(
            solar_candidates,
            key=lambda item: (item[0].export_price, item[0].start),
        ):
            if remaining <= 1e-9:
                break
            index = id(slot)
            maximum_power = self._ev_power_for_amps(available_amps)
            desired_power = min(maximum_power, remaining / slot.duration_h)
            amps = max(
                self.settings.ev_min_charge_amps,
                min(available_amps, self._ev_amps_for_power(desired_power, round_up=True)),
            )
            commanded_power = self._ev_power_for_amps(amps)
            # The optimiser replans every five minutes, so a partial final block
            # can stop early even though the instantaneous command stays at the
            # production-safe minimum current.
            allocated = min(remaining, commanded_power * slot.duration_h)
            planned_energy[index] = allocated
            planned_amps[index] = amps
            planned_source[index] = "direct_solar"
            solar_energy += allocated
            estimated_cost += allocated * max(0.0, slot.export_price)
            remaining -= allocated

        # Only a deadline shortfall after exhausting all conservative direct
        # solar capacity may enter this tranche.  These slots can use grid (or
        # retained battery value) and are therefore labelled explicitly rather
        # than being presented as solar charging.
        # An unanswered prompt or an explicit "No trip" response is never a
        # departure mandate.  It may use genuine direct-solar surplus to reach
        # the advisory minimum SOC, but it must not start a grid/deadline block
        # that can displace valuable home-battery export.  Only a declared trip
        # authorises the fallback tranche.
        if remaining > 1e-9 and explicit_trip_required:
            for slot in sorted(candidates, key=lambda item: (item.import_price, item.start)):
                if remaining <= 1e-9:
                    break
                index = id(slot)
                existing = planned_energy.get(index, 0.0)
                capacity = max(
                    0.0,
                    self._ev_power_for_amps(self.settings.ev_max_charge_amps)
                    * slot.duration_h
                    - existing,
                )
                allocated = min(remaining, capacity)
                if allocated <= 1e-9:
                    continue
                total_energy = existing + allocated
                total_average_power = total_energy / slot.duration_h
                amps = min(
                    self.settings.ev_max_charge_amps,
                    max(
                        self.settings.ev_min_charge_amps,
                        self._ev_amps_for_power(total_average_power, round_up=True),
                    ),
                )
                planned_energy[index] = total_energy
                planned_amps[index] = amps
                planned_source[index] = "mixed" if existing > 0 else "deadline_fallback"
                fallback_energy += allocated
                estimated_cost += allocated * slot.import_price
                remaining -= allocated

        selected_slots = [slot for slot in candidates if planned_energy.get(id(slot), 0.0) > 1e-9]
        if connected:
            for slot in selected_slots:
                index = id(slot)
                slot.ev_charge_amps = planned_amps[index]
                slot.ev_power_target_kw = self._ev_power_for_amps(slot.ev_charge_amps)
                # Dispatch must model the instantaneous power that the actuator
                # will actually request, not a lower block-average for a partial
                # final charge.  This keeps direct-solar slots conservative and
                # prevents the battery plan from spending phantom surplus.
                slot.ev_kw = slot.ev_power_target_kw
                slot.ev_charge_source = planned_source[index]
        if "unanswered" in selection:
            action = "prompt_trip"
        elif required <= 0:
            action = "ready"
        else:
            action = "recommend_charge"
        selected_times = sorted(item.start for item in selected_slots)
        charge_start = selected_times[0] if selected_times else None
        charge_end = max(
            (item.start + timedelta(hours=item.duration_h) for item in selected_slots),
            default=None,
        )
        return _EVSchedule(
            target_soc_pct=target,
            required_kwh=required,
            action=action,
            charge_start=charge_start,
            charge_end=charge_end,
            estimated_cost=estimated_cost,
            solar_energy_kwh=solar_energy,
            fallback_energy_kwh=fallback_energy,
        )

    def _ev_power_for_amps(self, amps: int) -> float:
        """Return measured-style three-phase input power for a current setting."""
        clamped = max(0, min(self.settings.ev_max_charge_amps, int(amps)))
        phase_power = (
            clamped
            * self.settings.ev_phase_count
            * self.settings.ev_phase_voltage_v
            / 1000
        )
        return min(self.settings.ev_max_charge_kw, phase_power)

    def _ev_amps_for_power(self, power_kw: float, *, round_up: bool) -> int:
        """Convert three-phase power to the integer current accepted by Tesla BLE."""
        kw_per_amp = (
            self.settings.ev_phase_count
            * self.settings.ev_phase_voltage_v
            / 1000
        )
        if power_kw <= 0 or kw_per_amp <= 0:
            return 0
        raw = min(self.settings.ev_max_charge_kw, power_kw) / kw_per_amp
        amps = math.ceil(raw - 1e-9) if round_up else math.floor(raw + 1e-9)
        return max(0, min(self.settings.ev_max_charge_amps, amps))

    def _dispatch(
        self,
        slots: list[Slot],
        initial_soc_pct: float,
        capacity_kwh: float,
        evening: datetime | None,
        morning: datetime | None = None,
    ) -> list[DispatchInterval]:
        step = 0.25
        min_energy = capacity_kwh * self.settings.battery_min_soc_pct / 100
        max_energy = capacity_kwh
        energy_levels = [min_energy + index * step for index in range(int((max_energy - min_energy) // step) + 1)]
        if max_energy - energy_levels[-1] > 1e-6:
            energy_levels.append(max_energy)
        level_count = len(energy_levels)

        def energy(level: int) -> float:
            return energy_levels[level]

        initial_energy = min(max_energy, max(min_energy, capacity_kwh * initial_soc_pct / 100))
        insertion = bisect_left(energy_levels, initial_energy)
        candidates = [index for index in {max(0, insertion - 1), min(level_count - 1, insertion)}]
        initial_level = min(candidates, key=lambda index: abs(energy_levels[index] - initial_energy))
        costs: dict[int, float] = {initial_level: 0.0}
        parents: list[dict[int, _Transition]] = []
        full_target = capacity_kwh * self.settings.battery_evening_target_soc_pct / 100
        morning_target = capacity_kwh * self.settings.battery_morning_target_soc_pct / 100
        morning_index = None
        if morning:
            morning_index = next((
                i for i, slot in enumerate(slots)
                if slot.start + timedelta(hours=slot.duration_h) >= morning
            ), None)
        evening_index = None
        if evening:
            evening_index = next((i for i, slot in enumerate(slots) if slot.start + timedelta(hours=slot.duration_h) >= evening), None)
        low_surplus = 0.0
        if evening_index is not None:
            low_surplus = sum(
                max(0.0, slot.solar_low_kw - slot.load_kw - slot.hot_water_kw - slot.ev_kw)
                * slot.duration_h * self.settings.battery_charge_efficiency
                for slot in slots[: evening_index + 1]
            )
        morning_target_feasible = False
        post_morning_surplus = 0.0
        if morning_index is not None:
            valuable_stored_kwh = 0.0
            for slot in slots[: morning_index + 1]:
                household_output_kw = (
                    slot.load_kw if slot.import_price > self.settings.battery_wear_per_kwh else 0.0
                )
                export_output_kw = 0.0
                if slot.export_price > (
                    self.settings.battery_wear_per_kwh
                    + self.settings.grid_charge_uncertainty_per_kwh
                ):
                    export_output_kw = max(
                        0.0,
                        self.settings.battery_max_discharge_kw - household_output_kw,
                    )
                valuable_stored_kwh += (
                    household_output_kw + export_output_kw
                ) * slot.duration_h / self.settings.battery_discharge_efficiency
            if evening_index is not None and evening_index > morning_index:
                post_morning_surplus = sum(
                    max(0.0, slot.solar_low_kw - slot.load_kw - slot.hot_water_kw - slot.ev_kw)
                    * slot.duration_h * self.settings.battery_charge_efficiency
                    for slot in slots[morning_index + 1 : evening_index + 1]
                )
            best_pre_morning_value = max(
                (max(slot.import_price, slot.export_price) for slot in slots[: morning_index + 1]),
                default=0.0,
            )
            best_later_value = max(
                (max(slot.import_price, slot.export_price) for slot in slots[morning_index + 1 :]),
                default=0.0,
            )
            can_refill_conservatively = morning_target + post_morning_surplus >= full_target
            exceptional_early_value = best_pre_morning_value > (
                best_later_value
                + self.settings.battery_wear_per_kwh
                + self.settings.grid_charge_uncertainty_per_kwh
            )
            morning_target_feasible = (
                valuable_stored_kwh + step >= max(0.0, initial_energy - morning_target)
                and (can_refill_conservatively or exceptional_early_value)
            )
        full_feasible = evening_index is not None and (
            (morning_target + post_morning_surplus >= full_target)
            if morning_target_feasible
            else (initial_energy + low_surplus >= full_target)
        )

        for index, slot in enumerate(slots):
            next_costs: dict[int, float] = {}
            next_parents: dict[int, _Transition] = {}
            max_charge_delta = self.settings.battery_max_charge_kw * slot.duration_h * self.settings.battery_charge_efficiency
            max_discharge_delta = self.settings.battery_max_discharge_kw * slot.duration_h / self.settings.battery_discharge_efficiency
            for previous_level, previous_cost in costs.items():
                previous_energy = energy(previous_level)
                first_level = bisect_left(energy_levels, previous_energy - max_discharge_delta - 1e-9)
                last_level = bisect_right(energy_levels, previous_energy + max_charge_delta + 1e-9) - 1
                for level in range(first_level, last_level + 1):
                    next_energy = energy(level)
                    if (
                        morning_target_feasible
                        and index == morning_index
                        and next_energy > morning_target + step + 1e-6
                    ):
                        continue
                    if full_feasible and index == evening_index and next_energy + 1e-6 < full_target:
                        continue
                    delta = next_energy - previous_energy
                    # Deadline fallback is the explicit-trip exception to the
                    # normal solar-only EV policy.  Even then, never discharge
                    # the stationary battery into that flexible load: the
                    # shortfall must be supplied by solar/grid.  Direct-solar
                    # EV slots may still coincide with profitable battery
                    # export because their EV power was capped to conservative
                    # surplus before dispatch.
                    if (
                        slot.ev_charge_source in {"deadline_fallback", "mixed"}
                        and delta < -1e-9
                    ):
                        continue
                    charge_input = max(0.0, delta) / self.settings.battery_charge_efficiency
                    discharge_output = max(0.0, -delta) * self.settings.battery_discharge_efficiency
                    base_grid = (slot.load_kw + slot.hot_water_kw + slot.ev_kw - slot.solar_kw) * slot.duration_h
                    grid = base_grid + charge_input - discharge_output
                    imported = max(0.0, grid)
                    potential_export = max(0.0, -grid)
                    curtailed = potential_export if slot.export_price < 0 else 0.0
                    exported = potential_export - curtailed
                    metered_grid = imported - exported
                    imported_for_battery = max(0.0, imported - max(0.0, base_grid))
                    wear = discharge_output * self.settings.battery_wear_per_kwh
                    interval_cost = (
                        imported * slot.import_price
                        - exported * slot.export_price
                        + wear
                        + imported_for_battery * self.settings.grid_charge_uncertainty_per_kwh
                    )
                    candidate = previous_cost + interval_cost
                    if candidate >= next_costs.get(level, float("inf")):
                        continue
                    battery_kw = (discharge_output - charge_input) / slot.duration_h
                    next_costs[level] = candidate
                    next_parents[level] = _Transition(
                        previous_level=previous_level,
                        battery_kw=battery_kw,
                        grid_kwh=metered_grid,
                        interval_cost=interval_cost,
                        revenue=exported * slot.export_price,
                        wear_cost=wear,
                        curtailed_kwh=curtailed,
                    )
            if not next_costs:
                raise RuntimeError(f"No feasible battery state at slot {index}")
            costs = next_costs
            parents.append(next_parents)

        # End the rolling horizon with only the energy needed to reach the next
        # solar takeover. Valuing every terminal kWh at the highest price seen
        # anywhere in the horizon caused a false tail: the model imported cheap
        # power on the second night while preserving an 80%+ battery for value
        # beyond the 36-hour window. The next five-minute plan would never
        # actually make that trade, but it made the published forecast misleading.
        horizon_end = slots[-1].start + timedelta(hours=slots[-1].duration_h)
        horizon_hours = (horizon_end - slots[0].start).total_seconds() / 3600
        if horizon_hours >= 24:
            takeover_clock = morning.timetz().replace(tzinfo=None) if morning else time(7, 0)
            terminal_takeover = datetime.combine(horizon_end.date(), takeover_clock, self.timezone)
            if terminal_takeover <= horizon_end:
                terminal_takeover += timedelta(days=1)
            tail_slots = slots[-min(6, len(slots)):]
            tail_deficit_kw = sum(
                max(0.0, slot.load_kw + slot.hot_water_kw + slot.ev_kw - slot.solar_low_kw)
                for slot in tail_slots
            ) / len(tail_slots)
            terminal_gap_h = max(0.0, (terminal_takeover - horizon_end).total_seconds() / 3600)
            terminal_reserve = min(
                max_energy,
                morning_target
                + tail_deficit_kw * terminal_gap_h / self.settings.battery_discharge_efficiency,
            )
            terminal_levels = [
                level for level in costs
                if energy(level) + step >= terminal_reserve
            ]
            final_level = min(terminal_levels or list(costs), key=costs.__getitem__)
        else:
            maximum_import = max((slot.import_price for slot in slots), default=0.20)
            terminal_value = max(
                0.0,
                min(0.30, maximum_import) - self.settings.battery_wear_per_kwh,
            ) * self.settings.battery_discharge_efficiency
            final_level = min(
                costs,
                key=lambda level: costs[level] - energy(level) * terminal_value,
            )
        levels = [final_level]
        transitions: list[_Transition] = []
        for index in range(len(slots) - 1, -1, -1):
            transition = parents[index][levels[-1]]
            transitions.append(transition)
            levels.append(transition.previous_level)
        transitions.reverse()
        levels.reverse()

        result: list[DispatchInterval] = []
        for index, (slot, transition) in enumerate(zip(slots, transitions)):
            start_energy = energy(levels[index])
            end_energy = energy(levels[index + 1])
            result.append(DispatchInterval(
                start=slot.start,
                duration_minutes=round(slot.duration_h * 60, 3),
                solar_kw=round(slot.solar_kw, 3),
                solar_low_kw=round(slot.solar_low_kw, 3),
                load_kw=round(slot.load_kw, 3),
                hot_water_kw=round(slot.hot_water_kw, 3),
                ev_kw=round(slot.ev_kw, 3),
                import_price=round(slot.import_price, 5),
                export_price=round(slot.export_price, 5),
                battery_kw=round(transition.battery_kw, 3),
                site_grid_kw=round(transition.grid_kwh / slot.duration_h, 3),
                pv_curtailment_kw=round(transition.curtailed_kwh / slot.duration_h, 3),
                soc_start_pct=round(100 * start_energy / capacity_kwh, 1),
                soc_end_pct=round(100 * end_energy / capacity_kwh, 1),
                cost=round(transition.interval_cost, 4),
                price_source=slot.price_source,
            ))
        return result
