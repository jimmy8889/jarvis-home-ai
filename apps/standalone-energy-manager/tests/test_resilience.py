from datetime import UTC, datetime, timedelta

from energy_manager.models import Telemetry
from energy_manager.nut import NutPowerState
from energy_manager.resilience import allocate_ups_power, fuse_grid_health, resilience_stage


def telemetry(state: str, phases: tuple[bool, bool, bool]) -> Telemetry:
    return Telemetry(
        measured_at=datetime.now(UTC), grid_state=state,
        grid_online=state != "lost", grid_phase_present=phases,
    )


def nut(status: str = "OL", age: float = 0) -> NutPowerState:
    return NutPowerState(
        measured_at=datetime.now(UTC) - timedelta(seconds=age), available=True,
        status=status, input_voltage_v=240, raw_real_power_w=540,
        server_rack_power_w=600, confidence="live_efficiency",
        variables={"outlet.realpower": "490", "outlet.1.realpower": "50"},
    )


def test_grid_health_truth_table_and_disagreement():
    healthy, supply = fuse_grid_health(telemetry("healthy", (True, True, True)), nut())
    assert healthy.state == "healthy" and supply.state == "mains"
    partial, _ = fuse_grid_health(telemetry("degraded", (True, False, True)), nut())
    assert partial.state == "degraded"
    lost, protected = fuse_grid_health(telemetry("lost", (False, False, False)), nut("OB"))
    assert lost.state == "lost" and protected.state == "ups_battery"
    disagree, _ = fuse_grid_health(telemetry("lost", (False, False, False)), nut("OL"))
    assert disagree.state == "degraded" and disagree.disagreement
    stale, _ = fuse_grid_health(None, nut("OL"))
    assert stale.state == "degraded" and stale.utility_source == "nut_fallback"
    unknown, _ = fuse_grid_health(None, nut("OL", age=10))
    assert unknown.state == "unknown"


def test_ups_allocation_conserves_wall_input():
    allocation = allocate_ups_power(nut())
    assert allocation["rack_output_w"] == 490
    assert allocation["office_output_w"] == 50
    assert allocation["conversion_loss_w"] == 60
    assert abs(allocation["rack_wall_allocated_w"] + allocation["office_wall_allocated_w"] - allocation["wall_input_w"]) < 1e-9


def test_runtime_stages_are_orderly_only():
    assert resilience_stage("healthy", 60, 5, 5) == "normal"
    assert resilience_stage("lost", 19 * 60, 90, 50) == "warning_arm"
    assert resilience_stage("lost", 11 * 60, 90, 50) == "orderly_shutdown"
    assert resilience_stage("lost", 7 * 60, 90, 50) == "urgent_graceful_shutdown"
    assert resilience_stage("lost", 30 * 60, 90, 8) == "urgent_graceful_shutdown"


def test_no_ups_or_guest_control_surface_exists():
    source = __import__("inspect").getsource(__import__("energy_manager.shutdown", fromlist=["NodeShutdownCoordinator"]))
    assert "outlet" not in source.lower()
    assert "/qemu/" not in source and "/lxc/" not in source
    assert "hard" not in source.lower() and "stopall" not in source.lower()
