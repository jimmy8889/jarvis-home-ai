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
        ev = self._schedule_ev(slots, states, now)

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
        actuation_allowed = (
            mode == "active"
            and battery_enabled
            and rollout_approved
            and not manual_override
        )
        warnings: list[str] = []
        if any(slot.price_source != "amber" for slot in slots[:12]):
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
    ) -> _EVSchedule:
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
        candidates = [
            slot for slot in slots
            if slot.start < departure
            and slot.start >= now - timedelta(minutes=self.settings.slot_minutes)
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
        for slot in candidates:
            surplus_kw = max(0.0, slot.solar_low_kw - slot.load_kw - slot.hot_water_kw)
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
        if remaining > 1e-9:
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
        charge_end = selected_times[-1] + timedelta(minutes=self.settings.slot_minutes) if selected_times else None
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
