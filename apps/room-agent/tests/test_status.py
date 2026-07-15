from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pilot_room_agent.config import Settings
from pilot_room_agent.status import (
    _mpris_playback_status,
    _tcp_port_status,
    _tcp_remote_port_status,
    collect_status,
)


class StatusTests(unittest.TestCase):
    @patch("pilot_room_agent.status._command_status")
    def test_ready_when_required_subsystems_are_healthy(self, command_status) -> None:
        command_status.return_value = {"available": True, "ok": True, "detail": "card 0"}
        status = collect_status(Settings(room_id="office"))
        self.assertTrue(status["ready"])
        self.assertEqual(status["room_id"], "office")
        self.assertEqual(command_status.call_count, 3)

    @patch("pilot_room_agent.status._command_status")
    def test_bluetooth_is_checked_only_when_enabled(self, command_status) -> None:
        command_status.return_value = {"available": True, "ok": True, "detail": "card 0"}
        collect_status(Settings(bluetooth_enabled=True))
        self.assertEqual(command_status.call_count, 4)

    @patch("pilot_room_agent.status._command_status")
    def test_empty_alsa_lists_are_not_ready(self, command_status) -> None:
        command_status.return_value = {"available": True, "ok": True, "detail": ""}
        status = collect_status(Settings())
        self.assertFalse(status["ready"])
        self.assertEqual(
            status["audio"]["capture"]["detail"],
            "no ALSA capture hardware detected",
        )

    @patch("pilot_room_agent.status._tcp_port_status")
    @patch("pilot_room_agent.status._command_status")
    def test_voice_satellite_connection_is_required_when_enabled(
        self,
        command_status,
        tcp_port_status,
    ) -> None:
        command_status.return_value = {"available": True, "ok": True, "detail": "card 0"}
        tcp_port_status.return_value = {
            "available": True,
            "ok": True,
            "listening": True,
            "client_connected": False,
            "connection_count": 0,
            "port": 6053,
        }
        status = collect_status(Settings(voice_satellite_enabled=True))
        self.assertFalse(status["ready"])
        self.assertFalse(
            status["voice_satellite"]["api"]["home_assistant_connected"]
        )

    def test_tcp_port_status_finds_listener_and_connection(self) -> None:
        fixture = self.create_tempfile(
            "  sl  local_address rem_address   st\n"
            "   0: E401000A:17A5 00000000:0000 0A 00000000:00000000\n"
            "   1: E401000A:17A5 4802000A:E798 01 00000000:00000000\n"
        )
        status = _tcp_port_status(6053, (fixture,))
        self.assertTrue(status["ok"])
        self.assertEqual(status["connection_count"], 1)

    @patch("pilot_room_agent.status._command_status")
    def test_airplay_playback_status_parses_mpris_values(self, command_status) -> None:
        command_status.side_effect = [
            {"available": True, "ok": True, "detail": 's "Playing"'},
            {"available": True, "ok": True, "detail": "d 0.333333"},
        ]
        status = _mpris_playback_status("org.mpris.MediaPlayer2.Test")
        self.assertEqual(status["state"], "Playing")
        self.assertAlmostEqual(status["volume"], 0.333333)

    def test_tcp_remote_port_status_finds_music_assistant(self) -> None:
        fixture = self.create_tempfile(
            "  sl  local_address rem_address   st\n"
            "   0: E401000A:C350 4802000A:22DF 01 00000000:00000000\n"
        )
        status = _tcp_remote_port_status(8927, (fixture,))
        self.assertTrue(status["ok"])
        self.assertEqual(status["connection_count"], 1)

    @patch("pilot_room_agent.status._tcp_remote_port_status")
    @patch("pilot_room_agent.status._sendspin_bus_name")
    @patch("pilot_room_agent.status._command_status")
    def test_music_assistant_connection_is_required(
        self,
        command_status,
        sendspin_bus_name,
        remote_port_status,
    ) -> None:
        command_status.return_value = {
            "available": True,
            "ok": True,
            "detail": "card 0",
        }
        remote_port_status.return_value = {
            "available": True,
            "ok": False,
            "connected": False,
            "connection_count": 0,
            "server_port": 8927,
        }
        sendspin_bus_name.return_value = None
        status = collect_status(Settings(music_assistant_enabled=True))
        self.assertFalse(status["ready"])
        self.assertFalse(status["music_assistant"]["transport"]["connected"])

    @patch("pilot_room_agent.status._mpris_playback_status")
    @patch("pilot_room_agent.status._tcp_port_status")
    @patch("pilot_room_agent.status._command_status")
    def test_airplay_requires_service_and_listener(
        self,
        command_status,
        tcp_port_status,
        playback_status,
    ) -> None:
        command_status.return_value = {
            "available": True,
            "ok": True,
            "detail": "card 0",
        }
        tcp_port_status.return_value = {
            "available": True,
            "ok": True,
            "listening": True,
            "client_connected": False,
            "connection_count": 0,
            "port": 5000,
        }
        playback_status.return_value = {
            "available": True,
            "ok": True,
            "state": "Playing",
            "volume": 0.33,
        }
        status = collect_status(Settings(airplay_enabled=True))
        self.assertTrue(status["ready"])
        self.assertTrue(status["airplay"]["api"]["listening"])
        self.assertEqual(status["airplay"]["playback"]["state"], "Playing")

    def create_tempfile(self, contents: str) -> str:
        handle = tempfile.NamedTemporaryFile(mode="w", delete=False)
        self.addCleanup(Path(handle.name).unlink, missing_ok=True)
        with handle:
            handle.write(contents)
        return handle.name


if __name__ == "__main__":
    unittest.main()
