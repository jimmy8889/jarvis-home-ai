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
