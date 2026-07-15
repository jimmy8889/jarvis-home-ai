from __future__ import annotations

import unittest

from pilot_room_agent.reporter import EventReporter


class ReporterTests(unittest.TestCase):
    def test_source_states_follow_mpris_playback(self) -> None:
        status = {
            "airplay": {"playback": {"state": "Stopped"}},
            "music_assistant": {"playback": {"state": "Playing"}},
        }
        self.assertEqual(
            EventReporter.source_states(status),
            {"airplay": False, "music": True},
        )

    def test_missing_playback_is_inactive(self) -> None:
        self.assertEqual(
            EventReporter.source_states({}),
            {"airplay": False, "music": False},
        )


if __name__ == "__main__":
    unittest.main()
