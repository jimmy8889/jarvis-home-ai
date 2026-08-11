from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from bisect import bisect_left, bisect_right
import hashlib
import math
from typing import Any
from zoneinfo import ZoneInfo

from .config import ENTITY, Settings
from .models import DispatchInterval, Plan, Slot
from .parsing import build_slots, numeric_state, parse_datetime, state_is_on
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


class EnergyOptimizer:
    def __init__(self, settings: Settings, learning: LearningState):
        self.settings = settings
        self.learning = learning
        self.timezone = ZoneInfo(settings.timezone)

    def build_plan(self, raw_states: list[dict[str, Any]], now: datetime | None = None) -> Plan:
        now = (now or datetime.now(self.timezone)).astimezone(self.timezone)
        states = {item.get("entity_id", ""): item for item in raw_states}
        self._update_learning(states, now)

        fit_entity = states.get(ENTITY["amber_fit"], {})
        import_entity = states.get(ENTITY["amber_import"], {})
        solar_entities = [states.get(ENTITY["solcast_today"], {}), states.get(ENTITY["solcast_tomorrow"], {})]
        weather = str(states.get(ENTITY["weather"], {}).get("state", "unknown"))
        slots = build_slots(
            now=now,
            horizon_hours=self.settings.horizon_hours,
            slot_minutes=self.settings.slot_minutes,
            timezone=self.timezone,
            fit_entity=fit_entity,
            import_entity=import_entity,
            solar_entities=solar_entities,
            load_forecast=self.learning.forecast_load,
            calibration_ratio=self.learning.solar_calibration_ratio,
            weather_condition=weather,
        )

        morning, evening = self._detect_crossovers(slots, now)
        self._schedule_hot_water(slots, states, now, evening)
        ev_target, ev_required, ev_action, ev_start, ev_end, ev_cost = self._schedule_ev(slots, states, now)

        soc = numeric_state(states, ENTITY["battery_soc"], 50.0)
        capacity = numeric_state(states, ENTITY["battery_usable"], self.settings.battery_capacity_kwh)
        capacity = min(60.0, max(35.0, capacity))
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
        shadow_started = parse_datetime(states.get(ENTITY["shadow_started"], {}).get("state"), self.timezone)
        shadow_mature = shadow_started is not None and now >= shadow_started + timedelta(days=7)
        actuation_allowed = (
            mode == "active"
            and battery_enabled
            and rollout_approved
            and shadow_mature
            and not manual_override
        )
        warnings: list[str] = []
        if any(slot.price_source != "amber" for slot in slots[:12]):
            warnings.append("Amber forecast horizon is incomplete; historical price fallback is in use")
        if not solar_entities[0].get("attributes", {}).get("detailedForecast"):
            warnings.append("Solcast detailed forecast is unavailable")
        if manual_override:
            warnings.append("Manual override is enabled")
        if not shadow_mature:
            warnings.append("Seven-day shadow validation gate is not yet mature")
        if not rollout_approved:
            warnings.append("Rollout approval is off")
        if mode != "active":
            warnings.append("Shadow mode: no optimiser command may be actuated")

        confidence = self.learning.solar_confidence
        if warnings:
            confidence = max(0.25, confidence - 0.08 * len(warnings))
        generated = now.astimezone(self.timezone)
        plan_seed = f"{generated.isoformat()}:{first.battery_kw:.3f}:{first.site_grid_kw:.3f}"
        plan_id = f"eop-{generated:%Y%m%dT%H%M%S}-{hashlib.sha256(plan_seed.encode()).hexdigest()[:8]}"
        expected_cost = sum(max(0.0, item.site_grid_kw) * item.duration_minutes / 60 * item.import_price for item in intervals)
        expected_revenue = sum(max(0.0, -item.site_grid_kw) * item.duration_minutes / 60 * item.export_price for item in intervals)
        expected_wear = sum(item.wear_cost if hasattr(item, "wear_cost") else max(0.0, item.battery_kw) * item.duration_minutes / 60 * self.settings.battery_wear_per_kwh for item in intervals)

        return Plan(
            plan_id=plan_id,
            generated_at=generated,
            valid_until=generated + timedelta(minutes=10),
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
            ev_action=ev_action if first.ev_kw <= 0 else ("charge" if state_is_on(states, ENTITY["ev_plugged"]) else "recommend_charge"),
            ev_target_soc_pct=ev_target,
            ev_required_kwh=ev_required,
            ev_charge_amps_target=(max(5, min(16, round(first.ev_kw * 1000 / 230))) if first.ev_kw > 0 else 0),
            ev_charge_start=ev_start,
            ev_charge_end=ev_end,
            ev_estimated_cost=ev_cost,
            morning_takeover=morning,
            evening_crossover=evening,
            expected_cost=expected_cost,
            expected_revenue=expected_revenue,
            expected_wear_cost=expected_wear,
            warnings=warnings,
            intervals=intervals,
        )

    def _update_learning(self, states: dict[str, dict[str, Any]], now: datetime) -> None:
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
        blocks = math.ceil(required_h / (self.settings.slot_minutes / 60))
        if blocks <= 0:
            return
        latest = datetime.combine(now.date(), time(self.settings.hot_water_latest_hour), self.timezone)
        if evening and evening.date() == now.date():
            latest = min(latest, evening)
        candidates = [
            slot for slot in slots
            if slot.start.date() == now.date() and slot.start >= now - timedelta(minutes=self.settings.slot_minutes) and slot.start < latest
        ]
        if not candidates:
            return

        def opportunity_cost(slot: Slot) -> tuple[float, datetime]:
            solar_surplus = slot.solar_low_kw - slot.load_kw
            price = max(0.0, slot.export_price) if solar_surplus >= self.settings.hot_water_kw else slot.import_price
            urgency = 0.0 if slot.start + timedelta(hours=slot.duration_h * blocks) < latest else -1.0
            return price + urgency, slot.start

        for slot in sorted(candidates, key=opportunity_cost)[:blocks]:
            slot.hot_water_kw = self.settings.hot_water_kw

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
    ) -> tuple[float, float, str, datetime | None, datetime | None, float]:
        selection = str(states.get(ENTITY["ev_trip"], {}).get("state", "Unanswered")).lower()
        distances = {"no trip": 0.0, "local / 50 km": 50.0, "100 km": 100.0, "200 km": 200.0}
        if "custom" in selection:
            distance = numeric_state(states, ENTITY["ev_custom_km"], 0.0)
        else:
            distance = distances.get(selection, 0.0)
        trip_energy = distance * self.settings.ev_kwh_per_km * self.settings.ev_trip_margin
        target = max(
            self.settings.ev_minimum_departure_soc_pct,
            self.settings.ev_arrival_reserve_pct + 100 * trip_energy / self.settings.ev_usable_capacity_kwh,
        )
        target = min(target, numeric_state(states, ENTITY["ev_limit"], 80.0))
        current = numeric_state(states, ENTITY["ev_soc"], target)
        required = max(0.0, (target - current) / 100 * self.settings.ev_usable_capacity_kwh / 0.90)
        departure = self._departure(states, now)
        connected = state_is_on(states, ENTITY["ev_plugged"]) and state_is_on(states, ENTITY["ev_home"])
        selected: list[tuple[Slot, float, float]] = []
        if required > 0:
            candidates = [slot for slot in slots if slot.start < departure and slot.start >= now - timedelta(minutes=self.settings.slot_minutes)]

            def opportunity_cost(slot: Slot) -> tuple[float, datetime]:
                surplus = slot.solar_low_kw - slot.load_kw - slot.hot_water_kw
                return (max(0.0, slot.export_price) if surplus > 0 else slot.import_price, slot.start)

            remaining = required
            for slot in sorted(candidates, key=opportunity_cost):
                if remaining <= 0:
                    break
                maximum = self.settings.ev_max_charge_kw * slot.duration_h
                allocated = min(maximum, remaining)
                price = opportunity_cost(slot)[0]
                selected.append((slot, allocated, price))
                if connected:
                    slot.ev_kw = allocated / slot.duration_h
                remaining -= allocated
        if "unanswered" in selection:
            action = "prompt_trip"
        elif required <= 0:
            action = "ready"
        else:
            action = "recommend_charge"
        selected_times = sorted(item[0].start for item in selected)
        charge_start = selected_times[0] if selected_times else None
        charge_end = selected_times[-1] + timedelta(minutes=self.settings.slot_minutes) if selected_times else None
        estimated_cost = sum(allocated * price for _, allocated, price in selected)
        return target, required, action, charge_start, charge_end, estimated_cost

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

        maximum_import = max((slot.import_price for slot in slots), default=0.20)
        terminal_value = max(0.0, min(0.30, maximum_import) - self.settings.battery_wear_per_kwh) * self.settings.battery_discharge_efficiency
        final_level = min(costs, key=lambda level: costs[level] - energy(level) * terminal_value)
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
                duration_minutes=round(slot.duration_h * 60),
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
