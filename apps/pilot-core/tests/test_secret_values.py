from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

from pilot_core.secret_values import SecretValueError, read_secret


class SecretValueTests(unittest.TestCase):
    def tearDown(self) -> None:
        os.environ.pop("TEST_PILOT_SECRET", None)
        os.environ.pop("TEST_PILOT_SECRET_FILE", None)

    def test_reads_file_backed_secret(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "secret"
            path.write_text("file-secret\n", encoding="utf-8")
            os.environ["TEST_PILOT_SECRET_FILE"] = str(path)
            self.assertEqual(read_secret("TEST_PILOT_SECRET"), "file-secret")

    def test_direct_value_takes_precedence_for_development(self) -> None:
        os.environ["TEST_PILOT_SECRET"] = "direct-secret"
        os.environ["TEST_PILOT_SECRET_FILE"] = "/missing"
        self.assertEqual(read_secret("TEST_PILOT_SECRET"), "direct-secret")

    def test_rejects_non_regular_secret_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            os.environ["TEST_PILOT_SECRET_FILE"] = directory
            with self.assertRaises(SecretValueError):
                read_secret("TEST_PILOT_SECRET")


if __name__ == "__main__":
    unittest.main()
