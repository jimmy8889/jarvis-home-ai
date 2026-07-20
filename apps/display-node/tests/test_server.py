from __future__ import annotations

import json
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

from pilot_display_node.server import (
    _core_device_request,
    _core_status,
    _core_surface,
)


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
    def test_device_media_proxy_keeps_credential_server_side(
        self,
        _read_token: MagicMock,
        urlopen: MagicMock,
    ) -> None:
        response = MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.read.return_value = b'{"player":{"id":"office-music"}}'
        urlopen.return_value = response

        status, result = _core_device_request(
            "http://pilot-core:8770",
            "pilot-display-pi",
            "/etc/pilot-display/device-token",
            "media",
            method="POST",
            payload={"action": "pause", "player_id": "office-music"},
        )

        self.assertEqual(status, 200)
        self.assertEqual(result["player"]["id"], "office-music")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.method, "POST")
        self.assertEqual(
            request.full_url,
            "http://pilot-core:8770/v1/devices/pilot-display-pi/media",
        )
        self.assertEqual(request.headers["Authorization"], "Bearer device-secret")
        self.assertNotIn("device-secret", json.dumps(result))

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

    def test_energy_surface_has_directional_flow_paths(self) -> None:
        static = Path(__file__).parents[1] / "pilot_display_node" / "static"
        html = (static / "index.html").read_text(encoding="utf-8")
        script = (static / "app.js").read_text(encoding="utf-8")
        styles = (static / "styles.css").read_text(encoding="utf-8")

        for name in ("solar", "grid", "battery"):
            self.assertIn(f'id="flow-{name}"', html)
            self.assertIn(f'id="particles-{name}"', html)
        self.assertIn('id="node-home"', html)
        self.assertIn("setFlow(elements.flow_grid", script)
        self.assertIn("grid < 0", script)
        self.assertIn("battery < 0", script)
        self.assertIn("@keyframes energy-flow-forward", styles)
        self.assertIn("@keyframes energy-flow-reverse", styles)
        self.assertIn("cursor: none !important", styles)
        self.assertIn(".flow-particles.reverse .particles-reverse", styles)


if __name__ == "__main__":
    unittest.main()
