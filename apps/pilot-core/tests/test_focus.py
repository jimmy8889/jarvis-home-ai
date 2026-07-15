from __future__ import annotations

import unittest

from pilot_core.focus import decide_focus


class FocusTests(unittest.TestCase):
    def test_assistant_ducks_music(self) -> None:
        decision = decide_focus({"assistant": True, "music": True})
        self.assertEqual(decision.foreground, "assistant")
        self.assertEqual(decision.gains["assistant"], 1.0)
        self.assertEqual(decision.gains["music"], 0.2)

    def test_airplay_excludes_music(self) -> None:
        decision = decide_focus({"airplay": True, "music": True})
        self.assertEqual(decision.foreground, "airplay")
        self.assertEqual(decision.gains["music"], 0.0)

    def test_critical_has_highest_priority(self) -> None:
        decision = decide_focus(
            {"critical": True, "assistant": True, "bluetooth": True}
        )
        self.assertEqual(decision.foreground, "critical")
        self.assertEqual(decision.gains["assistant"], 0.2)

    def test_rejects_unknown_source(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown audio source"):
            decide_focus({"unknown": True})


if __name__ == "__main__":
    unittest.main()
