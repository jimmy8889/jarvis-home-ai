from __future__ import annotations

import subprocess
import unittest

from pilot_room_agent.audio_focus import FocusEnforcer, decide, parse_stream_nodes


class AudioFocusTests(unittest.TestCase):
    def test_parses_known_pipewire_streams(self) -> None:
        nodes = parse_stream_nodes(
            """
        56. Shairport Sync
        62. linux_voice_assistant
        70. Sendspin
            """
        )
        self.assertEqual(nodes, {"airplay": 56, "assistant": 62, "music": 70})

    def test_assistant_ducks_lower_priority_sources(self) -> None:
        decision = decide({"assistant": True, "music": True}, 0.2)
        self.assertEqual(decision.foreground, "assistant")
        self.assertEqual(decision.gains["music"], 0.2)

    def test_enforcer_restores_baseline(self) -> None:
        commands: list[list[str]] = []

        def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
            commands.append(command)
            if command[1] == "get-volume":
                return subprocess.CompletedProcess(command, 0, "Volume: 0.7500\n", "")
            return subprocess.CompletedProcess(command, 0, "", "")

        enforcer = FocusEnforcer(runner)
        enforcer.apply(decide({"assistant": True, "music": True}, 0.2), {"music": 70})
        enforcer.apply(decide({"music": True}, 0.2), {"music": 70})
        set_commands = [command for command in commands if command[1] == "set-volume"]
        self.assertEqual(set_commands[0][-1], "0.1500")
        self.assertEqual(set_commands[1][-1], "0.7500")

    def test_inactive_persistent_stream_is_not_muted(self) -> None:
        commands: list[list[str]] = []

        def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
            commands.append(command)
            return subprocess.CompletedProcess(command, 0, "Volume: 1.0000\n", "")

        FocusEnforcer(runner).apply(
            decide({"assistant": False, "music": True}, 0.2),
            {"assistant": 62},
        )
        self.assertEqual(commands, [])


if __name__ == "__main__":
    unittest.main()
