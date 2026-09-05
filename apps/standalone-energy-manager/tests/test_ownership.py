import pytest

from energy_manager.ownership import ControllerOwnership


def test_only_one_local_controller_can_hold_ownership(tmp_path) -> None:
    path = tmp_path / "controller.lock"
    first = ControllerOwnership(path)
    second = ControllerOwnership(path)
    first.acquire()
    try:
        with pytest.raises(RuntimeError, match="already held"):
            second.acquire()
    finally:
        first.release()
    second.acquire()
    second.release()
