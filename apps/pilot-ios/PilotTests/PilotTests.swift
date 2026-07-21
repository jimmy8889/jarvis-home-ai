import XCTest
@testable import Pilot

final class PilotTests: XCTestCase {
    func testMusicAssistantSearchFlattening() {
        let input: [String: Any] = [
            "tracks": [
                [
                    "name": "Teardrop",
                    "artist": "Massive Attack",
                    "uri": "tidal://track/1",
                ],
            ],
        ]

        let results = PilotAPI.flattenSearch(input)

        XCTAssertEqual(results.count, 1)
        XCTAssertEqual(results[0].title, "Teardrop")
        XCTAssertEqual(results[0].uri, "tidal://track/1")
        XCTAssertEqual(results[0].kind, .track)
    }

    func testSearchFlatteningGroupsKindsAndRemovesDuplicateURIs() {
        let input: [String: Any] = [
            "albums": [
                [
                    "name": "Mezzanine",
                    "artist": "Massive Attack",
                    "uri": "tidal://album/1",
                ],
            ],
            "mixed": [
                [
                    "name": "Mezzanine",
                    "media_type": "album",
                    "uri": "tidal://album/1",
                ],
                [
                    "name": "Massive Attack",
                    "media_type": "artist",
                    "uri": "tidal://artist/1",
                ],
            ],
        ]

        let results = PilotAPI.flattenSearch(input)

        XCTAssertEqual(results.count, 2)
        XCTAssertEqual(results.first(where: { $0.uri == "tidal://album/1" })?.kind, .album)
        XCTAssertEqual(results.first(where: { $0.uri == "tidal://artist/1" })?.kind, .artist)
    }

    func testEnergyPlaceholderIsExplicitlyUnavailable() {
        XCTAssertEqual(EnergySnapshot.awaitingBackend.status, .unavailable)
        XCTAssertFalse(EnergySnapshot.awaitingBackend.isPopulated)
        XCTAssertNotNil(EnergySnapshot.awaitingBackend.detail)
    }

    func testHomeProjectionDecodesBoundedControls() throws {
        let data = Data(
            """
            {
              "device_id": "pilot-ios-james",
              "selected_room_id": "office",
              "room": {
                "id": "office", "name": "Office",
                "home_area_ids": ["office", "james_office"]
              },
              "entity_count": 1,
              "entities": [{
                "entity_id": "light.office_lamp",
                "domain": "light", "name": "Office lamp", "state": "on",
                "attributes": {"brightness": 128},
                "area_id": "james_office", "availability": "available",
                "unavailable": false, "stale": false,
                "observed_at": "2026-07-21T00:00:00Z",
                "actions": ["turn_on", "turn_off", "set_brightness"]
              }]
            }
            """.utf8
        )
        let projection = try JSONDecoder().decode(HomeProjection.self, from: data)
        XCTAssertEqual(projection.room.name, "Office")
        XCTAssertTrue(projection.entities[0].isOn)
        XCTAssertEqual(try XCTUnwrap(projection.entities[0].brightnessPercent), 50.2, accuracy: 0.2)
    }

    func testMeetingListDecodesProcessingAndEvidenceCounts() throws {
        let data = Data(
            """
            {
              "device_id": "pilot-ios-james",
              "meetings": [{
                "id": "meeting-1",
                "title": "Office planning",
                "language": "en-AU",
                "source_device_id": "pilot-ios-james",
                "started_at": "2026-07-21T00:00:00Z",
                "ended_at": null,
                "status": "processing",
                "summary": null,
                "has_recording": true,
                "transcript_segment_count": 8,
                "action_item_count": 2
              }]
            }
            """.utf8
        )
        let envelope = try JSONDecoder().decode(MeetingEnvelope.self, from: data)
        XCTAssertEqual(envelope.meetings[0].statusLabel, "Processing locally")
        XCTAssertEqual(envelope.meetings[0].transcriptSegmentCount, 8)
        XCTAssertEqual(envelope.meetings[0].actionItemCount, 2)
    }

    func testMeetingDetailDecodesEvidenceLinkedOutput() throws {
        let data = Data(
            """
            {
              "id":"meeting-1","title":"Planning","language":"en-AU",
              "source_device_id":"pilot-ios-james","started_at":"2026-07-21T00:00:00Z",
              "ended_at":null,"status":"ready","summary":"Release approved.",
              "recording":{"filename":"meeting.m4a","content_type":"audio/m4a","sha256":"abc","size_bytes":2048,"created_at":"2026-07-21T00:10:00Z"},
              "participants":[],
              "transcript":[{"id":"segment-1","sequence":0,"speaker_label":"James","start_ms":0,"end_ms":2500,"text":"Ship it.","confidence":0.94,"created_at":"2026-07-21T00:10:00Z"}],
              "decisions":[{"id":"decision-1","summary":"Release approved.","segment_ids":["segment-1"],"created_at":"2026-07-21T00:10:00Z"}],
              "action_items":[{"id":"action-1","task":"Publish notes","owner":"James","due_at":null,"status":"open","confidence":0.9,"segment_ids":["segment-1"],"created_at":"2026-07-21T00:10:00Z","updated_at":"2026-07-21T00:10:00Z"}],
              "created_at":"2026-07-21T00:00:00Z","updated_at":"2026-07-21T00:10:00Z"
            }
            """.utf8
        )

        let meeting = try JSONDecoder().decode(PilotMeetingDetail.self, from: data)
        XCTAssertEqual(meeting.transcript[0].speakerLabel, "James")
        XCTAssertEqual(meeting.decisions[0].segmentIDs, ["segment-1"])
        XCTAssertEqual(meeting.actionItems[0].task, "Publish notes")
    }

    @MainActor
    func testPreviewModelHasAdaptiveProductContent() {
        let model = PilotModel.preview()

        XCTAssertTrue(model.connectionState.isConnected)
        XCTAssertEqual(model.rooms.count, 2)
        XCTAssertEqual(model.activePlayer?.effective.media?.title, "Teardrop")
        XCTAssertTrue(model.energy.isPopulated)
        XCTAssertFalse(model.messages.isEmpty)
    }
}
