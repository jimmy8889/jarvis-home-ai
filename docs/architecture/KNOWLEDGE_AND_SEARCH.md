# Pilot Knowledge Graph and Unified Search

Status: Proposed

## Purpose

Pilot needs one search and relationship layer across meetings, projects, people, devices, documentation, media, tasks, and selected personal sources. Search results must retain source references and access controls.

## Knowledge graph

The knowledge graph stores durable entities and relationships that are useful beyond live world state.

Examples:

```text
person:mariella --works_at--> organisation:fronius
meeting:roundtable-2026-05 --mentioned--> product:reserva-pro
meeting:roundtable-2026-05 --created--> task:update-collateral
project:pilot-os --tracked_by--> github:jarvis-home-ai
room:media-room --uses--> device:denon-x8500h
```

## Difference from the world model

- The **world model** answers what is true now or recently.
- The **knowledge graph** answers what things are, how they relate, and where supporting evidence exists.
- The **memory service** governs what personal context is retained.
- The **search service** retrieves authorised evidence from all three.

## Ingestion pipeline

```text
Source connector
→ extraction
→ classification and entity linking
→ access and retention policy
→ canonical record
→ embeddings and keyword index
→ relationship updates
```

## Search modes

### Exact and filtered search
For device IDs, names, dates, entity types, status, owners, and tags.

### Semantic search
For natural-language retrieval over transcripts, documentation, notes, and project history.

### Graph traversal
For relationship questions such as “what actions came from meetings about Reserva?”

### Hybrid search
Combine keyword, semantic similarity, recency, source authority, and graph proximity.

## Result contract

```json
{
  "answer_candidate": "...",
  "results": [
    {
      "source_id": "meeting:123#segment:45",
      "title": "Solarwide meeting",
      "snippet": "...",
      "score": 0.91,
      "source_type": "meeting_transcript",
      "occurred_at": "...",
      "permissions": ["james"],
      "evidence_url": "/meetings/123?t=1842"
    }
  ]
}
```

Generated answers must cite result IDs internally so the UI can open the evidence.

## Initial searchable sources

- Pilot documentation and ADRs
- GitHub issues, pull requests, and releases
- Meeting transcripts and summaries
- Tasks and projects
- Home Assistant entity metadata and selected history
- Device inventory and fault history
- Music library metadata and playback history
- Energy system explanations and events

Email, calendar, files, and photos should be added only through explicit connectors and permission policies.

## Privacy

- Indexes inherit source permissions.
- Deleted source content must be removed from keyword, vector, cache, and graph stores.
- Sensitive sources can be configured as retrieval-only without durable embeddings.
- Search logs require retention controls.
