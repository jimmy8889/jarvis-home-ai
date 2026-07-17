# Meeting intelligence foundation

Pilot Core 0.10 contains the local storage and review contract for meeting
intelligence. This milestone deliberately separates reliable ingestion and
structured provenance from future speech and language-model workers.

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

The upload endpoint accepts common WAV, FLAC, M4A/MP4, AAC, MP3, Ogg, and WebM
audio types. It sanitizes the supplied filename, rejects empty or oversized
content, writes through a private temporary file, fsyncs, atomically replaces
the destination, and never returns its server filesystem path.

Status advances through `created`, `recorded`, `transcribed`, and `ready`.
Inference failure handling will use `failed` when the worker layer is added.

## What is not implemented yet

- voice activity detection;
- Whisper transcription;
- speaker diarisation;
- local structured-summary inference;
- semantic indexing;
- the iOS background recorder;
- automatic task/calendar export.

Those stages will consume these APIs. Transcript segments and generated
conclusions already have stable IDs, so later decisions and action items can
retain explicit links back to timestamped evidence instead of becoming
untraceable free text.
