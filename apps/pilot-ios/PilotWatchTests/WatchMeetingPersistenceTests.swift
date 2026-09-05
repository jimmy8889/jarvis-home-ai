import Foundation
import XCTest
@testable import PilotWatch

@MainActor
final class WatchMeetingPersistenceTests: XCTestCase {
    func testCoreAcceptedManifestFailureRetainsAudioAndLastDurableState() throws {
        let capture = makeCapture(state: .durableReceived)
        let store = try FailingOutboxStore(captures: [capture])
        let audioURL = store.audioURL(for: capture)
        try Data("retained meeting audio".utf8).write(to: audioURL)
        let model = try WatchMeetingModel(testingStore: store)

        store.failManifestWrites = true
        model.receiveAcknowledgement(try coreAcceptedAcknowledgement(for: capture.id))

        XCTAssertEqual(model.captures.first?.deliveryState, .durableReceived)
        XCTAssertEqual(model.captures.first?.retryable, true)
        XCTAssertNotNil(model.persistenceError)
        XCTAssertEqual(store.removeAudioCallCount, 0)
        XCTAssertTrue(FileManager.default.fileExists(atPath: audioURL.path))
        XCTAssertEqual(store.persistedCaptures.first?.deliveryState, .durableReceived)

        let relaunchedModel = try WatchMeetingModel(testingStore: store)
        XCTAssertEqual(relaunchedModel.captures, store.persistedCaptures)
        XCTAssertEqual(relaunchedModel.captures.first?.deliveryState, .durableReceived)
        XCTAssertTrue(FileManager.default.fileExists(atPath: audioURL.path))
    }

    func testCoreAcceptedDeletesOnlyAfterAcceptedManifestPersists() throws {
        let capture = makeCapture(state: .durableReceived)
        let store = try FailingOutboxStore(captures: [capture])
        let audioURL = store.audioURL(for: capture)
        try Data("accepted meeting audio".utf8).write(to: audioURL)
        let model = try WatchMeetingModel(testingStore: store)

        model.receiveAcknowledgement(try coreAcceptedAcknowledgement(for: capture.id))

        XCTAssertEqual(store.persistedCaptures.first?.deliveryState, .coreAccepted)
        XCTAssertEqual(model.captures.first?.deliveryState, .coreAccepted)
        XCTAssertEqual(store.removeAudioCallCount, 1)
        XCTAssertFalse(FileManager.default.fileExists(atPath: audioURL.path))

        let relaunchedModel = try WatchMeetingModel(testingStore: store)
        XCTAssertEqual(relaunchedModel.captures.first?.deliveryState, .coreAccepted)
    }

    private func makeCapture(state: WatchMeetingDeliveryState) -> WatchMeetingCapture {
        let id = UUID()
        return WatchMeetingCapture(
            id: id,
            title: "Persistence boundary",
            startedAt: Date(timeIntervalSince1970: 1_700_000_000),
            durationSeconds: 90,
            originalFilename: "\(id.uuidString.lowercased()).m4a",
            sha256: String(repeating: "a", count: 64),
            sizeBytes: 22,
            deliveryState: state,
            attemptCount: 1,
            lastAttemptAt: Date(timeIntervalSince1970: 1_700_000_010),
            acknowledgedAt: Date(timeIntervalSince1970: 1_700_000_020),
            coreMeetingID: nil,
            lastError: nil,
            retryable: false
        )
    }

    private func coreAcceptedAcknowledgement(for captureID: UUID) throws -> WatchMeetingAcknowledgement {
        let value = WatchMeetingAcknowledgement(propertyList: [
            "schema_version": WatchMeetingProtocol.acknowledgementSchema,
            "capture_id": captureID.uuidString.lowercased(),
            "state": "core_accepted",
            "acknowledged_at": WatchMeetingProtocol.iso8601String(
                from: Date(timeIntervalSince1970: 1_700_000_030)
            ),
            "core_meeting_id": "meeting-test",
            "retryable": false,
        ])
        return try XCTUnwrap(value)
    }
}

private final class FailingOutboxStore: WatchMeetingOutboxStoring, @unchecked Sendable {
    enum TestError: LocalizedError {
        case manifestWriteFailed
        case unusedFinalization

        var errorDescription: String? {
            switch self {
            case .manifestWriteFailed: "Injected manifest write failure"
            case .unusedFinalization: "Finalization is not used by this test"
            }
        }
    }

    let directoryURL: URL
    var persistedCaptures: [WatchMeetingCapture]
    var failManifestWrites = false
    private(set) var removeAudioCallCount = 0

    init(captures: [WatchMeetingCapture]) throws {
        directoryURL = FileManager.default.temporaryDirectory.appendingPathComponent(
            "PilotWatchPersistenceTests-\(UUID().uuidString)",
            isDirectory: true
        )
        persistedCaptures = captures
        try FileManager.default.createDirectory(
            at: directoryURL,
            withIntermediateDirectories: true
        )
    }

    deinit {
        try? FileManager.default.removeItem(at: directoryURL)
    }

    func audioURL(for capture: WatchMeetingCapture) -> URL {
        directoryURL.appendingPathComponent(capture.originalFilename)
    }

    func load() throws -> [WatchMeetingCapture] {
        persistedCaptures
    }

    func save(_ captures: [WatchMeetingCapture]) throws {
        if failManifestWrites {
            throw TestError.manifestWriteFailed
        }
        persistedCaptures = captures
    }

    func removeAudio(for capture: WatchMeetingCapture) throws {
        removeAudioCallCount += 1
        let url = audioURL(for: capture)
        if FileManager.default.fileExists(atPath: url.path) {
            try FileManager.default.removeItem(at: url)
        }
    }

    func protectAudio(for capture: WatchMeetingCapture) {}

    func finalizedDetails(
        for capture: WatchMeetingCapture
    ) throws -> (duration: TimeInterval, sha256: String, size: Int64) {
        throw TestError.unusedFinalization
    }
}
