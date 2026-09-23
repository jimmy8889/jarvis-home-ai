# Pilot mobile for Android

Personal Fold client unifying Pilot, James Control, James House Energy and House Energy. The original wall-tablet Android application remains unchanged. Other apps, including Pilot Drive and Pilot Cinema, remain unchanged.

Uses the iPhone Pilot and House Energy artwork and screen groupings. Android appearance follows the phone. On an open Fold, energy charts and room controls are visible side by side, with navigation along the edge.

Pilot snapshots and Control/Energy read responses are encrypted in Android Keystore-backed local storage. Saved readings show their timestamp when offline; home and financial actions require a live connection and are not replayed. Energy control uses a separate paired device and device-authenticated ECDSA proofs; existing iPhone identities are preserved.

Build: `./gradlew :app:assembleRelease :app:testDebugUnitTest :app:lintRelease` with SDK 37. Provisioning files are imported privately and deleted. Never commit device tokens or signing keys. The personal release currently uses this workstation's persistent local signing certificate.

The migration is under active parity review. Live bank MFA and physical energy actions must be tested only when intentionally requested, not as build smoke tests.
