from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from pilot_core.config import load_settings


VALID_CONFIG = """
[server]
listen_host = "127.0.0.1"
listen_port = 8770

[[rooms]]
id = "office"
name = "Office"
response_player_id = "office-assistant"
default_music_player_id = "office-music"

[[players]]
id = "office-assistant"
room_id = "office"
name = "Office Assistant"
protocol = "pipewire"
kind = "response"

[[players]]
id = "office-music"
room_id = "office"
name = "Pilot Office Music"
protocol = "sendspin"
kind = "music"
"""


class ConfigTests(unittest.TestCase):
    def _load(self, contents: str):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "core.toml"
            path.write_text(contents, encoding="utf-8")
            return load_settings(path)

    def test_loads_valid_registry(self) -> None:
        settings = self._load(VALID_CONFIG)
        self.assertEqual(settings.server.listen_port, 8770)
        self.assertEqual(settings.rooms[0].id, "office")
        self.assertEqual(settings.players[1].protocol, "sendspin")

    def test_rejects_unknown_default_player(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown player"):
            self._load(VALID_CONFIG.replace('default_music_player_id = "office-music"', 'default_music_player_id = "missing"'))

    def test_rejects_duplicate_player_id(self) -> None:
        duplicate = VALID_CONFIG + """
[[players]]
id = "office-music"
room_id = "office"
name = "Duplicate"
protocol = "sendspin"
kind = "music"
"""
        with self.assertRaisesRegex(ValueError, "duplicate player id"):
            self._load(duplicate)


if __name__ == "__main__":
    unittest.main()
