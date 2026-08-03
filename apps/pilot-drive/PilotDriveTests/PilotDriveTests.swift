import PilotClientKit
import LocalAuthentication
import Security
import XCTest
@testable import PilotDrive

final class PilotDriveTests: XCTestCase {
    private struct CancelledAuthenticator: DeviceAuthenticator {
        func authenticate(reason: String) async throws {
            throw LAError(.userCancel)
        }
    }

    @MainActor
    func testLegacyApps01CredentialMigratesToPublicEndpoint() throws {
        let migrated = DriveModel.migrateLegacyCredentials(
            PilotCredentials(
                coreURL: try XCTUnwrap(URL(string: "http://10.0.1.204:8770")),
                deviceID: "pilot-drive",
                deviceToken: "secret",
                credentialRevision: 4
            )
        )
        XCTAssertEqual(
            migrated.coreURL.absoluteString,
            "https://pilot.jameshomeautomation.work"
        )
        XCTAssertEqual(migrated.deviceToken, "secret")
        XCTAssertEqual(migrated.credentialRevision, 4)
    }

    func testDestinationDraftUsesBoundedServerFieldNames() throws {
        var draft = DestinationDraft()
        draft.name = "Work"
        draft.address = "1 Example Street"
        draft.latitude = -27.4
        draft.longitude = 153.0
        draft.climateEnabled = true
        draft.temperatureC = 22

        let object = try XCTUnwrap(
            JSONSerialization.jsonObject(with: JSONEncoder().encode(draft)) as? [String: Any]
        )
        XCTAssertEqual(object["climate_enabled"] as? Bool, true)
        XCTAssertEqual(object["temperature_c"] as? Double, 22)
        XCTAssertNil(object["vehicle_id"])
    }

    func testActionDecodesIndependentWorkflowSteps() throws {
        let data = Data(#"""
        {
          "id":"a1","vehicle_id":"jarvis","action":"destination_workflow",
          "parameters":{"destination_id":"d1"},"risk":"standard",
          "confirmation_required":false,"status":"unverified",
          "steps":[
            {"step":"climate","status":"failed","error":"provider unavailable"},
            {"step":"route","status":"accepted"}
          ],"expires_at":"2026-08-03T06:00:00Z"
        }
        """#.utf8)

        let action = try JSONDecoder().decode(VehicleAction.self, from: data)
        XCTAssertEqual(action.steps[0].status, "failed")
        XCTAssertEqual(action.steps[1].status, "accepted")
        XCTAssertEqual(action.parameters["destination_id"]?.stringValue, "d1")
    }

    func testCredentialVaultPersistsAndRemovesDeviceCredentials() throws {
        let vault = PilotCredentialVault(
            service: "com.jameshazell.pilotdrive.tests.\(UUID().uuidString)"
        )
        let credentials = PilotCredentials(
            coreURL: try XCTUnwrap(URL(string: "https://pilot.example.test")),
            deviceID: "pilot-drive-test",
            deviceToken: "secret-device-token"
        )
        defer { try? vault.remove() }

        do {
            try vault.save(credentials)
        } catch PilotClientError.keychain(let status) where status == errSecMissingEntitlement {
            throw XCTSkip("Unsigned simulator builds do not have Keychain entitlements")
        }
        XCTAssertEqual(try vault.load(), credentials)
        try vault.remove()
        XCTAssertNil(try vault.load())
    }

    @MainActor
    func testCachedVehicleDataIsRestoredOffline() throws {
        let cacheURL = FileManager.default.temporaryDirectory
            .appending(path: UUID().uuidString)
            .appending(path: "cache.json")
        defer { try? FileManager.default.removeItem(at: cacheURL.deletingLastPathComponent()) }
        let overview = VehicleOverview(
            schemaVersion: "pilot.vehicle.v1",
            id: "jarvis",
            name: "Jarvis",
            observedAt: "2026-08-03T05:00:00Z",
            freshness: "stale",
            state: ["battery_percent": .number(72)],
            tyres: [:],
            availableControls: [],
            providers: [:]
        )
        let cache = DriveCache(
            overview: overview,
            drives: [],
            charges: [],
            batteryHealth: nil,
            destinations: [],
            maintenance: [],
            savedAt: Date()
        )
        try FileManager.default.createDirectory(
            at: cacheURL.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        try JSONEncoder().encode(cache).write(to: cacheURL)

        let model = DriveModel(
            vault: PilotCredentialVault(service: "com.jameshazell.pilotdrive.tests.\(UUID().uuidString)"),
            cacheURL: cacheURL
        )
        XCTAssertEqual(model.overview?.number("battery_percent"), 72)
        XCTAssertEqual(model.overview?.freshness, "stale")
    }

    @MainActor
    func testBiometricCancellationPreventsConfirmation() async {
        let model = DriveModel(
            vault: PilotCredentialVault(service: "com.jameshazell.pilotdrive.tests.\(UUID().uuidString)"),
            authenticator: CancelledAuthenticator(),
            cacheURL: FileManager.default.temporaryDirectory.appending(path: UUID().uuidString)
        )

        do {
            try await model.authenticateSensitiveAction("unlock")
            XCTFail("Cancellation must not be treated as confirmation")
        } catch let error as LAError {
            XCTAssertEqual(error.code, .userCancel)
        } catch {
            XCTFail("Unexpected error: \(error)")
        }
    }
}
