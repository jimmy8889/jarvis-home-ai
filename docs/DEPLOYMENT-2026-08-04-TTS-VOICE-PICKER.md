# Pilot voice picker deployment

Date: 2026-08-04

## Delivered

- Pilot Core exposes device-scoped voice catalogue and preview routes.
- Preview audio is synthesized by the RTX 3080 Qwen3-TTS service and stored as
  a private, five-minute device audio asset.
- iOS Settings now includes a **Pilot voice** picker and Preview action.
- The selected voice is persisted on the phone and sent with subsequent phone
  voice requests; Core's configured voice remains the fallback for other clients.

## Production verification

- Core host: `apps01` (`10.0.1.204`)
- Production image: `core-0.35.1-tts-20260804.3`
- Health: Docker container healthy
- Public authenticated catalogue: `https://pilot.jameshomeautomation.work/v1/devices/{device_id}/tts/voices`
- Verified voice set: `aiden`, `dylan`, `eric`, `ono_anna`, `ryan`, `serena`,
  `sohee`, `uncle_fu`, `vivian`
- Verified authenticated `serena` preview: WAV, 80,684 bytes

## Client build

The iOS project builds successfully for the iOS Simulator with code signing
disabled. Install the new app build on the phone, open Settings, choose a voice
under **Pilot voice**, and tap **Preview**.

## Rollback

The previous Core deployment backup was created by the standard deployment
script on apps01 before replacing the container. Use the existing
`pilot-core-restore` procedure if the production container must be reverted.
