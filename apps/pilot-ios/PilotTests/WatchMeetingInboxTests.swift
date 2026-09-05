import Foundation
import XCTest
@testable import Pilot

final class WatchMeetingInboxTests: XCTestCase {
    func testTransferMetadataValidatesEveryRequiredField() throws {
        let captureID = UUID()
        let startedAt = Date(timeIntervalSince1970: 1_786_421_234.125)
        let valid = try WatchMeetingTransferMetadata(
            captureID: captureID,
            title: "  Weekly planning  ",
            startedAt: startedAt,
            durationSeconds: 42.5,
            sha256: String(repeating: "a", count: 64),
            sizeBytes: 4_096,
            originalFilename: "capture.m4a"
        )

        let decoded = try WatchMeetingTransferMetadata(propertyList: valid.propertyList)
        XCTAssertEqual(decoded.captureID, captureID)
        XCTAssertEqual(decoded.title, "Weekly planning")
        XCTAssertEqual(decoded.startedAt.timeIntervalSince1970, startedAt.timeIntervalSince1970, accuracy: 0.001)
        XCTAssertEqual(decoded.durationSeconds, 42.5)
        XCTAssertEqual(decoded.sha256, String(repeating: "a", count: 64))
        XCTAssertEqual(decoded.sizeBytes, 4_096)

        for (key, invalidValue) in [
            (WatchMeetingTransferContract.Key.captureID, "not-a-uuid" as Any),
            (WatchMeetingTransferContract.Key.title, "   " as Any),
            (WatchMeetingTransferContract.Key.startedAt, "yesterday" as Any),
            (WatchMeetingTransferContract.Key.durationSeconds, 0 as Any),
            (WatchMeetingTransferContract.Key.sha256, "abcd" as Any),
            (WatchMeetingTransferContract.Key.sizeBytes, -1 as Any),
        ] {
            var payload = valid.propertyList
            payload[key] = invalidValue
            XCTAssertThrowsError(
                try WatchMeetingTransferMetadata(propertyList: payload),
                "Expected \(key) to be rejected"
            )
        }
    }

    func testReceiveVerifiesChecksumAndSizeBeforeCommittingLedger() throws {
        let fixture = try Fixture()
        defer { fixture.cleanUp() }
        let audio = Data("private meeting audio".utf8)
        let source = try fixture.sourceFile(data: audio)
        let metadata = try fixture.metadata(fileURL: source, data: audio)

        let receipt = try fixture.store.receiveSynchronously(fileURL: source, metadata: metadata)
        XCTAssertFalse(receipt.isDuplicate)
        XCTAssertEqual(receipt.record.state, .received)
        XCTAssertEqual(try Data(contentsOf: fixture.store.fileURL(for: metadata.captureID)), audio)

        let secondSource = try fixture.sourceFile(data: audio, name: "bad-hash.m4a")
        let badHash = try WatchMeetingTransferMetadata(
            captureID: UUID(),
            title: "Bad hash",
            startedAt: .now,
            durationSeconds: 1,
            sha256: String(repeating: "0", count: 64),
            sizeBytes: Int64(audio.count)
        )
        XCTAssertThrowsError(
            try fixture.store.receiveSynchronously(fileURL: secondSource, metadata: badHash)
        ) { error in
            XCTAssertEqual(error as? WatchMeetingInboxError, .checksumMismatch)
        }

        let thirdSource = try fixture.sourceFile(data: audio, name: "bad-size.m4a")
        let badSize = try WatchMeetingTransferMetadata(
            captureID: UUID(),
            title: "Bad size",
            startedAt: .now,
            durationSeconds: 1,
            sha256: try WatchMeetingFileIntegrity.sha256Hex(at: thirdSource),
            sizeBytes: Int64(audio.count + 1)
        )
        XCTAssertThrowsError(
            try fixture.store.receiveSynchronously(fileURL: thirdSource, metadata: badSize)
        ) { error in
            guard case let WatchMeetingInboxError.fileSizeMismatch(expected, actual) = error else {
                return XCTFail("Unexpected error: \(error)")
            }
            XCTAssertEqual(expected, Int64(audio.count + 1))
            XCTAssertEqual(actual, Int64(audio.count))
        }
        XCTAssertEqual(fixture.store.allRecords().count, 1)
    }

    func testDuplicateDeliveryIsIdempotentAndConflictingMetadataIsRejected() throws {
        let fixture = try Fixture()
        defer { fixture.cleanUp() }
        let audio = Data("duplicate meeting".utf8)
        let source = try fixture.sourceFile(data: audio)
        let metadata = try fixture.metadata(fileURL: source, data: audio)

        let first = try fixture.store.receiveSynchronously(fileURL: source, metadata: metadata)
        let second = try fixture.store.receiveSynchronously(fileURL: source, metadata: metadata)

        XCTAssertFalse(first.isDuplicate)
        XCTAssertTrue(second.isDuplicate)
        XCTAssertEqual(second.acknowledgement.state, .durableReceived)
        XCTAssertEqual(fixture.store.allRecords().map(\.id), [metadata.captureID])

        let conflict = try WatchMeetingTransferMetadata(
            captureID: metadata.captureID,
            title: "Different title",
            startedAt: metadata.startedAt,
            durationSeconds: metadata.durationSeconds,
            sha256: metadata.sha256,
            sizeBytes: metadata.sizeBytes
        )
        XCTAssertThrowsError(
            try fixture.store.receiveSynchronously(fileURL: source, metadata: conflict)
        ) { error in
            XCTAssertEqual(error as? WatchMeetingInboxError, .metadataConflict(metadata.captureID))
        }
    }

    func testLedgerReloadRestoresCoreBindingPipelineStateAndFailure() throws {
        let fixture = try Fixture()
        defer { fixture.cleanUp() }
        let audio = Data("persist me".utf8)
        let source = try fixture.sourceFile(data: audio)
        let metadata = try fixture.metadata(fileURL: source, data: audio)
        _ = try fixture.store.receiveSynchronously(fileURL: source, metadata: metadata)
        _ = try fixture.store.bindCoreDestination(
            captureID: metadata.captureID,
            coreOrigin: "https://pilot.example/",
            coreDeviceID: "pilot-ios-test"
        )
        _ = try fixture.store.bindCoreMeeting(captureID: metadata.captureID, coreMeetingID: "core-123")
        _ = try fixture.store.markUploading(captureID: metadata.captureID)
        _ = try fixture.store.markUploaded(captureID: metadata.captureID)
        _ = try fixture.store.markProcessing(captureID: metadata.captureID)
        _ = try fixture.store.markCoreFailed(
            captureID: metadata.captureID,
            message: "Core temporarily unavailable",
            retryable: true
        )
        let acknowledgementQueuedAt = Date(timeIntervalSince1970: 1_786_400_123)
        _ = try fixture.store.markAcknowledgementQueued(
            captureID: metadata.captureID,
            at: acknowledgementQueuedAt
        )

        let reloaded = try WatchMeetingInboxStore(rootDirectory: fixture.inboxDirectory)
        let record = try XCTUnwrap(reloaded.pendingRecords().first)
        XCTAssertEqual(record.id, metadata.captureID)
        XCTAssertEqual(record.coreOrigin, "https://pilot.example")
        XCTAssertEqual(record.coreDeviceID, "pilot-ios-test")
        XCTAssertEqual(record.coreMeetingID, "core-123")
        XCTAssertEqual(record.state, .processing)
        XCTAssertEqual(record.failure?.message, "Core temporarily unavailable")
        XCTAssertTrue(record.failure?.retryable == true)
        XCTAssertEqual(record.acknowledgementQueuedAt, acknowledgementQueuedAt)
        XCTAssertEqual(try Data(contentsOf: reloaded.fileURL(for: metadata.captureID)), audio)

        XCTAssertThrowsError(
            try reloaded.bindCoreDestination(
                captureID: metadata.captureID,
                coreOrigin: "https://other-pilot.example",
                coreDeviceID: "pilot-ios-test"
            )
        ) { error in
            XCTAssertEqual(
                error as? WatchMeetingInboxError,
                .coreIdentityConflict(metadata.captureID)
            )
        }
    }

    func testRecordingIsRetainedUntilProcessingIsAcceptedByCore() throws {
        let fixture = try Fixture()
        defer { fixture.cleanUp() }
        let audio = Data("retain until accepted".utf8)
        let source = try fixture.sourceFile(data: audio)
        let metadata = try fixture.metadata(fileURL: source, data: audio)
        _ = try fixture.store.receiveSynchronously(fileURL: source, metadata: metadata)
        let retainedURL = try fixture.store.fileURL(for: metadata.captureID)

        _ = try fixture.store.markCoreFailed(
            captureID: metadata.captureID,
            message: "offline",
            retryable: true
        )
        XCTAssertTrue(FileManager.default.fileExists(atPath: retainedURL.path))

        _ = try fixture.store.bindCoreMeeting(captureID: metadata.captureID, coreMeetingID: "core-456")
        _ = try fixture.store.markUploading(captureID: metadata.captureID)
        _ = try fixture.store.markUploaded(captureID: metadata.captureID)
        XCTAssertThrowsError(try fixture.store.markCoreAccepted(captureID: metadata.captureID))
        XCTAssertTrue(FileManager.default.fileExists(atPath: retainedURL.path))

        _ = try fixture.store.markProcessing(captureID: metadata.captureID)
        let accepted = try fixture.store.markCoreAccepted(captureID: metadata.captureID)
        XCTAssertEqual(accepted.0.state, .coreAccepted)
        XCTAssertEqual(accepted.1.state, .coreAccepted)
        XCTAssertFalse(FileManager.default.fileExists(atPath: retainedURL.path))
        XCTAssertTrue(fixture.store.pendingRecords().isEmpty)

        // A cleanup failure/crash can leave an accepted file behind. Store
        // startup retries that privacy-sensitive cleanup.
        try audio.write(to: retainedURL)
        XCTAssertTrue(FileManager.default.fileExists(atPath: retainedURL.path))
        _ = try WatchMeetingInboxStore(rootDirectory: fixture.inboxDirectory)
        XCTAssertFalse(FileManager.default.fileExists(atPath: retainedURL.path))
    }

    func testAcknowledgementPayloadsUseBackgroundSafeContract() throws {
        let captureID = UUID()
        let timestamp = Date(timeIntervalSince1970: 1_786_400_000.25)

        let received = WatchMeetingAcknowledgement.durableReceived(
            captureID: captureID,
            at: timestamp
        ).propertyList
        XCTAssertEqual(
            received[WatchMeetingTransferContract.Key.schemaVersion] as? String,
            WatchMeetingTransferContract.acknowledgementSchema
        )
        XCTAssertEqual(
            received[WatchMeetingTransferContract.Key.captureID] as? String,
            captureID.uuidString.lowercased()
        )
        XCTAssertEqual(
            received[WatchMeetingTransferContract.Key.state] as? String,
            "durable_received"
        )
        XCTAssertNotNil(received[WatchMeetingTransferContract.Key.acknowledgedAt] as? String)

        let accepted = WatchMeetingAcknowledgement.coreAccepted(
            captureID: captureID,
            coreMeetingID: "core-789",
            at: timestamp
        ).propertyList
        XCTAssertEqual(accepted[WatchMeetingTransferContract.Key.state] as? String, "core_accepted")
        XCTAssertEqual(accepted[WatchMeetingTransferContract.Key.coreMeetingID] as? String, "core-789")

        let failed = WatchMeetingAcknowledgement.failed(
            captureID: captureID,
            message: "Upload failed",
            retryable: true,
            at: timestamp
        ).propertyList
        XCTAssertEqual(failed[WatchMeetingTransferContract.Key.state] as? String, "failed")
        XCTAssertEqual(failed[WatchMeetingTransferContract.Key.message] as? String, "Upload failed")
        XCTAssertEqual(failed[WatchMeetingTransferContract.Key.retryable] as? Bool, true)
        XCTAssertNil(failed[WatchMeetingTransferContract.Key.coreMeetingID])
    }
}

private final class Fixture {
    let temporaryDirectory: URL
    let inboxDirectory: URL
    let store: WatchMeetingInboxStore

    init() throws {
        temporaryDirectory = FileManager.default.temporaryDirectory
            .appendingPathComponent("WatchMeetingInboxTests-\(UUID().uuidString)", isDirectory: true)
        inboxDirectory = temporaryDirectory.appendingPathComponent("inbox", isDirectory: true)
        try FileManager.default.createDirectory(
            at: temporaryDirectory,
            withIntermediateDirectories: true
        )
        store = try WatchMeetingInboxStore(rootDirectory: inboxDirectory)
    }

    func sourceFile(data: Data, name: String = "source.m4a") throws -> URL {
        let url = temporaryDirectory.appendingPathComponent(name, isDirectory: false)
        try data.write(to: url, options: .atomic)
        return url
    }

    func metadata(fileURL: URL, data: Data) throws -> WatchMeetingTransferMetadata {
        try WatchMeetingTransferMetadata(
            captureID: UUID(),
            title: "Watch capture",
            startedAt: Date(timeIntervalSince1970: 1_786_400_000),
            durationSeconds: 12.5,
            sha256: try WatchMeetingFileIntegrity.sha256Hex(at: fileURL),
            sizeBytes: Int64(data.count),
            originalFilename: fileURL.lastPathComponent
        )
    }

    func cleanUp() {
        try? FileManager.default.removeItem(at: temporaryDirectory)
    }
}
