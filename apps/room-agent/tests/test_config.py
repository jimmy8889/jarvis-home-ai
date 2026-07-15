from pathlib import Path
import tempfile
import unittest

from pilot_room_agent.config import Settings, load_settings


class ConfigTests(unittest.TestCase):
    def test_missing_config_uses_safe_defaults(self) -> None:
        self.assertEqual(load_settings("/path/that/does/not/exist"), Settings())

    def test_known_values_load_and_unknown_values_are_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "room.toml"
            path.write_text(
                'room_id = "office"\nlisten_port = 9000\nunknown = "ignored"\n',
                encoding="utf-8",
            )
            settings = load_settings(path)
        self.assertEqual(settings.room_id, "office")
        self.assertEqual(settings.listen_port, 9000)


if __name__ == "__main__":
    unittest.main()
