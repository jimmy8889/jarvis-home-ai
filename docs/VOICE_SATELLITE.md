# Local voice satellite

Pilot uses the Open Home Foundation Linux Voice Assistant runtime for the first
Home Assistant voice-satellite integration. The deployment pins a stable release
instead of tracking `main` or `latest`.

Initial office settings:

```text
Runtime: OHF-Voice/linux-voice-assistant v1.1.12
Protocol: ESPHome API on TCP 6053
Input: Stadium USB microphone through PipeWire/Pulse compatibility
Output: FiiO K3 through PipeWire/Pulse compatibility
Channels: mono input
Temporary wake model: okay_nabu
Target custom phrase: Hey Pilot
```

The role installs the runtime first with its service disabled. This permits an
operator to enumerate and verify the exact input and output names before enabling
continuous wake-word capture. The office enumeration selected:

```text
Input:  Stadium USB microphone Mono
Output: pipewire/alsa_output.usb-FiiO_K3-00.analog-stereo
```

After the service is enabled and healthy, Home Assistant should discover
`lva-e051d81d452f`. If it does not, open **Settings → Devices & services → Add
integration → ESPHome**, then enter `10.0.1.53` and port `6053`. The native
endpoint is assigned to the **Office** area and the **Full local assistant**
pipeline. The wake word runs locally; audio following a trigger is sent to that
Home Assistant pipeline.

The production pipeline ID is pinned in Pilot Core instead of inheriting Home
Assistant's global preferred pipeline. This is intentional: the preferred
pipeline may use a conversation model without STT or TTS, while
`Full local assistant` owns the known-local Faster Whisper and Piper engines.

Verify the endpoint with:

```bash
systemctl status pilot-linux-voice-assistant
pilot-validate
ss -lntp | grep ':6053'
avahi-browse -rt _esphomelib._tcp
```

For the initial test, say **“Okay Nabu”**. `Hey Pilot` requires a separately
trained and deployed wake-word model.

Engine acceptance is separate from physical room acceptance:

```bash
deploy/scripts/pilot-voice-acceptance \
  --core-url http://10.0.1.64:8770
```

This test proves Piper-to-Faster-Whisper locally without producing room audio.
Then say the wake phrase and confirm transcription, Home Assistant action, and
the spoken response through the K3. The N150 journal records the received TTS
proxy URL, which proves delivery to the satellite but does not replace a human
audibility check.

The runtime source and virtual environment live in a versioned directory under
`/opt/pilot/vendor`. Preferences and downloaded models live under
`/var/lib/pilot/lva`, outside the versioned source tree.
