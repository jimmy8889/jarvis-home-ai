from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, time, timedelta
from bisect import bisect_left, bisect_right
import hashlib
import json
import math
from typing import Any
from zoneinfo import ZoneInfo

from .config import ENTITY, Settings
from . import __version__
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
    mandatory: bool = False
    unmet_kwh: float = 0.0


class EnergyOptimizer:
    def __init__(self, settings: Settings, learning: LearningState):
        self.settings = settings
        self.learning = learning
        self.timezone = ZoneInfo(settings.timezone)
        self._hot_water_commit_date: Any | None = None
        self._hot_water_commit_start: datetime | None = None
        self._hot_water_commit_end: datetime | None = None

    @staticmethod
    def _raw_source_timestamp(entity: dict[str, Any]) -> str | None:
        value = (
            entity.get("last_reported")
            or entity.get("last_updated")
            or entity.get("last_changed")
        )
        return str(value) if value else None

    def _source_timestamps(self, states: dict[str, dict[str, Any]]) -> dict[str, str | None]:
        return {
            key: self._raw_source_timestamp(states.get(ENTITY[key], {}))
            for key in (
                "amber_fit",
                "amber_import",
                "battery_soc",
                "battery_soc_heartbeat",
                "battery_usable",
                "pv_power",
                "pv_heartbeat",
                "home_load",
                "hot_water_runtime",
                "hot_water_power",
                "hot_water_active",
                "ev_power",
                "ev_power_local",
                "ev_charger",
                "ev_soc",
                "ev_charge_limit",
                "ev_plugged",
                "ev_home",
            )
        }

    def _entity_observed_at(
        self,
        states: dict[str, dict[str, Any]],
        entity_id: str,
    ) -> datetime | None:
        return parse_datetime(
            self._raw_source_timestamp(states.get(entity_id, {})),
            self.timezone,
        )

    @staticmethod
    def _power_kw(states: dict[str, dict[str, Any]], entity_id: str, default_kw: float = 0.0) -> float:
        value = numeric_state(states, entity_id, float("nan"))
        if not math.isfinite(value):
            return default_kw
        unit = str(
            states.get(entity_id, {}).get("attributes", {}).get("unit_of_measurement", "")
        ).strip().lower()
        if unit in {"w", "watt", "watts"}:
            return value / 1000
        if unit in {"kw", "kilowatt", "kilowatts"}:
            return value
        # Existing Home Assistant entities are mixed W/kW.  Values above a
        # plausible residential kW reading are safely interpreted as watts.
        return value / 1000 if abs(value) > 100 else value

    def _config_fingerprint(self) -> str:
        payload = {
            key: str(getattr(self.settings, key))
            for key in sorted(self.settings.__dataclass_fields__)
            if key not in {"ha_token_file", "data_dir", "bind_host", "bind_port", "ha_url"}
        }
        return hashlib.sha256(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest()[:16]

    def _sell_price_threshold(
        self,
        states: dict[str, dict[str, Any]],
    ) -> tuple[float, float]:
        """Return configured and economically effective battery sell floors.

        Home Assistant exposes the user-facing helper in cents/kWh.  Solar is
        still exported at every non-negative FIT; this floor applies only to
        energy discharged from the stationary battery.  Wear remains a hard
        lower economic bound even if the dashboard value is set below it.
        """
        fallback_cents = self.settings.battery_min_sell_price_per_kwh * 100
        configured_cents = numeric_state(
            states,
            ENTITY["min_sell_price"],
            fallback_cents,
        )
        if not math.isfinite(configured_cents):
            configured_cents = fallback_cents
        configured = min(2.0, max(0.0, configured_cents / 100))
        effective = max(configured, self.settings.battery_wear_per_kwh)
        return configured, effective

    def _battery_energy_consistency(
        self,
        states: dict[str, dict[str, Any]],
        soc_pct: float,
    ) -> tuple[float | None, bool | None, str | None]:
        stored = numeric_state(states, ENTITY["battery_usable"], float("nan"))
        if not math.isfinite(stored) or stored < 0:
            return None, None, None
        expected = self.settings.battery_capacity_kwh * soc_pct / 100
        tolerance = max(2.0, self.settings.battery_capacity_kwh * 0.08)
        consistent = stored <= self.settings.battery_capacity_kwh + tolerance and abs(stored - expected) <= tolerance
        warning = None
        if not consistent:
            warning = (
                f"Stored-energy telemetry {stored:.1f} kWh is inconsistent with "
                f"{soc_pct:.1f}% of the fixed {self.settings.battery_capacity_kwh:.1f} kWh nominal capacity"
            )
        return stored, consistent, warning

    def _protected_soc(self, intervals: list[DispatchInterval], morning: datetime | None) -> float:
        before_takeover = [
            item.soc_end_pct
            for item in intervals
            if morning is None or item.start < morning
        ]
        return max(
            self.settings.battery_min_soc_pct,
            min(before_takeover, default=self.settings.battery_min_soc_pct),
        )

    def _current_house_reserve_soc(
        self,
        intervals: list[DispatchInterval],
        morning: datetime | None,
        capacity_kwh: float,
    ) -> float:
        """Return the forecast energy that must be retained now for the house.

        Work backwards from the 7% morning target. Conservative future solar
        can reduce the reserve before sunset; forecast ordinary-house deficits
        increase it. EV and hot-water demand are deliberately excluded, so
        neither flexible load can consume the energy needed to reach morning.
        """
        if morning is None or capacity_kwh <= 0:
            return self.settings.battery_morning_target_soc_pct
        relevant = [item for item in intervals if item.start < morning]
        required_kwh = (
            capacity_kwh
            * self.settings.battery_morning_target_soc_pct
            / 100
        )
        for item in reversed(relevant):
            duration_h = max(0.0, item.duration_minutes / 60)
            ordinary_balance_kwh = (
                item.solar_low_kw - item.load_kw
            ) * duration_h
            if ordinary_balance_kwh >= 0:
                required_kwh = max(
                    capacity_kwh * self.settings.battery_min_soc_pct / 100,
                    required_kwh
                    - ordinary_balance_kwh * self.settings.battery_charge_efficiency,
                )
            else:
                required_kwh += (
                    -ordinary_balance_kwh
                    / self.settings.battery_discharge_efficiency
                )
            required_kwh = min(capacity_kwh, required_kwh)
        return min(
            100.0,
            max(
                self.settings.battery_min_soc_pct,
                100 * required_kwh / capacity_kwh,
            ),
        )

    def _slot_house_reserve_soc(
        self,
        slots: list[Slot],
        morning: datetime | None,
        capacity_kwh: float,
    ) -> float:
        """Reserve ordinary-house energy through forecast solar takeover.

        This is calculated before flexible loads are scheduled so neither the
        EV nor hot water can make its own demand appear to be household reserve.
        """
        if morning is None or capacity_kwh <= 0:
            return self.settings.battery_morning_target_soc_pct
        required_kwh = (
            capacity_kwh * self.settings.battery_morning_target_soc_pct / 100
        )
        for slot in reversed([item for item in slots if item.start < morning]):
            ordinary_balance_kwh = (
                slot.solar_low_kw - slot.load_kw
            ) * slot.duration_h
            if ordinary_balance_kwh >= 0:
                required_kwh = max(
                    capacity_kwh * self.settings.battery_min_soc_pct / 100,
                    required_kwh
                    - ordinary_balance_kwh * self.settings.battery_charge_efficiency,
                )
            else:
                required_kwh += (
                    -ordinary_balance_kwh
                    / self.settings.battery_discharge_efficiency
                )
            required_kwh = min(capacity_kwh, required_kwh)
        return min(
            100.0,
            max(
                self.settings.battery_min_soc_pct,
                100 * required_kwh / capacity_kwh,
            ),
        )

    @staticmethod
    def _command_semantic_hash(payload: dict[str, Any]) -> str:
        return hashlib.sha256(
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()[:20]

    @staticmethod
    def _battery_mode(first: DispatchInterval, site_export_kw: float) -> str:
        if first.battery_kw > 0.5:
            return "export" if site_export_kw > 0.5 else "self_consume"
        if first.battery_kw < -0.5:
            return "grid_charge" if first.site_grid_kw > 0.2 else "pv_charge"
        return "hold"

    @staticmethod
    def _source_energy_summary(
        intervals: list[DispatchInterval],
    ) -> dict[str, float]:
        """Attribute forecast energy using solar, battery, then grid priority.

        SAJ household load is separated before dispatch, so the three demand
        columns are mutually exclusive.  Solar is assigned house-first, then
        hot water and EV.  Stationary-battery energy may supply the house and an
        explicitly authorised EV tranche, but never hot water; grid is the
        service-rescue source for any hot-water shortfall.  Any remaining
        solar/battery output is the planned site export.
        """
        totals = {
            "hot_water_solar_energy_kwh": 0.0,
            "hot_water_battery_energy_kwh": 0.0,
            "hot_water_grid_energy_kwh": 0.0,
            "ev_solar_energy_kwh": 0.0,
            "ev_battery_energy_kwh": 0.0,
            "ev_grid_energy_kwh": 0.0,
            "house_total_energy_kwh": 0.0,
            "house_solar_energy_kwh": 0.0,
            "house_battery_energy_kwh": 0.0,
            "house_grid_energy_kwh": 0.0,
            "battery_export_energy_kwh": 0.0,
            "solar_export_energy_kwh": 0.0,
            "total_export_energy_kwh": 0.0,
        }
        for item in intervals:
            duration_h = max(item.duration_minutes / 60, 0.0)
            remaining_solar = max(0.0, item.solar_kw)
            remaining_battery = max(0.0, item.battery_kw)
            demands = {
                "house": max(0.0, item.load_kw),
                "hot_water": max(0.0, item.hot_water_kw),
                "ev": max(0.0, item.ev_kw),
            }
            remaining_demand: dict[str, float] = {}
            for category in ("house", "hot_water", "ev"):
                demand_kw = demands[category]
                solar_kw = min(demand_kw, remaining_solar)
                remaining_solar -= solar_kw
                remaining_demand[category] = demand_kw - solar_kw
                totals[f"{category}_solar_energy_kwh"] += solar_kw * duration_h
                if category == "house":
                    totals["house_total_energy_kwh"] += demand_kw * duration_h

            battery_allocations = {"house": 0.0, "hot_water": 0.0, "ev": 0.0}
            for category in ("house", "ev"):
                battery_kw = min(remaining_demand[category], remaining_battery)
                remaining_battery -= battery_kw
                remaining_demand[category] -= battery_kw
                battery_allocations[category] = battery_kw

            for category in ("house", "hot_water", "ev"):
                battery_kw = battery_allocations[category]
                grid_kw = remaining_demand[category]
                totals[f"{category}_battery_energy_kwh"] += battery_kw * duration_h
                totals[f"{category}_grid_energy_kwh"] += grid_kw * duration_h

            # Charging consumes solar left after all site demand before any
            # export can be attributed.  A grid-charged battery therefore does
            # not incorrectly reduce forecast solar export.
            if item.battery_kw < 0:
                remaining_solar = max(0.0, remaining_solar + item.battery_kw)
            exported_kw = max(0.0, -item.site_grid_kw)
            solar_export_kw = min(exported_kw, remaining_solar)
            battery_export_kw = min(
                max(0.0, exported_kw - solar_export_kw),
                remaining_battery,
            )
            totals["solar_export_energy_kwh"] += solar_export_kw * duration_h
            totals["battery_export_energy_kwh"] += battery_export_kw * duration_h
            totals["total_export_energy_kwh"] += exported_kw * duration_h
        return totals

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
        capacity = self.settings.battery_capacity_kwh
        house_reserve_soc = self._slot_house_reserve_soc(slots, morning, capacity)
        stored_energy, energy_consistent, energy_warning = self._battery_energy_consistency(
            states,
            soc,
        )
        minimum_sell_price, effective_sell_price = self._sell_price_threshold(states)
        self._schedule_hot_water(slots, states, now, evening)
        self._stabilize_hot_water_schedule(slots, states, now)
        ev = self._schedule_ev(
            slots,
            states,
            now,
            soc,
            capacity,
            evening,
            house_reserve_soc,
        )
        intervals = self._dispatch(
            slots,
            soc,
            capacity,
            evening,
            morning,
            minimum_sell_price=effective_sell_price,
        )
        hot_water_required_today = max(
            0.0,
            self.settings.hot_water_required_hours
            - numeric_state(states, ENTITY["hot_water_runtime"], 0.0),
        )
        hot_water_scheduled_today = sum(
            item.duration_minutes / 60
            for item in intervals
            if item.start.date() == now.date() and item.hot_water_kw > 0
        )
        hot_water_unmet_today = max(
            0.0,
            hot_water_required_today - hot_water_scheduled_today,
        )

        first = intervals[0]
        site_export = max(0.0, -first.site_grid_kw)
        negative_fit = first.export_price < 0
        if negative_fit:
            action = "zero_export_solar_priority"
            reason = (
                f"Negative FIT ${first.export_price:.3f}/kWh: use solar for "
                "loads and full-rate battery charging, then hold grid export at zero"
            )
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
        if energy_warning:
            warnings.append(energy_warning)
        if hot_water_unmet_today > 1e-6:
            warnings.append(
                f"Hot-water plan is {hot_water_unmet_today:.2f} service-hours short today"
            )
        if ev.action == "telemetry_unavailable":
            warnings.append("EV SOC is unavailable; automatic EV charging is disabled")
        elif ev.mandatory and ev.unmet_kwh > 1e-6:
            warnings.append(
                f"Declared EV requirement is {ev.unmet_kwh:.1f} kWh short before departure"
            )
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
        source_energy = self._source_energy_summary(intervals)
        active_pair = active_price_pair(
            fit_entity,
            import_entity,
            now,
            self.timezone,
            self.settings.amber_interval_minutes,
        )
        active_fit, active_import = active_pair if active_pair else (None, None)
        battery_mode = self._battery_mode(first, site_export)
        protected_soc = max(
            self._protected_soc(intervals, morning),
            self._current_house_reserve_soc(intervals, morning, capacity),
            house_reserve_soc,
        )
        battery_power_target_kw = max(
            -self.settings.battery_max_charge_kw,
            min(self.settings.battery_max_discharge_kw, first.battery_kw),
        )
        battery_charge_target_kw = max(0.0, -first.battery_kw)
        battery_discharge_target_kw = max(0.0, first.battery_kw)
        site_export_target_kw = site_export
        if not actuation_allowed:
            # Preserve the economic trajectory in ``intervals`` for shadow
            # analysis, but never publish a stale forced mode or non-zero
            # battery command after any production gate is disarmed.  Node-RED
            # independently rejects ``actuation_allowed=false``; this makes the
            # planner contract itself fail-safe as well.
            battery_mode = "hold"
            battery_power_target_kw = 0.0
            battery_charge_target_kw = 0.0
            battery_discharge_target_kw = 0.0
            site_export_target_kw = 0.0
            if not negative_fit:
                action = "safe_hold"
                reason = "Battery controls are disarmed; forecast dispatch is non-actionable"

        command_semantic_hash = self._command_semantic_hash({
            "battery_mode": battery_mode,
            "battery_charge_target_kw": round(
                battery_charge_target_kw if battery_mode == "grid_charge" else 0.0,
                3,
            ),
            "battery_discharge_target_kw": round(
                battery_discharge_target_kw
                if battery_mode == "export"
                or (
                    battery_mode == "self_consume"
                    and first.hot_water_control_mode == "service_rescue"
                )
                else 0.0,
                3,
            ),
            "site_export_target_kw": round(
                site_export_target_kw if battery_mode == "export" else 0.0,
                3,
            ),
            "pv_export_command": "curtail" if negative_fit else "allow",
            "protected_soc_pct": round(protected_soc, 1),
            "hot_water_control_mode": first.hot_water_control_mode,
            "software_version": __version__,
            "config_fingerprint": self._config_fingerprint(),
        })

        return Plan(
            plan_id=plan_id,
            generated_at=generated,
            valid_until=valid_until,
            mode=mode,
            actuation_allowed=actuation_allowed,
            action=action,
            reason=reason,
            confidence=confidence,
            battery_power_target_kw=battery_power_target_kw,
            site_export_target_kw=site_export_target_kw,
            pv_export_command="curtail" if negative_fit else "allow",
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
            ev_fallback_energy_kwh=ev.fallback_energy_kwh,
            ev_charge_start=ev.charge_start,
            ev_charge_end=ev.charge_end,
            ev_estimated_cost=ev.estimated_cost,
            morning_takeover=morning,
            evening_crossover=evening,
            expected_cost=expected_cost,
            expected_revenue=expected_revenue,
            expected_wear_cost=expected_wear,
            **source_energy,
            minimum_sell_price=minimum_sell_price,
            effective_sell_price=effective_sell_price,
            warnings=warnings,
            intervals=intervals,
            solar_potential_kw=solar_context[0],
            solar_actual_kw=solar_context[1],
            solar_curtailed_estimate_kw=solar_context[2],
            solar_live_correction_factor=solar_context[3],
            solar_potential_source=solar_context[4],
            solar_calibration_report=self.learning.roof_calibration_report,
            hot_water_control_mode=first.hot_water_control_mode,
            hot_water_scheduled_hours=hot_water_scheduled_today,
            hot_water_unmet_hours=max(
                0.0,
                hot_water_unmet_today,
            ),
            battery_mode=battery_mode,
            battery_charge_target_kw=battery_charge_target_kw,
            battery_discharge_target_kw=battery_discharge_target_kw,
            protected_soc_pct=protected_soc,
            battery_capacity_kwh=capacity,
            battery_stored_energy_kwh=stored_energy,
            battery_energy_consistent=energy_consistent,
            ev_mandatory=ev.mandatory,
            ev_grid_allowed=state_is_on(states, ENTITY["ev_allow_grid"]),
            ev_unmet_kwh=ev.unmet_kwh,
            live_fit_price=active_fit[0] if active_fit else None,
            live_import_price=active_import[0] if active_import else None,
            price_interval_start=active_fit[1] if active_fit else None,
            price_interval_end=active_fit[2] if active_fit else None,
            source_timestamps=self._source_timestamps(states),
            software_version=__version__,
            config_fingerprint=self._config_fingerprint(),
            command_semantic_hash=command_semantic_hash,
            house_reserve_soc_pct=house_reserve_soc,
            ev_schedule_amps=slots[0].ev_charge_amps if first.ev_kw > 0 else 0,
            ev_live_target_amps=slots[0].ev_charge_amps if first.ev_kw > 0 else 0,
            ev_source_budget=slots[0].ev_charge_source if first.ev_kw > 0 else "none",
            hot_water_service_target_hours=self.settings.hot_water_service_target_hours,
            hot_water_rescue_source="grid_only",
            dispatch_timestamps={"optimizer_decision_at": generated.isoformat()},
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
        capacity = self.settings.battery_capacity_kwh
        raw_soc = numeric_state(states, ENTITY["battery_soc"], -1.0)
        if not 0.0 <= raw_soc <= 100.0:
            safe_reason = "live battery SOC is unavailable"
            raw_soc = max(self.settings.battery_min_soc_pct, raw_soc)
        stored_energy, energy_consistent, energy_warning = self._battery_energy_consistency(
            states,
            raw_soc,
        )
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
        cached_protected_soc = base_plan.protected_soc_pct
        if (
            not math.isfinite(cached_protected_soc)
            or not self.settings.battery_min_soc_pct <= cached_protected_soc <= 100
        ):
            safe_reason = safe_reason or "cached protected SOC is invalid"
            cached_protected_soc = self.settings.battery_min_soc_pct
        reserve_soc = max(
            self.settings.battery_min_soc_pct,
            cached_protected_soc,
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
        hard_floor_output_kwh = (
            max(0.0, safe_soc - self.settings.battery_min_soc_pct)
            / 100
            * capacity
            * self.settings.battery_discharge_efficiency
        )
        hard_floor_discharge_kw = min(
            self.settings.battery_max_discharge_kw,
            hard_floor_output_kwh / duration_h,
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
        minimum_sell_price, effective_sell_price = self._sell_price_threshold(states)
        live_pv_kw = max(0.0, live_pv_w / 1000) if math.isfinite(live_pv_w) else 0.0
        live_load_kw = max(0.0, live_load_w / 1000) if math.isfinite(live_load_w) else 0.0
        live_hot_water_kw = max(
            0.0,
            self._power_kw(states, ENTITY["hot_water_power"], 0.0),
        )
        live_ev_kw = max(
            0.0,
            self._power_kw(states, ENTITY["ev_power"], 0.0),
            self._power_kw(states, ENTITY["ev_power_local"], 0.0),
        )
        # SAJ home load already includes active flexible demand.  Separate it
        # before valuing battery self-consumption so a cloud transient cannot
        # make the stationary battery silently carry the EV or hot-water load.
        live_base_load_kw = max(
            0.0,
            live_load_kw - live_hot_water_kw - live_ev_kw,
        )
        stop_nonmandatory_ev = (
            matching.ev_kw > 0
            and not base_plan.ev_mandatory
            and fit > self.settings.ev_opportunistic_fit_max
        )
        target_ev_kw = 0.0 if stop_nonmandatory_ev else matching.ev_kw
        target_hot_water_kw = matching.hot_water_kw
        target_load_kw = live_base_load_kw + target_hot_water_kw + target_ev_kw
        household_deficit_kw = max(0.0, live_base_load_kw - live_pv_kw)
        household_battery_need_kw = max(
            0.0,
            live_base_load_kw - max(0.0, live_pv_kw - target_hot_water_kw),
        )
        ev_battery_need_kw = max(
            0.0,
            live_base_load_kw
            + target_ev_kw
            - max(0.0, live_pv_kw - target_hot_water_kw)
            - household_battery_need_kw,
        )
        ev_battery_authorized = (
            base_plan.ev_mandatory
            and matching.ev_charge_source in {"house_battery", "solar_house_battery"}
        )
        # The house may follow its protected trajectory toward the morning
        # target. EV charging can use only the tranche strictly above today's
        # forecast house reserve.
        house_battery_budget_kw = min(
            hard_floor_discharge_kw,
            household_battery_need_kw,
        )
        ev_battery_budget_kw = (
            min(
                ev_battery_need_kw,
                max(0.0, available_discharge_kw - house_battery_budget_kw),
            )
            if ev_battery_authorized
            else 0.0
        )
        battery_eligible_deficit_kw = (
            house_battery_budget_kw + ev_battery_budget_kw
        )

        battery_kw = 0.0
        site_export_kw = 0.0
        predicted_grid_kw = max(0.0, target_load_kw - live_pv_kw)
        pv_curtailment_kw = 0.0
        action = "safe_hold" if safe_reason else "idle"
        reason = f"Fast safety stop: {safe_reason}" if safe_reason else "Fast live-price refresh"
        pv_export_command = "allow"
        actuation_allowed = gates_allowed and base_plan.actuation_allowed and safe_reason is None
        if safe_reason is None and fit < 0:
            action = "zero_export_solar_priority"
            pv_export_command = "curtail"
            solar_surplus_kw = max(0.0, live_pv_kw - target_load_kw)
            available_charge_kw = min(
                self.settings.battery_max_charge_kw,
                max(0.0, 100.0 - safe_soc)
                / 100
                * capacity
                / self.settings.battery_charge_efficiency
                / duration_h,
            )
            battery_kw = -min(solar_surplus_kw, available_charge_kw)
            raw_grid_kw = target_load_kw - live_pv_kw - battery_kw
            pv_curtailment_kw = max(0.0, -raw_grid_kw)
            predicted_grid_kw = max(0.0, raw_grid_kw)
            reason = (
                f"Negative FIT ${fit:.3f}/kWh: supply loads, charge the battery, "
                "then enforce zero export"
            )
        elif safe_reason is None:
            economically_positive = fit + 1e-9 >= effective_sell_price
            exceptional_export_now = economically_positive and fit >= (
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
                # The full optimiser has already solved battery scarcity over
                # the complete horizon.  Preserve its cached household tranche
                # when the live import price has not materially worsened; using
                # the single highest future allocation as a fresh hurdle here
                # caused a brief grid-import pulse at every Amber rollover even
                # though the following full plan selected self-consumption
                # again.  The configured uncertainty margin bounds how far a
                # fast plan may trust that cached decision.  A larger downward
                # revision still releases the tranche and waits for the full
                # optimiser, while newly invented discharge remains subject to
                # the retained-value test below.
                cached_household_allocation_still_valid = (
                    planned_household_kw > 0
                    and import_price > self.settings.battery_wear_per_kwh
                    and import_price
                    + self.settings.grid_charge_uncertainty_per_kwh
                    >= matching.import_price
                )
                household_value_positive = (
                    cached_household_allocation_still_valid
                    or (
                        import_price > self.settings.battery_wear_per_kwh
                        and import_price >= retained_value
                    )
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
            predicted_grid_kw = target_load_kw - live_pv_kw - battery_kw
            site_export_kw = max(0.0, -predicted_grid_kw)
            if battery_kw > 0.5 and site_export_kw > max(0.5, live_pv_kw - target_load_kw):
                action = "discharge_export"
                reason = (
                    f"Immediate profitable export at live FIT ${fit:.3f}/kWh; "
                    f"minimum sell ${effective_sell_price:.3f}/kWh; "
                    f"preserve {reserve_soc:.1f}% planned reserve"
                )
            elif battery_kw > 0.5:
                action = "self_consumption"
                site_export_kw = 0.0
                reason = f"Immediate household supply at import ${import_price:.3f}/kWh"
            else:
                site_export_kw = max(0.0, live_pv_kw - target_load_kw)
                reason = (
                    f"Live FIT ${fit:.3f}/kWh does not clear the "
                    f"${effective_sell_price:.3f}/kWh battery sell floor or retained value"
                )

        if target_hot_water_kw > 0 and battery_kw > battery_eligible_deficit_kw:
            battery_kw = battery_eligible_deficit_kw
            predicted_grid_kw = max(
                0.0,
                target_load_kw - live_pv_kw - battery_kw,
            )
            site_export_kw = 0.0

        # Import avoidance is a service priority. Ordinary house load follows
        # the protected trajectory; flexible loads never consume its reserved
        # overnight energy.
        if (
            safe_reason is None
            and battery_eligible_deficit_kw > 1e-6
            and battery_kw + 1e-6 < battery_eligible_deficit_kw
        ):
            import_avoidance_kw = battery_eligible_deficit_kw
            battery_kw = max(battery_kw, import_avoidance_kw)
            predicted_grid_kw = max(
                0.0,
                target_load_kw - live_pv_kw - battery_kw,
            )
            site_export_kw = 0.0
            if import_avoidance_kw > 0.5:
                action = "self_consumption"
                reason = "Solar first, then battery; grid is the last-resort supply"
        discharged_kwh = max(0.0, battery_kw) * duration_h
        charged_kwh = max(0.0, -battery_kw) * duration_h
        soc_end = min(
            100.0,
            max(
                self.settings.battery_min_soc_pct,
                safe_soc
                - 100
                * discharged_kwh
                / self.settings.battery_discharge_efficiency
                / capacity
                + 100
                * charged_kwh
                * self.settings.battery_charge_efficiency
                / capacity,
            ),
        )
        fast_interval = replace(
            matching,
            start=now,
            duration_minutes=round(duration_h * 60, 3),
            solar_kw=round(live_pv_kw, 3),
            solar_low_kw=round(live_pv_kw, 3),
            load_kw=round(live_base_load_kw, 3),
            hot_water_kw=round(target_hot_water_kw, 3),
            ev_kw=round(target_ev_kw, 3),
            import_price=round(import_price, 5),
            export_price=round(fit, 5),
            battery_kw=round(battery_kw, 3),
            site_grid_kw=round(predicted_grid_kw, 3),
            pv_curtailment_kw=round(pv_curtailment_kw, 3),
            soc_start_pct=round(safe_soc, 1),
            soc_end_pct=round(soc_end, 1),
            cost=round(
                max(0.0, predicted_grid_kw) * duration_h * import_price
                - max(0.0, -predicted_grid_kw) * duration_h * fit
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
        if energy_warning and energy_warning not in warnings:
            warnings.append(energy_warning)
        if stop_nonmandatory_ev:
            warnings.append(
                f"Paused nonmandatory EV charging immediately at FIT ${fit:.3f}/kWh"
            )
        warnings.append(
            "Fast dispatch from cached horizon; full optimisation pending"
            if safe_reason is None
            else reason
        )
        fast_intervals = [fast_interval, *future_intervals]
        source_energy = self._source_energy_summary(fast_intervals)
        fast_battery_mode = (
            "hold"
            if safe_reason is not None
            else (
                "pv_charge"
                if battery_kw < -0.5
                else "export"
                if action == "discharge_export"
                else "self_consume" if action == "self_consumption" else "hold"
            )
        )
        fast_command_hash = self._command_semantic_hash({
            "battery_mode": fast_battery_mode,
            "battery_charge_target_kw": round(
                max(0.0, -battery_kw)
                if fast_battery_mode == "grid_charge" else 0.0,
                3,
            ),
            "battery_discharge_target_kw": round(
                max(0.0, battery_kw)
                if fast_battery_mode == "export"
                or (
                    fast_battery_mode == "self_consume"
                    and matching.hot_water_control_mode == "service_rescue"
                )
                else 0.0,
                3,
            ),
            "site_export_target_kw": round(
                site_export_kw if fast_battery_mode == "export" else 0.0,
                3,
            ),
            "pv_export_command": pv_export_command,
            "protected_soc_pct": round(reserve_soc, 1),
            "hot_water_control_mode": matching.hot_water_control_mode,
            "software_version": __version__,
            "config_fingerprint": self._config_fingerprint(),
        })
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
            battery_mode=fast_battery_mode,
            battery_power_target_kw=round(battery_kw, 3),
            battery_charge_target_kw=round(max(0.0, -battery_kw), 3),
            battery_discharge_target_kw=round(max(0.0, battery_kw), 3),
            site_export_target_kw=round(site_export_kw, 3),
            protected_soc_pct=round(reserve_soc, 1),
            battery_capacity_kwh=capacity,
            battery_stored_energy_kwh=stored_energy,
            battery_energy_consistent=energy_consistent,
            minimum_sell_price=minimum_sell_price,
            effective_sell_price=effective_sell_price,
            pv_export_command=pv_export_command,
            pv_curtailment_target_kw=round(pv_curtailment_kw, 3),
            hot_water_command="on" if matching.hot_water_kw > 0 else "off",
            hot_water_control_mode=matching.hot_water_control_mode,
            ev_action="opportunity_wait" if stop_nonmandatory_ev else base_plan.ev_action,
            ev_charge_amps_target=(
                0 if stop_nonmandatory_ev else base_plan.ev_charge_amps_target
            ),
            ev_schedule_amps=(
                0 if stop_nonmandatory_ev else base_plan.ev_schedule_amps
            ),
            ev_live_target_amps=(
                0 if stop_nonmandatory_ev else base_plan.ev_live_target_amps
            ),
            ev_power_target_kw=(
                0.0 if stop_nonmandatory_ev else base_plan.ev_power_target_kw
            ),
            ev_charge_source=(
                "none" if stop_nonmandatory_ev else base_plan.ev_charge_source
            ),
            live_fit_price=fit_live[0] if fit_live else None,
            live_import_price=import_live[0] if import_live else None,
            price_interval_start=fit_live[1] if fit_live else None,
            price_interval_end=fit_live[2] if fit_live else None,
            source_timestamps=self._source_timestamps(states),
            software_version=__version__,
            config_fingerprint=self._config_fingerprint(),
            command_semantic_hash=fast_command_hash,
            dispatch_timestamps={"optimizer_decision_at": generated.isoformat()},
            warnings=warnings,
            intervals=fast_intervals,
            **source_energy,
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

        pv_heartbeat = numeric_state(
            states,
            ENTITY["pv_heartbeat"],
            float("nan"),
        )
        if not math.isfinite(pv_heartbeat):
            return "SAJ PV-source heartbeat is unavailable"

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
            (
                "SAJ PV-source heartbeat",
                health.pv_source_heartbeat_age_seconds
                if health.pv_source_heartbeat_age_seconds is not None
                else health.pv_age_seconds,
            ),
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

        corrected_components = [
            float(components[0]) * self.learning.roof_correction(now, "north"),
            float(components[1]) * self.learning.roof_correction(now, "south"),
        ]
        potential_kw = sum(corrected_components) / 1000
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
        home = self._power_kw(states, ENTITY["home_load"], 1.67)
        hot_water = self._power_kw(states, ENTITY["hot_water_power"], 0.0)
        ev = max(
            self._power_kw(states, ENTITY["ev_power"], 0.0),
            self._power_kw(states, ENTITY["ev_power_local"], 0.0),
        )
        base = max(0.2, home - max(0.0, hot_water) - max(0.0, ev))
        load_observed_at = self._entity_observed_at(states, ENTITY["home_load"]) or now
        if load_observed_at.date() == now.date():
            self.learning.update_load(load_observed_at, base)
        today = states.get(ENTITY["solcast_today"], {})
        forecast = numeric_state({ENTITY["solcast_today"]: today}, ENTITY["solcast_today"], 0.0)
        actual = numeric_state(states, ENTITY["pv_energy_today"], 0.0)
        date_key = now.date().isoformat()
        actual_observed_at = self._entity_observed_at(states, ENTITY["pv_energy_today"])
        self.learning.observe_solar_day(
            date_key,
            forecast,
            actual,
            observed_at=actual_observed_at or now,
        )
        potential_kw, actual_kw, curtailed_kw, _, source = solar_context
        if source == "local_two_plane_poa":
            self.learning.observe_solar_power(
                now,
                actual_kw=actual_kw,
                potential_kw=potential_kw,
                curtailed=curtailed_kw > 0,
            )
            fit = numeric_state(states, ENTITY["amber_fit"], float("nan"))
            export_disabled = (
                ENTITY["export_enabled"] in states
                and not state_is_on(states, ENTITY["export_enabled"])
            )
            uncurtailed = math.isfinite(fit) and fit >= 0 and not export_disabled
            expected_north = self._power_kw(
                states,
                ENTITY["solar_expected_north"],
                float("nan"),
            )
            expected_south = self._power_kw(
                states,
                ENTITY["solar_expected_south"],
                float("nan"),
            )
            actual_north = self._power_kw(
                states,
                ENTITY["solar_actual_north"],
                float("nan"),
            )
            actual_south = sum(
                self._power_kw(states, entity_id, float("nan"))
                for entity_id in (
                    ENTITY["solar_actual_south_1"],
                    ENTITY["solar_actual_south_2"],
                )
            )
            self.learning.observe_roof_power(
                now,
                roof="north",
                expected_kw=expected_north,
                actual_kw=actual_north,
                uncurtailed=uncurtailed,
            )
            self.learning.observe_roof_power(
                now,
                roof="south",
                expected_kw=expected_south,
                actual_kw=actual_south,
                uncurtailed=uncurtailed,
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
        thermostat_satisfied = state_is_on(states, ENTITY["hot_water_satisfied"])
        dates = sorted({slot.start.astimezone(self.timezone).date() for slot in slots})
        horizon_end = max(
            slot.start + timedelta(hours=slot.duration_h)
            for slot in slots
        )
        for local_date in dates:
            service_deadline = datetime.combine(
                local_date,
                time(self.settings.hot_water_latest_hour),
                self.timezone,
            )
            # Do not invent an early grid rescue for a trailing date whose 4pm
            # deadline lies beyond this rolling horizon.  The next plans will
            # schedule that day once its full opportunity window is visible.
            if local_date != now.date() and horizon_end < service_deadline:
                continue
            required_h = (
                0.0
                if local_date == now.date() and thermostat_satisfied
                else self.settings.hot_water_service_target_hours
            )
            if local_date == now.date():
                required_h = max(0.0, required_h - runtime)
            if required_h <= 1e-9:
                continue
            latest = service_deadline
            # 4pm remains the target completion time, but it is not permission
            # to skip the service.  If today's confirmed runtime is still short
            # after the target, schedule recovery immediately in the remaining
            # horizon and keep doing so until three physical hours are delivered.
            latest_start = latest - timedelta(hours=required_h)
            force_rescue_now = local_date == now.date() and now >= latest_start and required_h > 0
            if local_date == now.date() and now >= latest and required_h > 0:
                latest = max(
                    slot.start + timedelta(hours=slot.duration_h)
                    for slot in slots
                    if slot.start.date() == local_date
                )
            else:
                daily_evening = self._evening_crossover_for_date(slots, local_date)
                if evening and evening.date() == local_date:
                    daily_evening = evening
                if daily_evening:
                    latest = min(latest, daily_evening)
            candidates = [
                slot
                for slot in slots
                if slot.start.astimezone(self.timezone).date() == local_date
                and slot.start + timedelta(hours=slot.duration_h) > now
                and slot.start + timedelta(hours=slot.duration_h) <= latest
            ]
            if not candidates:
                continue
            self._schedule_hot_water_day(
                candidates,
                required_h,
                latest,
                force_rescue_now=force_rescue_now,
            )

    def _evening_crossover_for_date(
        self,
        slots: list[Slot],
        local_date: Any,
    ) -> datetime | None:
        daily = [slot for slot in slots if slot.start.date() == local_date]
        for index in range(1, len(daily) - 1):
            slot = daily[index]
            if not 13 <= slot.start.hour <= 20:
                continue
            if (
                slot.solar_kw < slot.load_kw
                and daily[index + 1].solar_kw < daily[index + 1].load_kw
                and any(item.solar_kw >= item.load_kw + 0.3 for item in daily[:index])
            ):
                return slot.start
        return None

    def _schedule_hot_water_day(
        self,
        candidates: list[Slot],
        required_h: float,
        latest: datetime,
        *,
        force_rescue_now: bool = False,
    ) -> None:
        """Guarantee service in the lowest-opportunity-cost valid blocks.

        Negative-FIT solar is selected first because consuming it avoids a paid
        export.  Positive-FIT solar is compared with grid import so the element
        can wait for a genuinely cheaper period.  Blocks without enough
        conservative solar are labelled ``service_rescue``; the Home Assistant
        governor then lets grid energy provide the shortfall while the inverter
        reserve continues to protect the stationary battery.
        """

        def blocks_for(items: list[Slot]) -> list[list[Slot]]:
            blocks: list[list[Slot]] = []
            current: list[Slot] = []
            duration_h = 0.0
            expected_start: datetime | None = None
            for slot in sorted(items, key=lambda item: item.start):
                contiguous = (
                    expected_start is None
                    or abs((slot.start - expected_start).total_seconds()) <= 1
                )
                if not contiguous:
                    current = []
                    duration_h = 0.0
                current.append(slot)
                duration_h += slot.duration_h
                expected_start = slot.start + timedelta(hours=slot.duration_h)
                if duration_h + 1e-9 >= 0.25:
                    blocks.append(list(current))
                    current = []
                    duration_h = 0.0
                    expected_start = None
            return blocks

        def opportunity_cost(block: list[Slot]) -> tuple[float, float]:
            cost = 0.0
            duration_h = 0.0
            for slot in block:
                conservative_surplus_kw = max(
                    0.0,
                    slot.solar_low_kw - slot.load_kw,
                )
                solar_to_element_kw = min(
                    self.settings.hot_water_kw,
                    conservative_surplus_kw,
                )
                grid_to_element_kw = self.settings.hot_water_kw - solar_to_element_kw
                cost += (
                    solar_to_element_kw * slot.export_price
                    + grid_to_element_kw * slot.import_price
                ) * slot.duration_h
                duration_h += slot.duration_h
            # For economically equal blocks commit to the earliest safe solar
            # opportunity. Preferring the latest equal block caused every
            # rolling solve to move the visible window forward, and could defer
            # a service that was already safe to begin for no financial gain.
            return cost / max(duration_h, 1e-9), block[0].start.timestamp()

        scheduled_h = 0.0
        selected_ids: set[int] = set()
        all_blocks = blocks_for(candidates)
        solar_blocks = [
            block for block in all_blocks
            if all(
                slot.solar_low_kw - slot.load_kw >= self.settings.hot_water_kw
                for slot in block
            )
        ]
        if force_rescue_now:
            solar_blocks = []
        for block in sorted(solar_blocks, key=opportunity_cost):
            if any(id(slot) in selected_ids for slot in block):
                continue
            for slot in block:
                slot.hot_water_kw = self.settings.hot_water_kw
                slot.hot_water_control_mode = "solar_surplus"
                selected_ids.add(id(slot))
                scheduled_h += slot.duration_h
            if scheduled_h + 1e-9 >= required_h:
                return

        # Grid rescue is the latest feasible remainder, never an early cheap
        # import or battery-assisted alternative to waiting for solar.
        rescue_needed_h = max(0.0, required_h - scheduled_h)
        rescue: list[Slot] = []
        rescue_h = 0.0
        rescue_order = sorted(candidates, key=lambda item: item.start)
        if not force_rescue_now:
            rescue_order.reverse()
        for slot in rescue_order:
            if id(slot) in selected_ids:
                continue
            rescue.append(slot)
            rescue_h += slot.duration_h
            if rescue_h + 1e-9 >= rescue_needed_h:
                break
        for slot in rescue:
            slot.hot_water_kw = self.settings.hot_water_kw
            slot.hot_water_control_mode = "service_rescue"

    def _stabilize_hot_water_schedule(
        self,
        slots: list[Slot],
        states: dict[str, dict[str, Any]],
        now: datetime,
    ) -> None:
        """Commit a near-term hot-water block across rolling full replans.

        Forecast prices and solar can legitimately move the uncommitted part of
        the day. Once the chosen start is within the commitment lead, however,
        sliding the same service five minutes later on every solve creates relay
        chatter and an unusable dashboard. The Home Assistant governor remains
        the physical solar/battery safety authority for this committed block.
        """
        local_date = now.astimezone(self.timezone).date()
        runtime = numeric_state(states, ENTITY["hot_water_runtime"], 0.0)
        complete = (
            state_is_on(states, ENTITY["hot_water_satisfied"])
            or runtime >= self.settings.hot_water_required_hours - 1e-6
        )
        if complete or self._hot_water_commit_date not in {None, local_date}:
            self._hot_water_commit_date = None
            self._hot_water_commit_start = None
            self._hot_water_commit_end = None
        if complete:
            return

        selected = [
            slot
            for slot in slots
            if slot.start.astimezone(self.timezone).date() == local_date
            and slot.hot_water_kw > 0
        ]
        if self._hot_water_commit_start is None:
            if not selected:
                return
            first = min(slot.start for slot in selected)
            if first > now + timedelta(minutes=self.settings.hot_water_commit_lead_minutes):
                return
            self._hot_water_commit_date = local_date
            self._hot_water_commit_start = first.replace(second=0, microsecond=0)
            self._hot_water_commit_end = max(
                slot.start + timedelta(hours=slot.duration_h) for slot in selected
            ).replace(second=0, microsecond=0)
            return

        assert self._hot_water_commit_end is not None
        if now >= self._hot_water_commit_end:
            # The physical governor could not complete this block. Release it so
            # the fresh schedule can choose the next solar-only recovery window.
            self._hot_water_commit_date = None
            self._hot_water_commit_start = None
            self._hot_water_commit_end = None
            return

        committed_candidates = [
            slot
            for slot in slots
            if slot.start.astimezone(self.timezone).date() == local_date
            and slot.start < self._hot_water_commit_end
            and slot.start + timedelta(hours=slot.duration_h)
                > max(now, self._hot_water_commit_start)
        ]
        if not committed_candidates:
            return
        for slot in slots:
            if slot.start.astimezone(self.timezone).date() == local_date:
                slot.hot_water_kw = 0.0
                slot.hot_water_control_mode = "off"

        required_h = max(
            0.0,
            self.settings.hot_water_service_target_hours - runtime,
        )
        scheduled_h = 0.0
        for slot in committed_candidates:
            slot.hot_water_kw = self.settings.hot_water_kw
            slot.hot_water_control_mode = (
                "solar_surplus"
                if slot.solar_low_kw - slot.load_kw >= self.settings.hot_water_kw
                else "service_rescue"
            )
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
        house_reserve_soc_pct: float | None = None,
    ) -> _EVSchedule:
        selection = str(states.get(ENTITY["ev_trip"], {}).get("state", "No trip / opportunistic")).lower()
        if selection in {"unanswered", "no trip", "no trip / opportunistic"}:
            selection = "no trip / opportunistic"
        distances = {"no trip": 0.0, "local / 50 km": 50.0, "100 km": 100.0, "200 km": 200.0}
        if "custom" in selection:
            distance = numeric_state(states, ENTITY["ev_custom_km"], 0.0)
        else:
            distance = distances.get(selection, 0.0)
        explicit_trip_required = (
            selection in {"local / 50 km", "100 km", "200 km"}
            or ("custom" in selection and distance > 0)
        )
        allow_grid = state_is_on(states, ENTITY["ev_allow_grid"])
        trip_energy = distance * self.settings.ev_kwh_per_km * self.settings.ev_trip_margin
        configured_limit = numeric_state(
            states,
            ENTITY["ev_charge_limit"],
            numeric_state(states, ENTITY["ev_limit"], 80.0),
        )
        configured_limit = min(100.0, max(40.0, configured_limit))
        opportunistic_only = not explicit_trip_required
        target = max(
            self.settings.ev_minimum_departure_soc_pct,
            self.settings.ev_arrival_reserve_pct + 100 * trip_energy / self.settings.ev_usable_capacity_kwh,
        )
        target = min(target, configured_limit)
        if selection == "no trip / opportunistic":
            # There is no declared trip requirement, but the car may absorb
            # otherwise-low-value solar all the way to its editable limit.
            target = configured_limit
        current = numeric_state(states, ENTITY["ev_soc"], float("nan"))
        if not math.isfinite(current) or not 0.0 <= current <= 100.0:
            return _EVSchedule(
                target_soc_pct=target,
                required_kwh=0.0,
                action="telemetry_unavailable",
                charge_start=None,
                charge_end=None,
                estimated_cost=0.0,
                solar_energy_kwh=0.0,
                fallback_energy_kwh=0.0,
                mandatory=explicit_trip_required,
                unmet_kwh=0.0,
            )
        minimum_reserve_required = max(
            0.0,
            (self.settings.ev_minimum_departure_soc_pct - current)
            / 100
            * self.settings.ev_usable_capacity_kwh
            / 0.90,
        )
        mandatory = explicit_trip_required or minimum_reserve_required > 1e-9
        required = max(0.0, (target - current) / 100 * self.settings.ev_usable_capacity_kwh / 0.90)
        departure = self._departure(states, now)
        connected = state_is_on(states, ENTITY["ev_plugged"]) and state_is_on(states, ENTITY["ev_home"])
        candidates = [
            slot for slot in slots
            if (slot.start < departure or opportunistic_only)
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
        live_expected_pv_kw = self._solar_potential_context(states, now)[0]
        for slot in candidates:
            surplus_kw = max(0.0, slot.solar_low_kw - slot.load_kw - slot.hot_water_kw)
            # The current interval may already be inverter-curtailed during a
            # negative FIT window, so actual PV and even P10 can hide usable
            # production. Grant live opportunistic charging from an attenuated
            # irradiance-derived roof expectation; the HA governor then trims
            # amps from measured battery/grid feedback.
            if (
                slot.export_price < 0
                and slot.start <= now
                < slot.start + timedelta(hours=slot.duration_h)
            ):
                surplus_kw = max(
                    surplus_kw,
                    live_expected_pv_kw * self.settings.ev_expected_pv_attenuation
                    - slot.load_kw
                    - slot.hot_water_kw,
                )
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
            if explicit_trip_required:
                # Solar is not intrinsically free: charging forfeits its FIT.
                # If enough lower-opportunity-cost charging capacity exists in
                # other slots, retain this solar for export and charge later.
                cheaper_capacity = sum(
                    self._ev_power_for_amps(self.settings.ev_max_charge_amps)
                    * later.duration_h
                    for later in candidates
                    if later is not slot
                    and self._ev_fallback_opportunity_cost(later) + 1e-9
                    < slot.export_price
                )
                if cheaper_capacity + 1e-9 >= remaining:
                    continue
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
            estimated_cost += allocated * slot.export_price
            remaining -= allocated

        # A plugged-in car below the 40% departure reserve is always a service
        # requirement, even when the trip question is unanswered.  When grid
        # permission is off, schedule only the minimum-reserve shortfall from
        # stationary-battery energy that remains above the forecast household
        # reserve. The EV must never consume energy needed to carry ordinary
        # house load through morning solar takeover.
        minimum_solar_before_departure = sum(
            planned_energy.get(id(slot), 0.0)
            for slot in candidates
            if slot.start < departure
            and planned_source.get(id(slot)) == "direct_solar"
        )
        minimum_remaining = max(
            0.0,
            minimum_reserve_required - minimum_solar_before_departure,
        )
        if minimum_remaining > 1e-9:
            protected_reserve = max(
                self.settings.battery_min_soc_pct,
                house_reserve_soc_pct
                if house_reserve_soc_pct is not None
                else self.settings.battery_morning_target_soc_pct,
            )
            battery_available_kwh = max(
                0.0,
                (battery_soc_pct - protected_reserve)
                / 100
                * battery_capacity_kwh
                * self.settings.battery_discharge_efficiency,
            )
            battery_budget_kwh = battery_available_kwh
            reserve_to_schedule = min(minimum_remaining, battery_budget_kwh)
            # Post-departure opportunistic solar cannot satisfy the morning
            # reserve. Make room for the mandatory pre-departure battery
            # tranche so total planned EV energy never exceeds its target.
            room_needed = reserve_to_schedule
            for slot in sorted(candidates, key=lambda item: item.start, reverse=True):
                index = id(slot)
                if (
                    room_needed <= 1e-9
                    or slot.start < departure
                    or planned_source.get(index) != "direct_solar"
                ):
                    continue
                removed = min(room_needed, planned_energy.get(index, 0.0))
                planned_energy[index] = max(0.0, planned_energy.get(index, 0.0) - removed)
                if planned_energy[index] <= 1e-9:
                    planned_energy.pop(index, None)
                    planned_amps.pop(index, None)
                    planned_source.pop(index, None)
                solar_energy -= removed
                remaining += removed
                room_needed -= removed
            battery_candidates = [
                slot for slot in candidates
                if slot.start < departure
            ]
            # A sub-40% Tesla is an immediate readiness fault, not an
            # economically deferrable load. Fill the earliest feasible slots
            # first; price shaping resumes only after the reserve is restored.
            for slot in sorted(battery_candidates, key=lambda item: item.start):
                if reserve_to_schedule <= 1e-9:
                    break
                index = id(slot)
                existing = planned_energy.get(index, 0.0)
                capacity = max(
                    0.0,
                    self._ev_power_for_amps(self.settings.ev_max_charge_amps)
                    * slot.duration_h
                    - existing,
                )
                allocated = min(reserve_to_schedule, capacity)
                if allocated <= 1e-9:
                    continue
                total_energy = existing + allocated
                amps = min(
                    self.settings.ev_max_charge_amps,
                    max(
                        self.settings.ev_min_charge_amps,
                        self._ev_amps_for_power(
                            total_energy / slot.duration_h,
                            round_up=True,
                        ),
                    ),
                )
                planned_energy[index] = total_energy
                planned_amps[index] = amps
                planned_source[index] = (
                    "solar_house_battery" if existing > 0 else "house_battery"
                )
                fallback_energy += allocated
                estimated_cost += allocated * self.settings.battery_wear_per_kwh
                reserve_to_schedule -= allocated
                remaining -= min(remaining, allocated)

        # Only a deadline shortfall after exhausting all conservative direct
        # solar capacity may enter this tranche.  These slots can use grid (or
        # retained battery value) and are therefore labelled explicitly rather
        # than being presented as solar charging.
        # An unanswered prompt or an explicit "No trip" response is never a
        # departure mandate.  It may use genuine direct-solar surplus to reach
        # the advisory minimum SOC, but it must not start a grid/deadline block
        # that can displace valuable home-battery export.  Only a declared trip
        # authorises the fallback tranche.
        if remaining > 1e-9 and mandatory and allow_grid:
            for slot in sorted(
                candidates,
                key=lambda item: (self._ev_fallback_opportunity_cost(item), item.start),
            ):
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
                estimated_cost += allocated * self._ev_fallback_opportunity_cost(slot)
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
        if required <= 0:
            action = "ready"
        elif mandatory and remaining > 1e-6:
            action = "insufficient_time"
        elif opportunistic_only and not selected_slots:
            action = "opportunity_wait"
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
            mandatory=mandatory,
            unmet_kwh=max(0.0, remaining),
        )

    def _ev_fallback_opportunity_cost(self, slot: Slot) -> float:
        """Value consumed by a deadline charge, including foregone solar FIT."""
        conservative_surplus = max(
            0.0,
            slot.solar_low_kw - slot.load_kw - slot.hot_water_kw,
        )
        if conservative_surplus >= self._ev_power_for_amps(self.settings.ev_min_charge_amps):
            return max(slot.import_price, slot.export_price)
        return slot.import_price

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

    def _remove_unprofitable_export_tranches(
        self,
        intervals: list[DispatchInterval],
        capacity_kwh: float,
        initial_soc_pct: float,
        minimum_sell_price: float | None = None,
        grid_reserve_charge_targets: dict[datetime, float] | None = None,
    ) -> list[DispatchInterval]:
        """Apply the physical solar -> battery -> grid source priority.

        The dynamic programme uses a 0.25 kWh stored-energy lattice.  In a
        five-minute slot its smallest discharge transition is 2.7 kW, so a
        profitable 1.4 kW household-supply tranche could previously be bundled
        with 1.3 kW of loss-making export.  Morning/evening feasibility then
        made the combined transition look attractive even though its export
        margin was negative.

        Keep the DP's intertemporal export decision, but project its output onto
        the continuous physical boundary.  Every load remaining after solar—
        including scheduled hot water and EV charging—is supplied from battery
        down to the hard floor before grid can be used.  Below the configured
        sell floor, discharge is capped to that complete site deficit so it
        never creates uneconomic export.  Recalculate from the exact input SOC
        and update grid flow, curtailment and cashflow sequentially.
        """
        if not intervals:
            return intervals

        sell_floor = max(
            self.settings.battery_wear_per_kwh,
            self.settings.battery_min_sell_price_per_kwh
            if minimum_sell_price is None
            else minimum_sell_price,
        )
        minimum_energy = capacity_kwh * self.settings.battery_min_soc_pct / 100
        maximum_energy = capacity_kwh
        energy_kwh = min(
            maximum_energy,
            max(minimum_energy, capacity_kwh * initial_soc_pct / 100),
        )
        reserve_targets = grid_reserve_charge_targets or {}
        for item in intervals:
            duration_h = max(item.duration_minutes / 60, 1 / 3600)
            base_grid_kw = item.load_kw + item.hot_water_kw + item.ev_kw - item.solar_kw
            non_hot_water_grid_kw = item.load_kw + item.ev_kw - item.solar_kw
            reserve_charge_kw = max(0.0, reserve_targets.get(item.start, 0.0))
            battery_kw = item.battery_kw
            if item.export_price < 0 and base_grid_kw < 0:
                # Consume otherwise-curtailed solar in the stationary battery
                # before anti-reflux discards it. Flexible loads are already in
                # base_grid_kw, so this uses only the surplus left after house,
                # hot water and EV demand and never creates grid charging here.
                battery_kw = -min(
                    self.settings.battery_max_charge_kw,
                    -base_grid_kw,
                )
            if reserve_charge_kw > 0:
                # The sole permitted grid-charge case: store only the
                # conservative ordinary-house reserve calculated for the next
                # low-solar period. Flexible loads are explicitly excluded.
                battery_kw = -reserve_charge_kw
            elif battery_kw < 0:
                # Ordinary charging may consume only live forecast solar
                # surplus. Economic grid arbitrage and the 99% target never
                # create imports by themselves.
                battery_kw = -min(-battery_kw, max(0.0, -base_grid_kw))
            if base_grid_kw > 0 and reserve_charge_kw <= 0:
                # Import avoidance takes precedence over retained-value
                # arbitrage. Availability is clipped against the 5% hard floor
                # below, so the grid remains the genuine last resort.
                battery_kw = max(
                    battery_kw,
                    min(self.settings.battery_max_discharge_kw, base_grid_kw),
                )
            if item.hot_water_kw > 0 and battery_kw > 0:
                # Hot water is solar-only in normal operation and grid-only in
                # service rescue. The stationary battery may still cover the
                # simultaneous house/EV deficit, but never the element.
                battery_kw = min(
                    battery_kw,
                    max(0.0, non_hot_water_grid_kw),
                )
            if (
                battery_kw > 0
                and item.export_price + 1e-9 < sell_floor
            ):
                # The sell floor gates battery export only.  It never prevents
                # the battery from carrying an EV, hot-water, or normal house
                # load that would otherwise import from the grid.
                battery_kw = min(battery_kw, max(0.0, base_grid_kw))

            if battery_kw > 0:
                maximum_output_kw = (
                    max(0.0, energy_kwh - minimum_energy)
                    * self.settings.battery_discharge_efficiency
                    / duration_h
                )
                battery_kw = min(battery_kw, maximum_output_kw)
                next_energy_kwh = (
                    energy_kwh
                    - battery_kw
                    * duration_h
                    / self.settings.battery_discharge_efficiency
                )
            elif battery_kw < 0:
                maximum_input_kw = (
                    max(0.0, maximum_energy - energy_kwh)
                    / self.settings.battery_charge_efficiency
                    / duration_h
                )
                battery_kw = -min(-battery_kw, maximum_input_kw)
                next_energy_kwh = (
                    energy_kwh
                    + (-battery_kw)
                    * duration_h
                    * self.settings.battery_charge_efficiency
                )
            else:
                next_energy_kwh = energy_kwh

            raw_grid_kw = base_grid_kw - battery_kw
            imported_kw = max(0.0, raw_grid_kw)
            potential_export_kw = max(0.0, -raw_grid_kw)
            curtailed_kw = potential_export_kw if item.export_price < 0 else 0.0
            exported_kw = potential_export_kw - curtailed_kw
            metered_grid_kw = imported_kw - exported_kw
            imported_for_battery_kw = max(
                0.0,
                imported_kw - max(0.0, base_grid_kw),
            )
            wear_cost = (
                max(0.0, battery_kw)
                * duration_h
                * self.settings.battery_wear_per_kwh
            )
            interval_cost = (
                imported_kw * duration_h * item.import_price
                - exported_kw * duration_h * item.export_price
                + wear_cost
                + imported_for_battery_kw
                * duration_h
                * self.settings.grid_charge_uncertainty_per_kwh
            )

            item.battery_kw = round(battery_kw, 3)
            item.site_grid_kw = round(metered_grid_kw, 3)
            item.pv_curtailment_kw = round(curtailed_kw, 3)
            item.soc_start_pct = round(100 * energy_kwh / capacity_kwh, 1)
            item.soc_end_pct = round(100 * next_energy_kwh / capacity_kwh, 1)
            item.cost = round(interval_cost, 4)
            energy_kwh = min(maximum_energy, max(minimum_energy, next_energy_kwh))
        return intervals

    def _home_reserve_grid_charge_targets(
        self,
        slots: list[Slot],
        initial_soc_pct: float,
        capacity_kwh: float,
        morning: datetime | None,
    ) -> dict[datetime, float]:
        """Return the minimal last-resort grid charge for ordinary house load.

        The reserve excludes hot water and EV demand. It is created only when
        conservative solar plus energy above the 5% floor cannot carry the
        normal house to the next sustainable solar takeover while retaining
        the 7% morning target.
        """
        if not slots:
            return {}
        horizon = morning
        if horizon is None or horizon <= slots[0].start:
            for index in range(len(slots) - 1):
                if (
                    slots[index].solar_low_kw >= slots[index].load_kw + 0.3
                    and slots[index + 1].solar_low_kw >= slots[index + 1].load_kw + 0.3
                ):
                    horizon = slots[index].start
                    break
        if horizon is None:
            return {}
        relevant = [slot for slot in slots if slot.start < horizon]
        if not relevant:
            return {}
        ordinary_deficit_kwh = sum(
            max(0.0, slot.load_kw - slot.solar_low_kw) * slot.duration_h
            for slot in relevant
        )
        available_output_kwh = (
            max(0.0, initial_soc_pct - self.settings.battery_min_soc_pct)
            / 100
            * capacity_kwh
            * self.settings.battery_discharge_efficiency
        )
        morning_buffer_output_kwh = (
            max(
                0.0,
                self.settings.battery_morning_target_soc_pct
                - self.settings.battery_min_soc_pct,
            )
            / 100
            * capacity_kwh
            * self.settings.battery_discharge_efficiency
        )
        shortfall_output_kwh = max(
            0.0,
            ordinary_deficit_kwh
            + morning_buffer_output_kwh
            - available_output_kwh,
        )
        remaining_input_kwh = shortfall_output_kwh / (
            self.settings.battery_charge_efficiency
            * self.settings.battery_discharge_efficiency
        )
        if remaining_input_kwh <= 1e-6:
            return {}
        targets: dict[datetime, float] = {}
        for slot in sorted(relevant, key=lambda item: (item.import_price, -item.start.timestamp())):
            if remaining_input_kwh <= 1e-6:
                break
            input_kwh = min(
                remaining_input_kwh,
                self.settings.battery_max_charge_kw * slot.duration_h,
            )
            targets[slot.start] = input_kwh / slot.duration_h
            remaining_input_kwh -= input_kwh
        return targets

    def _dispatch(
        self,
        slots: list[Slot],
        initial_soc_pct: float,
        capacity_kwh: float,
        evening: datetime | None,
        morning: datetime | None = None,
        *,
        minimum_sell_price: float | None = None,
    ) -> list[DispatchInterval]:
        sell_floor = max(
            self.settings.battery_wear_per_kwh,
            self.settings.battery_min_sell_price_per_kwh
            if minimum_sell_price is None
            else minimum_sell_price,
        )
        step = 0.25
        min_energy = capacity_kwh * self.settings.battery_min_soc_pct / 100
        max_energy = capacity_kwh
        energy_levels = [min_energy + index * step for index in range(int((max_energy - min_energy) // step) + 1)]
        if max_energy - energy_levels[-1] > 1e-6:
            energy_levels.append(max_energy)
        initial_energy = min(max_energy, max(min_energy, capacity_kwh * initial_soc_pct / 100))
        insertion = bisect_left(energy_levels, initial_energy)
        if (
            insertion >= len(energy_levels)
            or abs(energy_levels[insertion] - initial_energy) > 1e-9
        ):
            energy_levels.insert(insertion, initial_energy)
        level_count = len(energy_levels)

        def energy(level: int) -> float:
            return energy_levels[level]

        initial_level = bisect_left(energy_levels, initial_energy)
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
                if slot.export_price >= (
                    sell_floor + self.settings.grid_charge_uncertainty_per_kwh
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
                    if full_feasible and index == evening_index and next_energy + 1e-6 < full_target:
                        continue
                    delta = next_energy - previous_energy
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
                hot_water_control_mode=slot.hot_water_control_mode,
                ev_kw=round(slot.ev_kw, 3),
                ev_charge_source=slot.ev_charge_source,
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
        reserve_charge_targets = self._home_reserve_grid_charge_targets(
            slots,
            initial_soc_pct,
            capacity_kwh,
            morning,
        )
        return self._remove_unprofitable_export_tranches(
            result,
            capacity_kwh,
            initial_soc_pct,
            sell_floor,
            reserve_charge_targets,
        )
