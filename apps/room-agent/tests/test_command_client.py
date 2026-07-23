from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from typing import Callable

from pilot_room_agent.command_client import CommandClient, CommandJournal
from pilot_room_agent.config import Settings
from pilot_room_agent.controls import ControlState, RoomController


class FakeSocket:
    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []

    def send(self, message: str) -> None:
        self.sent.append(json.loads(message))


class ScriptedSocket(FakeSocket):
    def __init__(self, messages: list[str]) -> None:
        super().__init__()
        self.messages = messages
        self.finished: Callable[[], None] | None = None

    def __enter__(self) -> "ScriptedSocket":
        return self

    def __exit__(self, *args: object) -> None:
        pass

    def recv(self, timeout: float) -> str:
        if self.messages:
            return self.messages.pop(0)
        assert self.finished is not None
        self.finished()
        raise TimeoutError


class CommandClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.commands: list[list[str]] = []

        def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
            self.commands.append(command)
            return subprocess.CompletedProcess(command, 0, "", "")

        settings = Settings(
            room_id="office",
            core_url="https://pilot.example/base/",
            core_device_id="office n150",
            core_command_journal_path=":memory:",
        )
        controller = RoomController(
            ControlState(),
            runner=runner,
            sendspin_bus_resolver=lambda: "org.mpris.MediaPlayer2.Sendspin.test",
            airplay_bus_resolver=lambda: "org.mpris.MediaPlayer2.ShairportSync",
        )
        self.journal = CommandJournal(":memory:")
        self.client = CommandClient(
            settings, controller, journal=self.journal
        )

    def tearDown(self) -> None:
        self.journal.close()

    def test_http_core_url_is_converted_to_device_websocket(self) -> None:
        self.assertEqual(
            self.client.websocket_url(),
            "wss://pilot.example/base/v1/devices/ws?device_id=office%20n150",
        )

    def test_command_is_executed_and_result_is_journaled(self) -> None:
        socket = FakeSocket()
        message = json.dumps(
            {
                "type": "command",
                "command": {
                    "id": 42,
                    "payload": {
                        "action": "set_volume",
                        "source": "room",
                        "volume": 0.4,
                    },
                },
            }
        )
        self.client._handle_message(socket, message)
        self.assertEqual(socket.sent[0]["status"], "succeeded")
        self.assertEqual(self.commands[-1][-1], "0.4000")
        self.assertEqual(self.journal.get(42), socket.sent[0])

    def test_replayed_command_returns_cached_result_without_execution(self) -> None:
        socket = FakeSocket()
        message = json.dumps(
            {
                "type": "command",
                "command": {
                    "id": 7,
                    "payload": {"action": "pause", "source": "music"},
                },
            }
        )
        self.client._handle_message(socket, message)
        self.client._handle_message(socket, message)
        self.assertEqual(len(self.commands), 1)
        self.assertEqual(socket.sent[0], socket.sent[1])

    def test_failed_command_is_journaled_for_idempotent_retry(self) -> None:
        socket = FakeSocket()
        self.client._handle_message(
            socket,
            json.dumps(
                {
                    "type": "command",
                    "command": {
                        "id": 99,
                        "payload": {"action": "set_volume", "volume": 2},
                    },
                }
            ),
        )
        self.assertEqual(socket.sent[0]["status"], "failed")
        self.assertFalse(socket.sent[0]["result"]["ok"])
        self.assertIsNotNone(self.journal.get(99))

    def test_run_once_authenticates_and_processes_server_command(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            token_path = Path(directory) / "token"
            token_path.write_text("device-secret\n", encoding="utf-8")
            settings = Settings(
                room_id="office",
                core_url="http://pilot-core:8770",
                core_device_id="pilot-office",
                core_device_token_file=str(token_path),
                core_command_journal_path=":memory:",
            )
            socket = ScriptedSocket(
                [
                    json.dumps({"type": "hello"}),
                    json.dumps(
                        {
                            "type": "command",
                            "command": {
                                "id": 123,
                                "payload": {"action": "cancel"},
                            },
                        }
                    ),
                ]
            )
            connection: dict[str, object] = {}

            def connector(url: str, **kwargs: object) -> ScriptedSocket:
                connection["url"] = url
                connection.update(kwargs)
                return socket

            journal = CommandJournal(":memory:")
            client = CommandClient(
                settings,
                self.client.controller,
                connector=connector,
                journal=journal,
            )
            socket.finished = client.stop_event.set
            try:
                client.run_once()
            finally:
                journal.close()
            self.assertEqual(
                connection["url"],
                "ws://pilot-core:8770/v1/devices/ws?device_id=pilot-office",
            )
            self.assertEqual(
                connection["additional_headers"],
                {"Authorization": "Bearer device-secret"},
            )
            self.assertEqual(socket.sent[0]["command_id"], 123)


if __name__ == "__main__":
    unittest.main()
