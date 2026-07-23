from __future__ import annotations

import importlib.util
from pathlib import Path
import tarfile
import tempfile
import unittest


MODULE_PATH = Path(__file__).parents[1] / "volume_archive.py"
SPEC = importlib.util.spec_from_file_location("pilot_volume_archive", MODULE_PATH)
assert SPEC and SPEC.loader
volume_archive = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(volume_archive)


class VolumeArchiveTests(unittest.TestCase):
    def test_round_trip_preserves_and_verifies_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "pilot.db").write_bytes(b"sqlite-data")
            (source / "audio").mkdir()
            (source / "audio" / "reply.wav").write_bytes(b"RIFF-test")
            archive = root / "backup.tar.gz"
            manifest = volume_archive.create_backup(source, archive)
            self.assertEqual(len(manifest["files"]), 2)

            (source / "pilot.db").write_bytes(b"changed")
            (source / "unwanted").write_text("remove me", encoding="utf-8")
            volume_archive.restore_backup(archive, source)
            self.assertEqual((source / "pilot.db").read_bytes(), b"sqlite-data")
            self.assertEqual(
                (source / "audio" / "reply.wav").read_bytes(), b"RIFF-test"
            )
            self.assertFalse((source / "unwanted").exists())

    def test_restore_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "malicious.tar.gz"
            with tarfile.open(archive, "w:gz") as bundle:
                info = tarfile.TarInfo("../outside")
                info.size = 0
                bundle.addfile(info)
            destination = root / "destination"
            with self.assertRaisesRegex(volume_archive.ArchiveError, "unsafe"):
                volume_archive.restore_backup(archive, destination)
            self.assertFalse((root / "outside").exists())


if __name__ == "__main__":
    unittest.main()
