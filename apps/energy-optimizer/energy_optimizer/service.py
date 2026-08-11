from __future__ import annotations

import asyncio
from datetime import datetime
import json
import logging
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .config import Settings
from .ha import HomeAssistantClient
from .models import Plan
from .optimizer import EnergyOptimizer
from .state import LearningState


LOG = logging.getLogger(__name__)


class Coordinator:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.timezone = ZoneInfo(settings.timezone)
        self.learning = LearningState(settings.data_dir / "learning-state.json")
        self.optimizer = EnergyOptimizer(settings, self.learning)
        self.ha = HomeAssistantClient(settings.ha_url, settings.ha_token_file)
        self.last_plan: Plan | None = None
        self.last_success: datetime | None = None
        self.last_error: str | None = None
        self._stop = asyncio.Event()

    async def close(self) -> None:
        self._stop.set()
        await self.ha.close()

    async def run_forever(self) -> None:
        while not self._stop.is_set():
            started = asyncio.get_running_loop().time()
            try:
                await self.run_once()
            except Exception as exc:  # noqa: BLE001 - the service must remain alive and publish failure health
                self.last_error = f"{type(exc).__name__}: {exc}"
                LOG.exception("optimisation cycle failed")
                await self._publish_failure(self.last_error)
            elapsed = asyncio.get_running_loop().time() - started
            delay = max(5.0, self.settings.interval_seconds - elapsed)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
            except TimeoutError:
                pass

    async def run_once(self) -> Plan:
        states = await self.ha.states()
        plan = self.optimizer.build_plan(states)
        self._record_plan(plan)
        await self._publish_plan(plan)
        self.last_plan = plan
        self.last_success = datetime.now(self.timezone)
        self.last_error = None
        LOG.info(
            "plan=%s mode=%s action=%s battery_kw=%.2f export_kw=%.2f confidence=%.2f",
            plan.plan_id,
            plan.mode,
            plan.action,
            plan.battery_power_target_kw,
            plan.site_export_target_kw,
            plan.confidence,
        )
        return plan

    def _record_plan(self, plan: Plan) -> None:
        self.settings.data_dir.mkdir(parents=True, exist_ok=True)
        full = plan.to_dict()
        latest = self.settings.data_dir / "latest-plan.json"
        temporary = latest.with_suffix(".tmp")
        temporary.write_text(json.dumps(full, indent=2, sort_keys=True))
        temporary.replace(latest)
        journal = self.settings.data_dir / "plans" / f"{plan.generated_at:%Y-%m-%d}.jsonl"
        journal.parent.mkdir(parents=True, exist_ok=True)
        with journal.open("a") as handle:
            handle.write(json.dumps(full, separators=(",", ":")) + "\n")

    async def _publish_plan(self, plan: Plan) -> None:
        summary = plan.to_dict(interval_limit=12)
        common = {"plan_id": plan.plan_id, "generated_at": plan.generated_at.isoformat(), "valid_until": plan.valid_until.isoformat()}
        publishes = [
            self.ha.publish_state("sensor.energy_optimizer_status", plan.mode, {
                **common,
                "friendly_name": "Energy Optimizer Status",
                "icon": "mdi:home-lightning-bolt-outline",
                "action": plan.action,
                "reason": plan.reason,
                "confidence": plan.confidence,
                "warnings": plan.warnings,
            }),
            self.ha.publish_state("sensor.energy_optimizer_battery_power_target", round(plan.battery_power_target_kw, 3), {
                **common,
                "friendly_name": "Energy Optimizer Battery Power Target",
                "unit_of_measurement": "kW",
                "device_class": "power",
                "state_class": "measurement",
                "action": plan.action,
                "actuation_allowed": plan.actuation_allowed,
            }),
            self.ha.publish_state("sensor.energy_optimizer_site_export_target", round(plan.site_export_target_kw, 3), {
                **common,
                "friendly_name": "Energy Optimizer Site Export Target",
                "unit_of_measurement": "kW",
                "device_class": "power",
                "state_class": "measurement",
            }),
            self.ha.publish_state("sensor.energy_optimizer_pv_export", plan.pv_export_command, {
                **common,
                "friendly_name": "Energy Optimizer PV Export",
                "icon": "mdi:transmission-tower-export",
                "curtailment_target_kw": plan.pv_curtailment_target_kw,
            }),
            self.ha.publish_state("sensor.energy_optimizer_hot_water", plan.hot_water_command, {
                **common,
                "friendly_name": "Energy Optimizer Hot Water",
                "icon": "mdi:water-boiler",
                "evening_crossover": plan.evening_crossover.isoformat() if plan.evening_crossover else None,
            }),
            self.ha.publish_state("sensor.energy_optimizer_ev", plan.ev_action, {
                **common,
                "friendly_name": "Energy Optimizer EV",
                "icon": "mdi:car-electric",
                "target_soc_pct": plan.ev_target_soc_pct,
                "required_kwh": plan.ev_required_kwh,
                "charge_amps_target": plan.ev_charge_amps_target,
                "charge_start": plan.ev_charge_start.isoformat() if plan.ev_charge_start else None,
                "charge_end": plan.ev_charge_end.isoformat() if plan.ev_charge_end else None,
                "estimated_cost": plan.ev_estimated_cost,
            }),
            self.ha.publish_state("sensor.energy_optimizer_plan", plan.plan_id, {
                "friendly_name": "Energy Optimizer Plan",
                "icon": "mdi:chart-timeline-variant-shimmer",
                **summary,
            }),
        ]
        await asyncio.gather(*publishes)

    async def _publish_failure(self, error: str) -> None:
        try:
            await self.ha.publish_state("sensor.energy_optimizer_status", "error", {
                "friendly_name": "Energy Optimizer Status",
                "icon": "mdi:alert-circle",
                "error": error[:512],
                "safe_state": "Node-RED must reject stale plans and cancel forced operation",
            })
        except Exception:  # noqa: BLE001
            LOG.exception("failed to publish optimiser failure to Home Assistant")

    def health(self) -> dict[str, Any]:
        return {
            "status": "ok" if self.last_success and not self.last_error else "starting" if not self.last_error else "error",
            "last_success": self.last_success.isoformat() if self.last_success else None,
            "last_error": self.last_error,
            "plan_id": self.last_plan.plan_id if self.last_plan else None,
            "mode": self.last_plan.mode if self.last_plan else None,
        }
