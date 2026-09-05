from __future__ import annotations

from dataclasses import dataclass

from .config import Settings


@dataclass(frozen=True)
class BatteryExportEconomics:
    """Marginal value which must be cleared before stored energy is sold."""

    acquisition_or_retained_per_kwh: float
    uncertainty_per_kwh: float
    wear_per_kwh: float

    @property
    def retained_value_per_kwh(self) -> float:
        return self.acquisition_or_retained_per_kwh + self.uncertainty_per_kwh

    @property
    def marginal_cost_per_kwh(self) -> float:
        return self.retained_value_per_kwh + self.wear_per_kwh


def battery_export_economics(
    settings: Settings,
    import_price_per_kwh: float | None,
) -> BatteryExportEconomics:
    """Use one conservative export-cost calculation in planning and control.

    Retained battery energy avoids a later AC import after discharge losses.
    The uncertainty and wear allowances are additive; neither can be hidden by
    a high import price or counted twice by a caller.
    """

    avoided_import = max(0.0, float(import_price_per_kwh or 0.0))
    acquisition_or_retained = avoided_import / max(settings.battery_discharge_efficiency, 0.01)
    return BatteryExportEconomics(
        acquisition_or_retained_per_kwh=acquisition_or_retained,
        uncertainty_per_kwh=max(0.0, settings.uncertainty_per_kwh),
        wear_per_kwh=max(0.0, settings.battery_wear_per_kwh),
    )


def protected_surplus_export_economics(settings: Settings) -> BatteryExportEconomics:
    """Cost basis for energy explicitly above the protected SOC trajectory.

    The protected trajectory has already allocated energy for forecast house
    demand. Charging that same surplus tranche with the live avoided-import
    value double-counts retention and makes the operator sell floor cosmetic.
    Surplus export therefore clears the configured floor plus its direct wear
    and uncertainty costs while the SOC guard remains independently mandatory.
    """

    return BatteryExportEconomics(
        acquisition_or_retained_per_kwh=0.0,
        uncertainty_per_kwh=max(0.0, settings.uncertainty_per_kwh),
        wear_per_kwh=max(0.0, settings.battery_wear_per_kwh),
    )


def profitable_export_site_target_kw(
    settings: Settings,
    fit_per_kwh: float,
    later_fit_per_kwh: list[float] | tuple[float, ...],
) -> float:
    """Shared Amber price ramp used by both rolling and live dispatch."""

    later_peak = max(later_fit_per_kwh, default=fit_per_kwh)
    scarcity = 0.5 if later_peak > fit_per_kwh + 0.05 else 1.0
    price_scale = min(
        1.0,
        max(0.15, (fit_per_kwh - settings.min_sell_price_per_kwh + 0.02) / 0.20),
    )
    return settings.max_discharge_kw * scarcity * price_scale
