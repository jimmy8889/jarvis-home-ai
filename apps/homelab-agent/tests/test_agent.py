from __future__ import annotations

import unittest
from unittest.mock import patch

from pilot_homelab_agent.main import gpus, max_interval


class AgentTests(unittest.TestCase):
    def test_nvidia_csv_is_normalized(self) -> None:
        completed = type("Completed", (), {"stdout": "0, NVIDIA RTX 3090, 42, 1024, 24576, 61, 184.5\n"})()
        with patch("pilot_homelab_agent.main.shutil.which", return_value="/usr/bin/nvidia-smi"), patch(
            "pilot_homelab_agent.main.subprocess.run", return_value=completed
        ):
            result = gpus()
        self.assertEqual(result[0]["name"], "NVIDIA RTX 3090")
        self.assertEqual(result[0]["utilization_ratio"], 0.42)
        self.assertEqual(result[0]["memory_total_bytes"], 24576 * 1024 * 1024)

    def test_interval_is_bounded(self) -> None:
        self.assertEqual(max_interval("15"), 15)
        with self.assertRaises(Exception):
            max_interval("2")


if __name__ == "__main__":
    unittest.main()
