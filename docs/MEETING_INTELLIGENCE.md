# Meeting intelligence foundation

Pilot Core 0.23 contains the local storage, processing, retrieval, and
device-scoped client contract for meeting intelligence. The original 0.10
ingestion foundation remains, now joined by local speech and analysis workers.

## Local data model

SQLite now stores:

- meetings and processing status;
- recording metadata and SHA-256 integrity;
- participants and speaker labels;
- timestamped transcript segments with optional confidence;
- decisions linked to transcript segment IDs;
- action items with owner, due date, confidence, status, and source segments.

Recording bytes are stored under the configured meeting asset root
(`/data/meetings` in the production container). They remain inside the
integrity-manifested Pilot Core data volume and are covered by the existing cold
backup and guarded restore process.

## Authenticated API

- `POST /v1/meetings` creates a meeting.
- `GET /v1/meetings` lists review summaries and counts.
- `GET /v1/meetings/{id}` returns the full review model.
- `PUT /v1/meetings/{id}/recording` streams an audio recording into bounded
  local storage.
- `GET /v1/meetings/{id}/recording` downloads the original recording.
- `PUT /v1/meetings/{id}/transcript` replaces the timestamped transcript.
- `PUT /v1/meetings/{id}/analysis` replaces the structured summary, decisions,
  and action items.
- `POST /v1/meetings/{id}/process` runs the configured local STT and analysis
  path for an administrator.

Devices with the explicit `meetings` capability use the equivalent
`/v1/devices/{device_id}/meetings` routes. Those routes force the authenticated
device as the source, hide meetings created by any other device, and queue
processing with `202 Accepted` so a long recording never holds a mobile
request open.

The upload endpoint accepts common WAV, FLAC, M4A/MP4, AAC, MP3, Ogg, and WebM
audio types. It sanitizes the supplied filename, rejects empty or oversized
content, writes through a private temporary file, fsyncs, atomically replaces
the destination, and never returns its server filesystem path.

Status advances through `created`, `recorded`, `processing`, `transcribed`, and
`ready`. Worker failures are stored as `failed` with a bounded operational
reason.

## Local processing and retrieval

The meeting worker calls an OpenAI-compatible Whisper endpoint only when it is
configured on a private/local address. It requests timestamped segments,
normalizes confidence, bounds transcript size, and fails closed for public STT
URLs. Pilot's local LLM then creates a summary, decisions, and actions. Any
decision or action lacking a valid source-segment ID is discarded.

The assistant can search meeting titles, summaries, transcripts, decisions,
and open actions. Retrieved evidence retains segment IDs and timestamps.
Keyword retrieval is intentionally deterministic today; semantic embeddings
will be added only after production transcript quality is measured.

Pilot iOS can create a meeting, record mono AAC with the iOS background-audio
mode, upload the recording, queue processing, and display processing status,
summaries, transcript counts, and action counts. Real-device background and
long-meeting acceptance remains required.

## Remaining work

- production deployment of the local Whisper endpoint;
- dedicated VAD and multi-speaker diarisation;
- participant naming and review UI;
- semantic embeddings;
- action approval/export to tasks and calendars;
- retention, deletion, and data-export controls.
