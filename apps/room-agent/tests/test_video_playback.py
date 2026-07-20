from pathlib import Path
import tempfile
import unittest

from pilot_room_agent.config import Settings
from pilot_room_agent.controls import ControlError
from pilot_room_agent.video_playback import MpvPlayback


class FakeMpvPlayback(MpvPlayback):
    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.commands: list[list[object]] = []

    def _ensure_started(self) -> None:
        return

    def _command(self, command: list[object]) -> dict[str, object]:
        self.commands.append(command)
        return {"error": "success"}

    def status(self) -> dict[str, object]:
        return {"enabled": True, "available": True}


class MpvPlaybackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = tempfile.TemporaryDirectory()
        path = Path(self.root.name) / "Films" / "Example.mkv"
        path.parent.mkdir()
        path.write_bytes(b"test")
        self.player = FakeMpvPlayback(
            Settings(
                video_enabled=True,
                video_media_roots=(self.root.name,),
            )
        )

    def tearDown(self) -> None:
        self.root.cleanup()

    def test_loads_only_relative_item_inside_configured_library(self) -> None:
        result = self.player.execute(
            "video_play",
            {"media_id": "Films/Example.mkv"},
        )
        self.assertEqual(result["state"], "loading")
        self.assertEqual(self.player.commands[0][0:2], ["loadfile", str(
            Path(self.root.name, "Films", "Example.mkv").resolve()
        )])

    def test_rejects_path_traversal_absolute_paths_and_unknown_types(self) -> None:
        for media_id in (
            "../etc/passwd",
            "/etc/passwd",
            r"Films\Example.mkv",
            "Films/Example.sh",
            "Films/Missing.mkv",
        ):
            with self.subTest(media_id=media_id):
                with self.assertRaises(ControlError):
                    self.player.execute("video_play", {"media_id": media_id})

    def test_seek_and_track_selection_are_bounded_typed_commands(self) -> None:
        self.player.execute("video_seek", {"seconds": 30})
        self.player.execute("video_audio_track", {"track": 2})
        self.player.execute("video_subtitle_track", {"track": 0})
        self.assertEqual(
            self.player.commands,
            [
                ["seek", 30.0, "relative+exact"],
                ["set_property", "aid", 2],
                ["set_property", "sid", "no"],
            ],
        )
        with self.assertRaisesRegex(ControlError, "between -3600 and 3600"):
            self.player.execute("video_seek", {"seconds": 10_000})
        with self.assertRaisesRegex(ControlError, "between 0 and 128"):
            self.player.execute("video_audio_track", {"track": 999})


if __name__ == "__main__":
    unittest.main()
