from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from pilot_display_node.server import (
    _core_device_request,
    _core_status,
    _core_surface,
    _cached_artwork,
    _artwork_url_allowed,
)


class CoreStatusTests(unittest.TestCase):
    def test_artwork_proxy_allows_only_configured_https_hosts(self) -> None:
        hosts = ("resources.tidal.com",)
        self.assertTrue(
            _artwork_url_allowed(
                "https://resources.tidal.com/images/example/750x750.jpg", hosts
            )
        )
        self.assertTrue(
            _artwork_url_allowed("https://cdn.resources.tidal.com/art.jpg", hosts)
        )
        self.assertFalse(
            _artwork_url_allowed("http://resources.tidal.com/art.jpg", hosts)
        )
        self.assertFalse(
            _artwork_url_allowed("https://resources.tidal.com.example/art.jpg", hosts)
        )
        self.assertFalse(_artwork_url_allowed("https://127.0.0.1/admin", hosts))

    @patch("pilot_display_node.server.urlopen")
    def test_artwork_is_validated_and_cached_locally(self, urlopen: MagicMock) -> None:
        png = b"\x89PNG\r\n\x1a\n" + (b"image" * 32)
        response = MagicMock()
        response.__enter__.return_value = response
        response.geturl.return_value = "https://resources.tidal.com/images/cover.png"
        response.read.return_value = png
        urlopen.return_value = response

        with tempfile.TemporaryDirectory() as directory:
            first = _cached_artwork(
                "https://resources.tidal.com/images/cover.png",
                Path(directory),
                ("resources.tidal.com",),
            )
            second = _cached_artwork(
                "https://resources.tidal.com/images/cover.png",
                Path(directory),
                ("resources.tidal.com",),
            )

        self.assertEqual(first, (png, "image/png"))
        self.assertEqual(second, first)
        urlopen.assert_called_once()

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
        self.assertIn('id="onscreen-keyboard"', html)
        self.assertIn('aria-label="QWERTY keys"', html)
        self.assertIn('["1234567890", "QWERTYUIOP", "ASDFGHJKL", "ZXCVBNM"]', script)
        self.assertIn(".onscreen-keyboard[hidden]", styles)
        self.assertIn("body.keyboard-open main", styles)
        self.assertIn("pilot-display-selected-output", script)
        self.assertIn("lastSuccessfulUpdate", script)
        self.assertIn("effective.position_seconds", script)
        self.assertIn("observedAt < lastMediaObservedAt", script)
        self.assertIn("room.id === deviceRoomId", script)
        self.assertNotIn("renderNowPlaying(value.surface", script)
        self.assertIn(".onscreen-keyboard", styles)
        self.assertIn("Showing the last known state", styles)

    def test_dashboard_assets_and_media_console_are_packaged(self) -> None:
        static = Path(__file__).parents[1] / "pilot_display_node" / "static"
        html = (static / "index.html").read_text(encoding="utf-8")
        script = (static / "app.js").read_text(encoding="utf-8")
        styles = (static / "styles.css").read_text(encoding="utf-8")

        for scene in (
            "house-day.png",
            "house-day-tesla.png",
            "house-night.png",
            "house-night-tesla.png",
        ):
            self.assertGreater((static / "assets" / scene).stat().st_size, 100_000)
            self.assertIn(f'"/assets/{scene}"', script)
        server = (static.parent / "server.py").read_text(encoding="utf-8")
        for scene in (
            "house-day.png",
            "house-day-tesla.png",
            "house-night.png",
            "house-night-tesla.png",
        ):
            self.assertIn(f'"/assets/{scene}"', server)
        self.assertIn("value.scene?.is_day", script)
        self.assertIn("power.solar_w >= 100", script)
        self.assertIn("transition: opacity 450ms ease", styles)
        self.assertIn('data-page="media"', html)
        self.assertIn('id="music-results"', html)
        self.assertIn('id="console-video-input"', html)
        self.assertIn('id="console-artwork"', html)
        self.assertIn('id="console-energy-solar"', html)
        self.assertIn('data-console-media-action="previous"', html)
        self.assertIn('postJSON("/api/media/browse"', script)
        self.assertIn('postJSON("/api/video"', script)
        self.assertIn("resultArtwork", script)
        self.assertIn("/api/artwork?url=", script)
        self.assertIn(".media-console-stage", styles)


if __name__ == "__main__":
    unittest.main()
