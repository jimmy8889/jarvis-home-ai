from __future__ import annotations

from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
import subprocess
from threading import Thread
import unittest

from pilot_room_agent.config import Settings
from pilot_room_agent.controls import ControlState, RoomController
from pilot_room_agent.main import Handler


class QuietHandler(Handler):
    def log_message(self, format: str, *args: object) -> None:
        pass


class ControlApiTests(unittest.TestCase):
    def setUp(self) -> None:
        state = ControlState()
        QuietHandler.settings = Settings(room_id="test-room")
        QuietHandler.control_state = state
        QuietHandler.audio_playback = None
        QuietHandler.command_client = None
        QuietHandler.controller = RoomController(
            state,
            runner=lambda command: subprocess.CompletedProcess(command, 0, "", ""),
            sendspin_bus_resolver=lambda: "org.mpris.MediaPlayer2.Sendspin.test",
            airplay_bus_resolver=lambda: "org.mpris.MediaPlayer2.ShairportSync",
        )
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, body: object) -> tuple[int, dict[str, object]]:
        connection = HTTPConnection(*self.server.server_address, timeout=2)
        connection.request(
            "POST",
            "/v1/control",
            body=json.dumps(body),
            headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        payload = json.loads(response.read())
        connection.close()
        return response.status, payload

    def test_control_endpoint_updates_listening_state(self) -> None:
        status, payload = self.request(
            {"action": "start_listening", "ttl_seconds": 20}
        )
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["state"]["listening"])

    def test_control_endpoint_rejects_invalid_command(self) -> None:
        status, payload = self.request({"action": "unknown"})
        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])


if __name__ == "__main__":
    unittest.main()
