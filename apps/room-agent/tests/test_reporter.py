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
            {
                "critical": False,
                "assistant": False,
                "bluetooth": False,
                "airplay": False,
                "music": True,
            },
        )

    def test_transient_focus_is_included(self) -> None:
        self.assertEqual(
            EventReporter.source_states(
                {}, {"critical": True, "assistant": True}
            ),
            {
                "critical": True,
                "assistant": True,
                "bluetooth": False,
                "airplay": False,
                "music": False,
            },
        )

    def test_missing_playback_is_inactive(self) -> None:
        self.assertEqual(
            EventReporter.source_states({}),
            {
                "critical": False,
                "assistant": False,
                "bluetooth": False,
                "airplay": False,
                "music": False,
            },
        )


if __name__ == "__main__":
    unittest.main()
