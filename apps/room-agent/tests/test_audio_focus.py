from __future__ import annotations

import subprocess
import unittest

from pilot_room_agent.audio_focus import (
    FocusEnforcer,
    decide,
    parse_pipewire_nodes,
    parse_stream_nodes,
)
from pilot_room_agent.controls import ControlState


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

    def test_parses_sendspin_generic_python_alsa_stream(self) -> None:
        nodes = parse_stream_nodes("        44. PipeWire ALSA [python3.13]\n")
        self.assertEqual(nodes, {"music": 44})

    def test_pipewire_dump_resolves_real_sendspin_node_id(self) -> None:
        nodes = parse_pipewire_nodes(
            """
            [
              {
                "id": 69,
                "type": "PipeWire:Interface:Node",
                "info": {"props": {
                  "media.class": "Stream/Output/Audio",
                  "application.name": "PipeWire ALSA [python3.13]",
                  "node.name": "alsa_playback.python3.13"
                }}
              },
              {
                "id": 44,
                "type": "PipeWire:Interface:Client",
                "info": {"props": {"application.name": "PipeWire ALSA [python3.13]"}}
              }
            ]
            """
        )
        self.assertEqual(nodes, {"music": 69})

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

    def test_control_state_maps_listening_to_assistant_focus(self) -> None:
        state = ControlState()
        state.set("listening", True, 30)
        decision = decide(
            {**state.focus_sources(), "music": True, "airplay": False},
            0.2,
        )
        self.assertEqual(decision.foreground, "assistant")
        self.assertEqual(decision.gains["music"], 0.2)


if __name__ == "__main__":
    unittest.main()
