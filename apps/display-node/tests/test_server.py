from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from pilot_display_node.server import _core_status


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


if __name__ == "__main__":
    unittest.main()
