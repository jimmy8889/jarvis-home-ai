# Pilot Watch meeting capture

Pilot includes a watchOS 10 companion for explicit, local-first meeting
recording. The Watch records without requiring the user to take out the
iPhone, then relays the recording through the paired iPhone to the original
device-authenticated Pilot Core meeting routes.

## Trust and deletion boundary

The Watch never receives or stores a Pilot Core token. Its only network trust
relationship is the paired iPhone through Watch Connectivity. The iPhone keeps
the existing device token in its Keychain and uses it only with the paired Core
origin for requests protected by the device ID and `meetings` capability.

If Core advertises a different upload origin, iPhone first obtains a
short-lived, single-upload ticket from the paired Core. The ticket is bound to
the meeting, device credential revision, byte count, and SHA-256. The upload
origin receives only that scoped ticket: it never receives the reusable device
bearer or `X-Pilot-Device-ID`. A missing or invalid ticket fails closed to the
same-origin Core upload route.

Before creating an upload task, iPhone verifies the returned ticket's meeting
ID, filename, normalized content type, SHA-256, and byte count against the
retained capture. Core enforces the expected byte count while streaming (before
writing an overflowing chunk), then verifies the final digest before commit.

There are two durable copies during delivery:

1. Watch stores the AAC M4A and a manifest-backed outbox entry.
2. iPhone synchronously copies the temporary Watch Connectivity file into
   Application Support, verifies its advertised byte count and SHA-256, and
   persists an inbox record before acknowledging `durable_received`.
3. iPhone creates the Core meeting, uploads the M4A with a background
   `URLSession`, and queues `/process`.
4. Only after Core accepts both the upload and processing request does iPhone
   acknowledge `core_accepted`; both devices may then delete their audio copy.

Any transfer, authentication, upload, or process failure retains the audio.
The Watch presents the failure and supports resend; the iPhone also recovers
its inbox and background-task ledger on relaunch and retries after reconnect.

## Idempotency and crash recovery

Every Watch recording has an immutable UUID `capture_id`. The iPhone sends it
as `source_capture_id` when creating the meeting. Core uniquely scopes this ID
to the authenticated source device, so a retry after a lost response returns
the existing meeting instead of creating a duplicate. A different enrolled
device may use the same capture UUID without crossing the device ownership
boundary.

Once a capture is bound to a Core origin, device ID, and Core meeting ID, that
identity is immutable in the iPhone inbox. Re-pairing the app while delivery is
pending retains the recording and reports a non-retryable identity conflict
instead of sending an old meeting ID to a replacement Core.

The transfer property-list schemas are:

- `pilot.watch.meeting.transfer.v1`: capture ID, title, start time, duration,
  SHA-256, byte count, and original filename;
- `pilot.watch.meeting.ack.v1`: capture ID, acknowledgement time, delivery
  state, and optional Core meeting ID or bounded failure detail.

Watch state advances from recording to queued, transferring,
`durable_received`, and `core_accepted`. The iPhone ledger advances through
received, meeting created, uploading, uploaded, processing, and Core accepted.
Transitions are persisted before starting the next network operation.

## Recording and delivery behavior

- Recording starts and stops only from explicit controls in the Watch app.
- Audio is mono AAC in an M4A container at 16 kHz and 64 kbit/s.
- watchOS background audio is declared so an active recording can continue
  with the display down, subject to normal watchOS resource policy.
- `WCSession.transferFile` provides queued background delivery and resumes when
  the paired iPhone is available; direct Watch-to-Core upload is intentionally
  not part of this release.
- The iPhone upload uses a stable background session identifier and a durable
  task/capture/meeting ledger. A reusable bearer or short-lived upload ticket
  is placed only on its live request and is never written to either application
  ledger.
- An iOS background-execution lease covers the Watch-file receive wake until
  the verified inbox copy and next delivery boundary are durable. When a
  background upload wakes the app, its system completion handler is held while
  the normal `/process` request reaches a durable result, with a bounded safety
  deadline and ledger-backed retry.
- A failed upload whose response may have been lost is reconciled against the
  meeting before sending the large file again. Delivery advances only if Core's
  stored recording has the exact retained SHA-256, byte count, and content type;
  otherwise iPhone keeps both client copies, obtains a fresh ticket, and retries.
- A process response lost after Core accepted the job is reconciled by reading
  the meeting. `processing`, `transcribed`, `ready`, or `failed` proves that
  Core crossed the processing acceptance boundary; `created` or `recorded`
  does not.

## Build and automated verification

Generate the project before opening or building it:

```bash
cd apps/pilot-ios
xcodegen generate
```

The `Pilot` scheme embeds the `PilotWatch` target. Generic unsigned builds are:

```bash
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer xcodebuild \
  -project Pilot.xcodeproj -scheme PilotWatch \
  -destination 'generic/platform=watchOS' CODE_SIGNING_ALLOWED=NO build

DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer xcodebuild \
  -project Pilot.xcodeproj -scheme Pilot \
  -destination 'generic/platform=iOS' CODE_SIGNING_ALLOWED=NO build
```

The iOS test target covers Watch metadata validation, checksum and size
verification, duplicate transfer handling, ledger recovery, the Core-only
deletion boundary, background task recovery, credential and ticket exclusion,
same-origin authentication, scoped off-origin tickets, upload/process failure
retention, and lost-response reconciliation. Core tests cover per-device
capture idempotency, upload-ticket expiry/revocation/one-time use, and migration
of an existing meeting database.

## Physical acceptance still required

Simulator and generic-device builds do not prove Apple Watch behavior. Before
calling the feature operational, validate on the enrolled Watch and iPhone:

1. 60–90 minute recording with the Watch display down and normal arm movement;
2. phone nearby, phone locked, phone unavailable, and later reconnection;
3. phone and Watch process termination/relaunch at every durable state;
4. interruption by calls, Siri, alarms, low battery, and audio-route changes;
5. resend after iPhone app reinstall and duplicate transfer delivery;
6. battery, storage, temperature, intelligibility, file duration, and checksum;
7. live Core receipt, processing acceptance, `core_accepted` acknowledgement,
   meeting review, and deletion of both retained client copies.

Meeting transcription is a separate Core acceptance boundary. The current
worker requires a private OpenAI-compatible multipart transcription endpoint
that returns timestamped segments. A WebSocket-only realtime ASR service is
not interchangeable with that contract; if compatible STT is inactive, the
recording must remain visible in Core with an honest processing failure rather
than fabricated transcript or analysis.
