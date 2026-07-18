from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from pilot_core.firmware import FirmwareReleaseError, FirmwareReleases


class FirmwareReleaseTests(unittest.TestCase):
    def test_validates_and_returns_latest_release(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "esp32-c6-touch-amoled-2.16"
            target.mkdir()
            image = b"pilot-firmware"
            (target / "pilot-display-0.2.0.bin").write_bytes(image)
            (target / "latest.json").write_text(
                json.dumps(
                    {
                        "version": "0.2.0",
                        "filename": "pilot-display-0.2.0.bin",
                        "sha256": hashlib.sha256(image).hexdigest(),
                        "mandatory": False,
                    }
                ),
                encoding="utf-8",
            )
            release = FirmwareReleases(directory, 1_000_000).latest(
                "esp32-c6-touch-amoled-2.16"
            )
            self.assertIsNotNone(release)
            assert release is not None
            self.assertEqual(release.version, "0.2.0")
            self.assertEqual(release.size_bytes, len(image))

    def test_rejects_checksum_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "display"
            target.mkdir()
            (target / "firmware.bin").write_bytes(b"firmware")
            (target / "latest.json").write_text(
                json.dumps(
                    {
                        "version": "0.2.0",
                        "filename": "firmware.bin",
                        "sha256": "0" * 64,
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(FirmwareReleaseError, "checksum"):
                FirmwareReleases(directory, 1_000_000).latest("display")


if __name__ == "__main__":
    unittest.main()
