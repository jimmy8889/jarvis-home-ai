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
    }
}
