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

    func testEnergySceneUsesAuthoritativeSunAndTeslaDeadband() {
        XCTAssertFalse(EnergyScenePolicy.vehicleIsDrawingPower(1.6))
        XCTAssertFalse(EnergyScenePolicy.vehicleIsDrawingPower(99.9))
        XCTAssertTrue(EnergyScenePolicy.vehicleIsDrawingPower(100))
        XCTAssertEqual(
            EnergyScenePolicy.houseAsset(
                isDay: true,
                solarWatts: 0,
                vehicleConnected: true
            ),
            "SolarHouseTeslaDay"
        )
        XCTAssertEqual(
            EnergyScenePolicy.houseAsset(
                isDay: false,
                solarWatts: 8_000,
                vehicleConnected: false
            ),
            "SolarHouse"
        )
    }

    func testPortableEnergyContractMapsPartialSnapshot() throws {
        let data = Data(
            """
            {
              "schema_version":"pilot.energy.v1","status":"partial",
              "solar":{"value":8420,"unit":"W","observed_at":"2026-07-22T00:00:00Z"},
              "grid":{"value":-4910,"unit":"W","observed_at":"2026-07-22T00:00:00Z","direction":"exporting"},
              "battery":{"value":-2080,"unit":"W","observed_at":"2026-07-22T00:00:00Z","direction":"charging"},
              "battery_soc":{"value":76,"unit":"%","observed_at":"2026-07-22T00:00:00Z"},
              "home_load":{"value":3510,"unit":"W","observed_at":"2026-07-22T00:00:00Z"}
            }
            """.utf8
        )
        let value = try JSONDecoder().decode(EnergyEnvelope.self, from: data).snapshot
        XCTAssertEqual(value.status, .stale)
        XCTAssertEqual(value.solarWatts, 8420)
        XCTAssertEqual(value.gridWatts, -4910)
        XCTAssertEqual(value.batteryStateOfCharge, 76)
    }

    func testSharedDashboardContractDecodesMonitoringAndControls() throws {
        let data = Data(
            """
            {
              "schema_version":"pilot.dashboard.v1","status":"ok",
              "power":{"solar_w":8820,"grid_w":15,"battery_w":-3110,
                "battery_soc_percent":77,"home_load_w":5610,"server_rack_w":312,
                "vehicle_w":4540,"directions":{"grid":"exporting","battery":"charging"},
                "flow_active":{"grid":false,"battery":true}},
              "scene":{"is_day":true,"sun_state":"above_horizon",
                "solar_elevation_degrees":31.4},
              "daily":{"solar_generated_kwh":66.3,"home_used_kwh":32.9,
                "grid_exported_kwh":5.5},
              "vehicle":{"name":"Jarvis","connected":true,"charging":true,
                "power_w":4540,"state_of_charge_percent":64},
              "tariff":{"import_cents_per_kwh":28.5,"feed_in_cents_per_kwh":8.2,
                "feed_in_forecast":[{"at":"2026-07-22T04:00:00Z","cents_per_kwh":11.3}]},
              "temperatures":[{"id":"bedroom","label":"Bedroom","temperature_c":23.4}],
              "history":{"period_hours":24,"series":[{"id":"solar","label":"Solar",
                "color":"#FFC247","unit":"W","points":[
                  {"at":"2026-07-22T03:00:00Z","value":8820}]}]},
              "weather":{"status":"ok","condition":"sunny","temperature_c":24,
                "forecast":[{"at":"2026-07-23T00:00:00Z","condition":"partlycloudy",
                  "high_temperature_c":26,"low_temperature_c":15,
                  "precipitation_probability":10}]},
              "controls":{"tesla_charging_mode":{"value":"Solar",
                "options":["Grid","Solar"],"available":true},
                "media_room_mode":{"available":true}}
            }
            """.utf8
        )
        let value = try JSONDecoder().decode(DashboardSnapshot.self, from: data)
        XCTAssertEqual(value.power.serverRackWatts, 312)
        XCTAssertEqual(value.power.flowActive["grid"], false)
        XCTAssertEqual(value.power.directions["battery"], "charging")
        XCTAssertEqual(value.scene?.isDay, true)
        XCTAssertEqual(value.scene?.solarElevationDegrees, 31.4)
        XCTAssertTrue(value.vehicle.charging)
        XCTAssertEqual(value.history.series.first?.points.first?.value, 8820)
        XCTAssertEqual(value.weather.forecast.first?.highTemperatureCelsius, 26)
        XCTAssertEqual(value.controls.chargingMode.value, "Solar")
        XCTAssertTrue(value.controls.mediaRoomMode.available)
    }

    @MainActor
    func testPairingCodeParsesJSONAndBareGrant() throws {
        let json = """
        {"core_url":"http://pilot.local:8770","bootstrap_token":"one-use-token"}
        """
        let payload = try XCTUnwrap(
            PilotModel.parsePairingCode(json, defaultCoreURL: "")
        )
        XCTAssertEqual(payload.coreURL.absoluteString, "http://pilot.local:8770")
        XCTAssertEqual(payload.token, "one-use-token")

        let bare = try XCTUnwrap(
            PilotModel.parsePairingCode(
                "grant-token",
                defaultCoreURL: "http://10.0.1.64:8770/"
            )
        )
        XCTAssertEqual(bare.coreURL.absoluteString, "http://10.0.1.64:8770")
        XCTAssertEqual(bare.token, "grant-token")
    }

    func testClientManifestAndResumableEventsDecode() throws {
        let manifest = Data(
            """
            {"schema_version":"pilot.client.v1","core_version":"0.25.0",
             "features":{"home":true,"realtime":true},
             "endpoints":{"events":"/v1/devices/phone/events"}}
            """.utf8
        )
        let decoded = try JSONDecoder().decode(PilotClientManifest.self, from: manifest)
        XCTAssertEqual(decoded.schemaVersion, "pilot.client.v1")
        XCTAssertEqual(decoded.features["realtime"], true)

        let events = Data(
            """
            {"schema_version":"pilot.events.v1","cursor":"7","revision":7,
             "reset_required":false,"events":[{
               "id":"evt_7","type":"pilot.media.changed.v1","revision":7,
               "occurred_at":"2026-07-22T00:00:00Z","room_id":"office",
               "payload":{"player_id":"office-music"}
             }]}
            """.utf8
        )
        let batch = try JSONDecoder().decode(ClientEventSnapshot.self, from: events)
        XCTAssertEqual(batch.cursor, "7")
        XCTAssertEqual(batch.events.first?.revision, 7)
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
                "actions": ["turn_on", "turn_off", "set_brightness"],
                "presentation": {
                  "exposure_policy":"automatic","included":true,
                  "reason":"user_facing_domain","category":"control","priority":85,
                  "room":{"trust":"registry","authoritative":true},
                  "supported_actions":["turn_on","turn_off","set_brightness"],
                  "canonical_id":"light.office_lamp","duplicate_of":null,
                  "display_name":"Desk Lamp","icon":"lightbulb.fill","section":"Controls"
                }
              }]
            }
            """.utf8
        )
        let projection = try JSONDecoder().decode(HomeProjection.self, from: data)
        XCTAssertEqual(projection.room.name, "Office")
        XCTAssertTrue(projection.entities[0].isOn)
        XCTAssertEqual(projection.entities[0].displayName, "Desk Lamp")
        XCTAssertTrue(projection.entities[0].shouldDisplay)
        XCTAssertEqual(try XCTUnwrap(projection.entities[0].brightnessPercent), 50.2, accuracy: 0.2)
    }

    func testRichMediaQueueAndArtworkDecode() throws {
        let data = Data(
            """
            {
              "device_id":"phone","room_id":"office","rooms":[],
              "media":{"observed_at":"2026-07-22T00:00:00Z","players":{
                "office-music":{
                  "player":{"id":"office-music","room_id":"office","name":"Office Music",
                    "kind":"music","protocol":"sendspin","enabled":true,"control_enabled":true},
                  "status":"ok",
                  "effective":{"available":true,"powered":true,"playback_state":"playing",
                    "volume_percent":35,"muted":false,"source":"music_assistant",
                    "media":{"title":"Teardrop","artist":"Massive Attack","album":"Mezzanine"},
                    "position_seconds":12.5,"duration_seconds":180,
                    "artwork_url":"https://pilot.local/artwork/1",
                    "queue":{"status":"ok","index":0,"truncated":false,"items":[{
                      "id":"track-1","title":"Teardrop","artist":"Massive Attack",
                      "album":"Mezzanine","artwork":{"available":true,
                        "source_url":"https://example.test/cover.jpg","proxy_url":null}
                    }]}
                  },
                  "capabilities":{"actions":["play","pause","next","seek"],
                    "transport":true,"volume":true,"seek":true,"transfer":true,"grouping":false}
                }
              }}
            }
            """.utf8
        )
        let envelope = try JSONDecoder().decode(DeviceMediaEnvelope.self, from: data)
        let player = try XCTUnwrap(envelope.media.players["office-music"])
        XCTAssertEqual(player.effective.positionSeconds, 12.5)
        XCTAssertEqual(player.effective.queue?.items.first?.title, "Teardrop")
        XCTAssertEqual(player.capabilities?.seek, true)
    }

    func testPendingMeetingRecordingPersistsFailureMetadata() throws {
        let pending = PendingMeetingRecording(
            id: "meeting-1",
            meetingID: "meeting-1",
            title: "Planning",
            recordingPath: "/private/var/mobile/meeting-1.m4a",
            state: .failed,
            uploadComplete: true,
            failureMessage: "Processing service unavailable",
            updatedAt: Date(timeIntervalSince1970: 1)
        )
        let roundTrip = try JSONDecoder().decode(
            PendingMeetingRecording.self,
            from: JSONEncoder().encode(pending)
        )
        XCTAssertEqual(roundTrip.state, .failed)
        XCTAssertTrue(roundTrip.uploadComplete)
        XCTAssertEqual(roundTrip.recordingPath, pending.recordingPath)
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
