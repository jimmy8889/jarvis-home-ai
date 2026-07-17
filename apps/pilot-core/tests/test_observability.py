from __future__ import annotations

from datetime import UTC, datetime, timedelta
import unittest

from pilot_core.observability import (
    evaluate_observability,
    prometheus_metrics,
)


class ObservabilityTests(unittest.TestCase):
    def snapshot(self) -> dict:
        generated = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)
        return {
            "generated_at": generated.isoformat(),
            "summary": {
                "room_count": 1,
                "device_count": 1,
                "connected_device_count": 1,
                "pending_command_count": 0,
            },
            "safety": {
                "audible_actions_gated": True,
                "unarmed_rooms": ["office"],
            },
            "integrations": {
                "music_assistant": {
                    "configured": True,
                    "status": "ok",
                },
                "tts": {
                    "configured": False,
                    "status": "not_configured",
                },
            },
            "rooms": {
                "office": {
                    "devices": [
                        {
                            "id": "pilot-office",
                            "name": "Office N150",
                            "connected": True,
                            "health": {
                                "updated_at": (
                                    generated - timedelta(seconds=20)
                                ).isoformat(),
                                "payload": {
                                    "ready": True,
                                    "audio_activation": {"allowed": False},
                                },
                            },
                        }
                    ]
                }
            },
            "media": {
                "players": {
                    "office-music": {
                        "status": "ok",
                        "player": {
                            "room_id": "office",
                            "name": "Office Music",
                            "control_enabled": True,
                            "kind": "music",
                        },
                    },
                    "office-assistant": {
                        "status": "unresolved",
                        "player": {
                            "room_id": "office",
                            "name": "Office Assistant",
                            "control_enabled": True,
                            "kind": "response",
                        },
                    }
                }
            },
        }

    def test_healthy_but_gated_snapshot_is_guarded(self) -> None:
        snapshot = self.snapshot()
        result = evaluate_observability(snapshot)
        self.assertEqual(result["status"], "guarded")
        self.assertEqual(result["summary"]["warning_alert_count"], 0)
        self.assertEqual(result["alerts"][0]["code"], "AUDIO_GATED")
        self.assertEqual(
            {check["status"] for check in result["checks"]},
            {"ok", "not_configured"},
        )

    def test_stale_device_and_unresolved_player_are_degraded(self) -> None:
        snapshot = self.snapshot()
        snapshot["rooms"]["office"]["devices"][0]["health"]["updated_at"] = datetime(
            2026, 7, 17, 11, 55, tzinfo=UTC
        ).isoformat()
        snapshot["media"]["players"]["office-music"]["status"] = "unresolved"
        result = evaluate_observability(snapshot)
        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["summary"]["stale_device_count"], 1)
        self.assertEqual(result["summary"]["unresolved_player_count"], 1)
        self.assertEqual(result["summary"]["warning_alert_count"], 2)

    def test_prometheus_metrics_have_bounded_labels(self) -> None:
        snapshot = self.snapshot()
        result = evaluate_observability(snapshot)
        metrics = prometheus_metrics(snapshot, result)
        self.assertIn("pilot_core_up 1", metrics)
        self.assertIn(
            'pilot_core_device_connected{room_id="office",device_id="pilot-office"} 1',
            metrics,
        )
        self.assertIn(
            'pilot_core_observability_status{status="guarded"} 1',
            metrics,
        )


if __name__ == "__main__":
    unittest.main()
