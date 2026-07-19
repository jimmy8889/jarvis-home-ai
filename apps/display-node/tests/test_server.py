from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from pilot_display_node.server import _core_status, _core_surface


class CoreStatusTests(unittest.TestCase):
    def test_rejects_non_http_core_url(self) -> None:
        self.assertEqual(
            _core_status("file:///etc/passwd"),
            {"connected": False, "error": "invalid Pilot Core URL"},
        )

    @patch("pilot_display_node.server.urlopen")
    def test_returns_bounded_ready_state(self, urlopen: MagicMock) -> None:
        response = MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.read.return_value = json.dumps(
            {
                "ready": True,
                "registry_revision": "abc123",
                "room_count": 3,
                "player_count": 8,
                "tts_configured": True,
                "assistant": {"session_owner": "pilot_core"},
                "not_public": "discarded",
            }
        ).encode()
        urlopen.return_value = response

        self.assertEqual(
            _core_status("http://pilot-core:8770"),
            {
                "connected": True,
                "registry_revision": "abc123",
                "room_count": 3,
                "player_count": 8,
                "tts_configured": True,
                "assistant": {"session_owner": "pilot_core"},
            },
        )

    def test_surface_fails_closed_without_device_credentials(self) -> None:
        self.assertEqual(
            _core_surface("http://pilot-core:8770", "", ""),
            {"status": "not_configured"},
        )

    @patch("pilot_display_node.server.urlopen")
    @patch("pilot_display_node.server._bounded_text", return_value="device-secret")
    def test_surface_proxies_bounded_payload_without_exposing_token(
        self,
        _read_token: MagicMock,
        urlopen: MagicMock,
    ) -> None:
        response = MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.read.return_value = json.dumps(
            {
                "device_id": "pilot-display-pi",
                "energy": {"status": "ok", "solar": {"value": 1234}},
                "now_playing": {"status": "ok", "items": []},
            }
        ).encode()
        urlopen.return_value = response

        result = _core_surface(
            "http://pilot-core:8770",
            "pilot-display-pi",
            "/etc/pilot-display/device-token",
        )
        self.assertEqual(result["energy"]["solar"]["value"], 1234)
        request = urlopen.call_args.args[0]
        self.assertEqual(request.headers["Authorization"], "Bearer device-secret")
        self.assertNotIn("device-secret", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
