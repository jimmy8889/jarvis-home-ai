import XCTest
@testable import PilotClientKit

final class PilotClientKitTests: XCTestCase {
    func testJSONPairingCodeRequiresHTTPSByDefault() throws {
        let code = #"{"core_url":"https://pilot.example.test","bootstrap_token":"grant"}"#
        let parsed = try PilotPairingPayload.parse(code)
        XCTAssertEqual(parsed.coreURL.absoluteString, "https://pilot.example.test")
        XCTAssertEqual(parsed.bootstrapToken, "grant")

        XCTAssertThrowsError(
            try PilotPairingPayload.parse(
                #"{"core_url":"http://10.0.1.64:8770","bootstrap_token":"grant"}"#
            )
        )
    }

    func testDevelopmentModeCanExplicitlyAllowHTTP() throws {
        let parsed = try PilotPairingPayload.parse(
            "pilot://pair?core_url=http://10.0.1.64:8770&token=grant",
            allowsInsecureHTTP: true
        )
        XCTAssertEqual(parsed.coreURL.host, "10.0.1.64")
    }

    func testManagedCredentialBundleRequiresVersionedHTTPSPayload() throws {
        let credentials = try PilotCredentialBundle.parse(
            #"{"schema_version":"pilot.credentials.v1","core_url":"https://pilot.example.test","device_id":"pilot-drive","device_token":"secret"}"#
        )
        XCTAssertEqual(credentials.coreURL.absoluteString, "https://pilot.example.test")
        XCTAssertEqual(credentials.deviceID, "pilot-drive")
        XCTAssertEqual(credentials.deviceToken, "secret")
        XCTAssertThrowsError(
            try PilotCredentialBundle.parse(
                #"{"schema_version":"pilot.credentials.v1","core_url":"http://10.0.1.204:8770","device_id":"pilot-drive","device_token":"secret"}"#
            )
        )
    }

    func testEventSnapshotDecodesResumableCursor() throws {
        let data = Data(
            #"{"schema_version":"pilot.events.v1","cursor":"12","revision":12,"reset_required":false,"events":[{"id":"evt_12","type":"pilot.vehicle.state.v1","revision":12,"room_id":null,"payload":{"privacy":"sensitive"},"occurred_at":"2026-08-03T00:00:00Z"}]}"#.utf8
        )
        let snapshot = try JSONDecoder().decode(PilotEventSnapshot.self, from: data)
        XCTAssertEqual(snapshot.cursor, "12")
        XCTAssertEqual(snapshot.events.first?.type, "pilot.vehicle.state.v1")
    }

    func testCredentialVaultRoundTrip() throws {
        let vault = PilotCredentialVault(
            service: "com.jameshazell.pilotclientkit.tests.\(UUID().uuidString)"
        )
        let credentials = PilotCredentials(
            coreURL: try XCTUnwrap(URL(string: "https://pilot.example.test")),
            deviceID: "pilot-drive-test",
            deviceToken: "secret-device-token"
        )
        defer { try? vault.remove() }

        try vault.save(credentials)
        XCTAssertEqual(try vault.load(), credentials)
        try vault.remove()
        XCTAssertNil(try vault.load())
    }
}
