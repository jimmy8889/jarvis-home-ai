from __future__ import annotations

import json
import os
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
    _prune_artwork_cache,
    _performance_profile,
    _static_cache_control,
    status_payload,
)


class CoreStatusTests(unittest.TestCase):
    def test_performance_profile_auto_detects_raspberry_pi(self) -> None:
        self.assertEqual(
            _performance_profile("auto", "Raspberry Pi 4 Model B Rev 1.5"),
            "low-power",
        )
        self.assertEqual(_performance_profile("auto", "Intel N150"), "balanced")
        self.assertEqual(
            _performance_profile("balanced", "Raspberry Pi 4 Model B"),
            "balanced",
        )

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

    def test_artwork_cache_is_bounded_by_age_count_and_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            now = 10_000.0
            fixtures = {
                "expired": (12, now - 500),
                "oldest": (20, now - 30),
                "middle": (25, now - 20),
                "newest": (30, now - 10),
            }
            for name, (size, modified) in fixtures.items():
                path = root / name
                path.write_bytes(b"x" * size)
                os.utime(path, (modified, modified))

            _prune_artwork_cache(
                root,
                max_age_seconds=100,
                max_items=2,
                max_bytes=50,
                now=now,
            )

            self.assertFalse((root / "expired").exists())
            self.assertFalse((root / "oldest").exists())
            self.assertFalse((root / "middle").exists())
            self.assertTrue((root / "newest").exists())

    def test_stable_static_asset_names_are_revalidated(self) -> None:
        policy = _static_cache_control("/assets/house-day.png")
        self.assertEqual(policy, "public, max-age=0, must-revalidate")
        self.assertNotIn("immutable", policy)

    @patch("pilot_display_node.server._core_surface", return_value={})
    @patch("pilot_display_node.server._core_status", return_value={"connected": True})
    def test_local_video_is_explicitly_gated(
        self,
        _core_status: MagicMock,
        _core_surface: MagicMock,
    ) -> None:
        disabled = status_payload("http://pilot-core:8770")
        enabled = status_payload("http://pilot-core:8770", video_enabled=True)

        self.assertEqual(disabled["features"], {"local_video": False})
        self.assertEqual(enabled["features"], {"local_video": True})

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

        for name in ("solar", "grid", "battery", "home"):
            self.assertIn(f'id="flow-{name}"', html)
            self.assertIn(f'id="particles-{name}"', html)
        self.assertIn('id="node-home"', html)
        self.assertIn('class="flow-base home-flow-base"', html)
        self.assertIn('id="particles-home"', html)
        self.assertIn("setFlow(elements.flow_grid", script)
        self.assertIn("setFlow(elements.flow_home, elements.particles_home", script)
        self.assertIn("grid < 0", script)
        self.assertIn("battery < 0", script)
        self.assertIn('"battery-feeding-home"', script)
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
        self.assertIn('const fallback = normalized === "media-console" ? "media" : "home";', script)
        self.assertIn("window.history.replaceState", script)
        self.assertIn("showPage(target);", script)
        self.assertIn("value.features?.local_video === true", script)
        self.assertIn('id="console-video-target"', html)
        self.assertIn("disabled", html)
        self.assertIn('const isDay = typeof configuredDay === "boolean" ? configuredDay : false;', script)
        self.assertIn('image.removeAttribute("src")', script)
        self.assertNotIn("renderNowPlaying(value.surface", script)
        self.assertIn(".onscreen-keyboard", styles)
        self.assertIn("Showing the last known state", styles)
        self.assertIn('value.performance_profile', script)
        self.assertIn('flowDiagram?.pauseAnimations?.()', script)
        self.assertIn("pilot-chart-gradient-", script)
        self.assertIn("visibleHistorySegments", script)
        self.assertIn('item.render_mode === "step"', script)
        self.assertIn("Math.abs(battery) >= 100", script)
        self.assertIn(".battery-flow-base", styles)
        self.assertIn(".vehicle-flow-base", styles)
        self.assertIn("value.history?.started_at", script)
        self.assertIn("showTimeAxis: true", script)
        self.assertIn("loads plotted below zero from midnight to midnight", html)
        self.assertIn("Today · midnight to midnight", html)
        self.assertIn('window.matchMedia("(prefers-reduced-motion: reduce)")', script)
        self.assertIn("!homeVisible || reducedMotion.matches", script)
        self.assertIn('data-performance-profile="low-power"', styles)
        self.assertIn("steps(var(--flow-steps, 36), end)", styles)
        self.assertIn("Math.round(speedSeconds * 10)", script)
        self.assertIn("bounded 10 visual updates per second", styles)
        self.assertIn("shape-rendering: optimizeSpeed", styles)
        self.assertIn('.solar-flow { stroke: #ffc247; }', styles)
        self.assertIn(".home-particles circle", styles)
        self.assertIn(".motion-paused .energy-house", styles)
        self.assertIn('path.style.setProperty("--flow-steps", steps)', script)
        self.assertIn("battery-charge-efficient", styles)
        self.assertIn(".motion-paused .flow-active.active", styles)

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

    def test_n150_display_audio_is_opt_in_and_room_agent_owned(self) -> None:
        repository = Path(__file__).parents[3]
        role = repository / "deploy" / "ansible" / "roles" / "display_node"
        defaults = (role / "defaults" / "main.yml").read_text(encoding="utf-8")
        tasks = (role / "tasks" / "main.yml").read_text(encoding="utf-8")
        inventory = (
            repository / "deploy" / "ansible" / "inventory" / "hosts.example.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("display_node_audio_services_enabled: false", defaults)
        self.assertIn("Assert display audio ownership is explicit", tasks)
        self.assertIn("when: display_node_audio_services_enabled | bool", tasks)
        self.assertIn("Mask display-user audio services when Room Agent owns audio", tasks)
        self.assertIn("systemctl --user mask --now", tasks)
        self.assertIn("when: not (display_node_audio_services_enabled | bool)", tasks)
        self.assertIn("display_node_audio_services_enabled: false", inventory)
        self.assertIn("display_node_sendspin_enabled: false", inventory)
        self.assertIn("display_node_performance_profile: auto", defaults)
        self.assertIn("PILOT_DISPLAY_PERFORMANCE_PROFILE", (
            role / "templates" / "pilot-display.env.j2"
        ).read_text(encoding="utf-8"))
        self.assertIn("display_node_performance_profile: low-power", inventory)


if __name__ == "__main__":
    unittest.main()
