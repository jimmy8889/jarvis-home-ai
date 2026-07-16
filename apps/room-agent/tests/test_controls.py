from __future__ import annotations

import subprocess
from threading import Thread
import time
import unittest

from pilot_room_agent.controls import ControlError, ControlState, RoomController


class ControlStateTests(unittest.TestCase):
    def test_transient_state_expires_and_advances_revision(self) -> None:
        now = [10.0]
        state = ControlState(lambda: now[0])
        state.set("listening", True, 5)
        active = state.snapshot()
        self.assertTrue(active["listening"])

        now[0] = 15.0
        expired = state.snapshot()
        self.assertFalse(expired["listening"])
        self.assertGreater(expired["revision"], active["revision"])

    def test_focus_sources_include_listening_and_critical_announcement(self) -> None:
        state = ControlState()
        state.set("listening", True, 30)
        state.set("critical_announcement", True, 30)
        self.assertEqual(
            state.focus_sources(),
            {"critical": True, "assistant": True},
        )

    def test_wait_for_change_wakes_on_transient_update(self) -> None:
        state = ControlState()
        revision = state.snapshot()["revision"]
        observed: list[int] = []
        waiter = Thread(
            target=lambda: observed.append(state.wait_for_change(revision, 1))
        )
        waiter.start()
        time.sleep(0.01)
        state.set("assistant_speaking", True, 30)
        waiter.join(timeout=1)
        self.assertFalse(waiter.is_alive())
        self.assertGreater(observed[0], revision)


class RoomControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.commands: list[list[str]] = []

        def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
            self.commands.append(command)
            return subprocess.CompletedProcess(command, 0, "", "")

        self.state = ControlState()
        self.controller = RoomController(
            self.state,
            runner=runner,
            sendspin_bus_resolver=lambda: "org.mpris.MediaPlayer2.Sendspin.test",
            airplay_bus_resolver=lambda: "org.mpris.MediaPlayer2.ShairportSync",
        )

    def test_pause_all_controls_airplay_and_music(self) -> None:
        result = self.controller.execute({"action": "pause"})
        self.assertEqual(result.detail["affected"], ["airplay", "music"])
        self.assertEqual(len(self.commands), 2)
        self.assertTrue(all(command[-1] == "Pause" for command in self.commands))

    def test_room_volume_uses_default_pipewire_sink(self) -> None:
        result = self.controller.execute(
            {"action": "set_volume", "source": "room", "volume": 0.42}
        )
        self.assertEqual(
            self.commands,
            [["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "0.4200"]],
        )
        self.assertEqual(result.detail["volume"], 0.42)

    def test_music_volume_uses_mpris(self) -> None:
        self.controller.execute(
            {"action": "set_volume", "source": "music", "volume": 0.25}
        )
        self.assertEqual(self.commands[0][-3:], ["Volume", "d", "0.250000"])
        self.assertIn("set-property", self.commands[0])

    def test_critical_announcement_sets_both_focus_states(self) -> None:
        result = self.controller.execute(
            {
                "action": "announcement_start",
                "critical": True,
                "ttl_seconds": 60,
            }
        )
        self.assertTrue(result.state["announcement_active"])
        self.assertTrue(result.state["critical_announcement"])

        ended = self.controller.execute({"action": "announcement_end"})
        self.assertFalse(ended.state["announcement_active"])
        self.assertFalse(ended.state["critical_announcement"])

    def test_cancel_clears_transient_state_without_stopping_music(self) -> None:
        self.controller.execute({"action": "start_listening"})
        result = self.controller.execute({"action": "cancel"})
        self.assertFalse(result.state["listening"])
        self.assertEqual(self.commands, [])

    def test_invalid_volume_is_rejected(self) -> None:
        with self.assertRaisesRegex(ControlError, "between 0 and 1"):
            self.controller.execute({"action": "set_volume", "volume": 2})

    def test_explicit_unavailable_music_player_is_rejected(self) -> None:
        controller = RoomController(
            self.state,
            runner=lambda command: subprocess.CompletedProcess(command, 0, "", ""),
            sendspin_bus_resolver=lambda: None,
            airplay_bus_resolver=lambda: None,
        )
        with self.assertRaisesRegex(ControlError, "unavailable"):
            controller.execute({"action": "pause", "source": "music"})

    def test_all_skips_an_unavailable_player(self) -> None:
        controller = RoomController(
            self.state,
            runner=lambda command: subprocess.CompletedProcess(command, 0, "", ""),
            sendspin_bus_resolver=lambda: "org.mpris.MediaPlayer2.Sendspin.test",
            airplay_bus_resolver=lambda: None,
        )
        result = controller.execute({"action": "pause", "source": "all"})
        self.assertEqual(result.detail["affected"], ["music"])
        self.assertEqual(result.detail["unavailable"], ["airplay"])


if __name__ == "__main__":
    unittest.main()
