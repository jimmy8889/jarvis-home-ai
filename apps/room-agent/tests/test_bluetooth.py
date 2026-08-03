from __future__ import annotations

import subprocess
import unittest

from pilot_room_agent.bluetooth import (
    BluetoothBridge,
    parse_bluetooth_sources,
    parse_loopback_modules,
)
from pilot_room_agent.config import Settings


class BluetoothTests(unittest.TestCase):
    def test_parses_only_bluez_sources_and_running_state(self) -> None:
        sources = parse_bluetooth_sources(
            """
            [
              {"name":"alsa_input.usb-mic","state":"RUNNING","properties":{}},
              {"name":"bluez_input.AA_BB_CC_DD_EE_FF.0","state":"RUNNING",
               "properties":{"device.api":"bluez5"}},
              {"name":"bluez_input.11_22_33_44_55_66.0","state":"SUSPENDED",
               "properties":{}}
            ]
            """
        )
        self.assertEqual(len(sources), 2)
        activity = {source.name: source.active for source in sources}
        self.assertTrue(activity["bluez_input.AA_BB_CC_DD_EE_FF.0"])
        self.assertFalse(activity["bluez_input.11_22_33_44_55_66.0"])

    def test_parses_managed_loopback_modules(self) -> None:
        modules = parse_loopback_modules(
            "12\tmodule-loopback\tsource=bluez_input.AA.0 sink=office "
            "sink_input_properties=application.name=PilotBluetooth\n"
            "13\tmodule-loopback\tsource=alsa_input.usb sink=office\n"
        )
        self.assertEqual(modules, {"bluez_input.AA.0": 12})

    def test_bridge_loads_and_unloads_loopback(self) -> None:
        calls: list[list[str]] = []
        source_present = True

        def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
            nonlocal source_present
            calls.append(command)
            if command[1:4] == ["--format=json", "list", "sources"]:
                payload = (
                    '[{"name":"bluez_input.AA.0","state":"RUNNING",'
                    '"properties":{"device.api":"bluez5"}}]'
                    if source_present
                    else "[]"
                )
                return subprocess.CompletedProcess(command, 0, payload, "")
            if command[1:4] == ["list", "short", "modules"]:
                return subprocess.CompletedProcess(command, 0, "", "")
            if command[1:3] == ["load-module", "module-loopback"]:
                return subprocess.CompletedProcess(command, 0, "42\n", "")
            if command[1] == "unload-module":
                return subprocess.CompletedProcess(command, 0, "", "")
            return subprocess.CompletedProcess(command, 1, "", "unexpected")

        bridge = BluetoothBridge(
            Settings(
                speaker_node="alsa_output.office",
                bluetooth_loopback_latency_ms=90,
            ),
            runner,
        )
        bridge.reconcile_once()
        self.assertTrue(bridge.snapshot()["active"])
        self.assertEqual(bridge.snapshot()["loopbacks"], 1)
        load = next(call for call in calls if "load-module" in call)
        self.assertIn("sink=alsa_output.office", load)
        self.assertIn("latency_msec=90", load)
        self.assertIn("sink_input_properties=application.name=PilotBluetooth", load)

        source_present = False
        bridge.reconcile_once()
        self.assertFalse(bridge.snapshot()["connected"])
        self.assertIn(["pactl", "unload-module", "42"], calls)

    def test_bridge_fails_closed_when_source_inventory_fails(self) -> None:
        def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(command, 1, "", "server unavailable")

        bridge = BluetoothBridge(Settings(), runner)
        bridge.reconcile_once()
        self.assertFalse(bridge.snapshot()["ok"])
        self.assertEqual(bridge.snapshot()["last_error"], "server unavailable")


if __name__ == "__main__":
    unittest.main()
