import unittest

from pilot_room_agent.audio_defaults import parse_node_ids


class AudioDefaultsTests(unittest.TestCase):
    def test_parses_default_and_non_default_nodes(self) -> None:
        status = """
     │   55. alsa_input.usb-Stadium_USB_microphone.mono-fallback
     │ * 67. alsa_output.usb-FiiO_K3-00.analog-stereo [vol: 0.40]
        """
        self.assertEqual(
            parse_node_ids(status),
            {
                "alsa_input.usb-Stadium_USB_microphone.mono-fallback": 55,
                "alsa_output.usb-FiiO_K3-00.analog-stereo": 67,
            },
        )

    def test_ignores_non_node_lines(self) -> None:
        self.assertEqual(parse_node_ids("Audio\n ├─ Devices:\nSettings"), {})


if __name__ == "__main__":
    unittest.main()
