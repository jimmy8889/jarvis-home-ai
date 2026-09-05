import Foundation
import XCTest
@testable import Pilot

final class WatchMeetingDeliveryPipelineTests: XCTestCase {
    @MainActor
    func testCaptureIsRetainedUntilUploadAndProcessingAreAccepted() async throws {
        let fixture = try PipelineFixture()
        defer { fixture.cleanUp() }
        let captureID = try fixture.receiveCapture()
        let retainedURL = try fixture.inbox.fileURL(for: captureID)

        await fixture.pipeline.resumePending()

        XCTAssertEqual(fixture.core.createCaptureIDs, [captureID.uuidString.lowercased()])
        XCTAssertEqual(try fixture.record(captureID).state, .uploading)
        XCTAssertEqual(fixture.uploader.jobs.count, 1)
        XCTAssertEqual(fixture.core.ticketRequests.count, 1)
        XCTAssertEqual(
            fixture.uploader.enqueueAttempts.first?.ticket?.uploadToken,
            "ticket-secret-1"
        )
        XCTAssertTrue(FileManager.default.fileExists(atPath: retainedURL.path))
        XCTAssertEqual(fixture.core.processCallCount, 0)

        fixture.uploader.completeUpload(captureID: captureID)
        await fixture.pipeline.resumePending()

        XCTAssertEqual(fixture.core.processCallCount, 1)
        XCTAssertEqual(try fixture.record(captureID).state, .coreAccepted)
        XCTAssertFalse(FileManager.default.fileExists(atPath: retainedURL.path))
        XCTAssertTrue(fixture.uploader.jobs.isEmpty)
    }

    @MainActor
    func testLostProcessResponseUsesDurableCoreStatusAsAcknowledgement() async throws {
        let fixture = try PipelineFixture()
        defer { fixture.cleanUp() }
        fixture.core.processError = PipelineTestError.lostResponse
        fixture.core.lookupStatus = "processing"
        let captureID = try fixture.receiveCapture()
        let retainedURL = try fixture.inbox.fileURL(for: captureID)

        await fixture.pipeline.resumePending()
        fixture.uploader.completeUpload(captureID: captureID)
        await fixture.pipeline.resumePending()

        XCTAssertEqual(fixture.core.processCallCount, 1)
        XCTAssertEqual(fixture.core.lookupCallCount, 1)
        XCTAssertEqual(try fixture.record(captureID).state, .coreAccepted)
        XCTAssertFalse(FileManager.default.fileExists(atPath: retainedURL.path))
        XCTAssertTrue(fixture.uploader.jobs.isEmpty)
    }

    @MainActor
    func testUnacceptedProcessingFailureRetainsBothCopiesForRetry() async throws {
        let fixture = try PipelineFixture()
        defer { fixture.cleanUp() }
        fixture.core.processError = PipelineTestError.coreOffline
        fixture.core.lookupStatus = "recorded"
        let captureID = try fixture.receiveCapture()
        let retainedURL = try fixture.inbox.fileURL(for: captureID)

        await fixture.pipeline.resumePending()
        fixture.uploader.completeUpload(captureID: captureID)
        await fixture.pipeline.resumePending()

        let record = try fixture.record(captureID)
        XCTAssertEqual(record.state, .processing)
        XCTAssertEqual(record.failure?.message, PipelineTestError.coreOffline.localizedDescription)
        XCTAssertTrue(record.failure?.retryable == true)
        XCTAssertTrue(FileManager.default.fileExists(atPath: retainedURL.path))
        XCTAssertEqual(fixture.uploader.jobs.first?.state, .failed)
        XCTAssertTrue(fixture.uploader.jobs.first?.uploadComplete == true)
    }

    @MainActor
    func testCaptureCannotMoveToAReplacementCoreIdentity() async throws {
        let fixture = try PipelineFixture()
        defer { fixture.cleanUp() }
        let captureID = try fixture.receiveCapture()
        let retainedURL = try fixture.inbox.fileURL(for: captureID)

        await fixture.pipeline.resumePending()
        fixture.uploader.completeUpload(captureID: captureID)

        let replacementCore = PipelineTestCore()
        let replacementPipeline = WatchMeetingDeliveryPipeline(
            inbox: fixture.inbox,
            uploader: fixture.uploader,
            configurationProvider: {
                WatchMeetingDeliveryConfiguration(
                    coreURL: URL(string: "https://replacement-pilot.example")!,
                    deviceID: "replacement-device",
                    token: "replacement-token",
                    advertisedUploadEndpoint: nil
                )
            },
            coreProvider: { replacementCore }
        )
        await replacementPipeline.resumePending()

        let record = try fixture.record(captureID)
        XCTAssertEqual(record.coreOrigin, "https://pilot.example")
        XCTAssertEqual(record.coreDeviceID, "pilot-ios-test")
        XCTAssertEqual(record.state, .uploading)
        XCTAssertTrue(record.failure?.retryable == false)
        XCTAssertEqual(replacementCore.processCallCount, 0)
        XCTAssertTrue(FileManager.default.fileExists(atPath: retainedURL.path))
    }

    @MainActor
    func testBackgroundSessionCompletionWaitsForProcessingResult() async throws {
        let fixture = try PipelineFixture()
        defer { fixture.cleanUp() }
        fixture.core.blockProcessing = true
        let captureID = try fixture.receiveCapture()
        var completionCalled = false
        PilotBackgroundSessionEvents.shared.register(
            identifier: MeetingBackgroundUploadCoordinator.backgroundSessionIdentifier
        ) {
            completionCalled = true
        }

        fixture.pipeline.start()
        try await waitUntil { !fixture.uploader.jobs.isEmpty }
        fixture.uploader.completeUpload(captureID: captureID)
        let job = try XCTUnwrap(fixture.uploader.job(
            captureID: captureID.uuidString.lowercased()
        ))
        fixture.uploader.emit(.processingRequired(job))
        fixture.uploader.emit(.backgroundSessionEventsFinished)
        try await waitUntil { fixture.core.processStarted }

        XCTAssertFalse(completionCalled)
        fixture.core.releaseProcessing()
        try await waitUntil { completionCalled }
        XCTAssertEqual(try fixture.record(captureID).state, .coreAccepted)
    }

    @MainActor
    func testUnconfirmedRecoveryPreventsReplacementUploadPump() async throws {
        let fixture = try PipelineFixture()
        defer { fixture.cleanUp() }
        fixture.uploader.recoveryError = PipelineTestError.recoveryBlocked
        let captureID = try fixture.receiveCapture()

        await fixture.pipeline.resumePending()

        XCTAssertTrue(fixture.uploader.enqueueAttempts.isEmpty)
        XCTAssertTrue(fixture.core.createCaptureIDs.isEmpty)
        XCTAssertEqual(try fixture.record(captureID).state, .received)
    }

    @MainActor
    func testRelativeLegacyManifestEndpointStillRequestsOffOriginTicket() async throws {
        let fixture = try PipelineFixture(
            uploadEndpoint:
                "v1/devices/pilot-ios-test/meetings/{meeting_id}/recording"
        )
        defer { fixture.cleanUp() }
        let captureID = try fixture.receiveCapture()

        await fixture.pipeline.resumePending()

        let record = try fixture.record(captureID)
        let ticketRequest = try XCTUnwrap(fixture.core.ticketRequests.first)
        XCTAssertEqual(ticketRequest.meetingID, "core-meeting-1")
        XCTAssertEqual(ticketRequest.sha256, record.metadata.sha256)
        XCTAssertEqual(ticketRequest.sizeBytes, record.metadata.sizeBytes)
        XCTAssertEqual(ticketRequest.filename, record.metadata.originalFilename)
        let attempt = try XCTUnwrap(fixture.uploader.enqueueAttempts.first)
        XCTAssertEqual(
            attempt.endpoint,
            "v1/devices/pilot-ios-test/meetings/{meeting_id}/recording"
        )
        XCTAssertEqual(attempt.ticket?.uploadToken, "ticket-secret-1")
        XCTAssertEqual(
            attempt.ticket?.uploadURL,
            "https://uploads.pilot.example/v1/meeting-recording-uploads/ticket-1"
        )
    }

    @MainActor
    func testTicketIssuanceFailureFallsBackToSameOriginUpload() async throws {
        let fixture = try PipelineFixture(
            uploadEndpoint:
                "https://uploads.pilot.example/v1/meetings/{meeting_id}/recording"
        )
        defer { fixture.cleanUp() }
        fixture.core.ticketError = PipelineTestError.ticketUnavailable
        _ = try fixture.receiveCapture()

        await fixture.pipeline.resumePending()

        XCTAssertEqual(fixture.core.ticketRequests.count, 1)
        let attempt = try XCTUnwrap(fixture.uploader.enqueueAttempts.first)
        XCTAssertNil(attempt.endpoint)
        XCTAssertNil(attempt.ticket)
    }

    @MainActor
    func testEveryMismatchedTicketBindingFallsBackBeforeTicketUpload() async throws {
        for mismatch in PipelineTicketBindingMismatch.allCases {
            let fixture = try PipelineFixture(
                uploadEndpoint:
                    "v1/devices/pilot-ios-test/meetings/{meeting_id}/recording"
            )
            defer { fixture.cleanUp() }
            fixture.core.ticketBindingMismatch = mismatch
            let captureID = try fixture.receiveCapture()
            let retainedURL = try fixture.inbox.fileURL(for: captureID)

            await fixture.pipeline.resumePending()

            XCTAssertEqual(
                fixture.core.ticketRequests.count,
                1,
                "missing ticket request for \(mismatch)"
            )
            XCTAssertEqual(
                fixture.uploader.enqueueAttempts.count,
                1,
                "unexpected upload attempts for \(mismatch)"
            )
            let attempt = try XCTUnwrap(fixture.uploader.enqueueAttempts.first)
            XCTAssertNil(attempt.ticket, "mismatched \(mismatch) ticket escaped validation")
            XCTAssertEqual(
                attempt.endpoint,
                "v1/devices/pilot-ios-test/meetings/{meeting_id}/recording"
            )
            XCTAssertTrue(FileManager.default.fileExists(atPath: retainedURL.path))
            XCTAssertEqual(try fixture.record(captureID).state, .uploading)
        }
    }

    @MainActor
    func testRetryReconcilesStoredCoreRecordingBeforeReupload() async throws {
        let fixture = try PipelineFixture()
        defer { fixture.cleanUp() }
        let captureID = try fixture.receiveCapture()

        await fixture.pipeline.resumePending()
        fixture.uploader.failUpload(captureID: captureID)
        fixture.core.lookupRecording = MeetingRecording(
            filename: "watch-capture.m4a",
            contentType: "audio/m4a",
            sha256: try fixture.record(captureID).metadata.sha256,
            sizeBytes: Int(try fixture.record(captureID).metadata.sizeBytes),
            createdAt: "2026-08-11T05:00:00Z"
        )

        await fixture.pipeline.resumePending()

        XCTAssertEqual(fixture.core.lookupCallCount, 1)
        XCTAssertEqual(fixture.uploader.reconciledCaptureIDs, [
            captureID.uuidString.lowercased(),
        ])
        XCTAssertTrue(fixture.uploader.retryAttempts.isEmpty)
        XCTAssertEqual(fixture.core.processCallCount, 1)
        XCTAssertEqual(try fixture.record(captureID).state, .coreAccepted)
    }

    @MainActor
    func testRetryDoesNotReconcileADifferentCoreRecording() async throws {
        let fixture = try PipelineFixture()
        defer { fixture.cleanUp() }
        let captureID = try fixture.receiveCapture()
        let retainedURL = try fixture.inbox.fileURL(for: captureID)

        await fixture.pipeline.resumePending()
        fixture.uploader.failUpload(captureID: captureID)
        fixture.core.lookupRecording = MeetingRecording(
            filename: "different-recording.m4a",
            contentType: "audio/m4a",
            sha256: String(repeating: "0", count: 64),
            sizeBytes: Int(try fixture.record(captureID).metadata.sizeBytes),
            createdAt: "2026-08-11T05:00:00Z"
        )

        await fixture.pipeline.resumePending()

        XCTAssertEqual(fixture.core.lookupCallCount, 1)
        XCTAssertTrue(fixture.uploader.reconciledCaptureIDs.isEmpty)
        XCTAssertEqual(fixture.uploader.retryAttempts.count, 1)
        XCTAssertEqual(fixture.core.processCallCount, 0)
        XCTAssertTrue(FileManager.default.fileExists(atPath: retainedURL.path))
        XCTAssertEqual(try fixture.record(captureID).state, .uploading)
    }

    @MainActor
    func testRetryObtainsFreshOffOriginTicketWhenCoreHasNoRecording() async throws {
        let fixture = try PipelineFixture(
            uploadEndpoint:
                "https://uploads.pilot.example/v1/meetings/{meeting_id}/recording"
        )
        defer { fixture.cleanUp() }
        let captureID = try fixture.receiveCapture()

        await fixture.pipeline.resumePending()
        fixture.uploader.failUpload(captureID: captureID)
        await fixture.pipeline.resumePending()

        XCTAssertEqual(fixture.core.lookupCallCount, 1)
        XCTAssertEqual(fixture.core.ticketRequests.count, 2)
        XCTAssertEqual(
            fixture.uploader.enqueueAttempts.first?.ticket?.uploadToken,
            "ticket-secret-1"
        )
        XCTAssertEqual(
            fixture.uploader.retryAttempts.first?.ticket?.uploadToken,
            "ticket-secret-2"
        )
    }

    @MainActor
    private func waitUntil(
        timeout: Duration = .seconds(2),
        _ condition: @escaping @MainActor () -> Bool
    ) async throws {
        let clock = ContinuousClock()
        let deadline = clock.now.advanced(by: timeout)
        while !condition() {
            if clock.now >= deadline {
                XCTFail("Timed out waiting for asynchronous pipeline state")
                return
            }
            try await Task.sleep(for: .milliseconds(10))
        }
    }
}

private enum PipelineTestError: LocalizedError {
    case lostResponse
    case coreOffline
    case ticketUnavailable
    case recoveryBlocked

    var errorDescription: String? {
        switch self {
        case .lostResponse: "The accepted response was lost."
        case .coreOffline: "Pilot Core is temporarily offline."
        case .ticketUnavailable: "Upload ticket issuance is unavailable."
        case .recoveryBlocked: "An orphaned background upload is still cancelling."
        }
    }
}

private enum PipelineTicketBindingMismatch: String, CaseIterable {
    case meetingID
    case filename
    case contentType
    case sha256
    case sizeBytes
}

@MainActor
private final class PipelineFixture {
    let rootDirectory: URL
    let inbox: PipelineTestInbox
    let uploader = PipelineTestUploader()
    let core = PipelineTestCore()
    let pipeline: WatchMeetingDeliveryPipeline

    init(uploadEndpoint: String? = nil) throws {
        rootDirectory = FileManager.default.temporaryDirectory.appendingPathComponent(
            "pilot-watch-pipeline-\(UUID().uuidString)",
            isDirectory: true
        )
        try FileManager.default.createDirectory(
            at: rootDirectory,
            withIntermediateDirectories: true
        )
        let store = try WatchMeetingInboxStore(
            rootDirectory: rootDirectory.appendingPathComponent("inbox", isDirectory: true)
        )
        inbox = PipelineTestInbox(store: store)
        pipeline = WatchMeetingDeliveryPipeline(
            inbox: inbox,
            uploader: uploader,
            configurationProvider: {
                WatchMeetingDeliveryConfiguration(
                    coreURL: URL(string: "https://pilot.example")!,
                    deviceID: "pilot-ios-test",
                    token: "secret-not-ledgered",
                    advertisedUploadEndpoint: uploadEndpoint
                )
            },
            coreProvider: { [core] in core }
        )
    }

    func receiveCapture() throws -> UUID {
        let captureID = UUID()
        let audio = Data("watch meeting audio \(captureID.uuidString)".utf8)
        let sourceURL = rootDirectory.appendingPathComponent("source-\(captureID).m4a")
        try audio.write(to: sourceURL, options: .atomic)
        let metadata = try WatchMeetingTransferMetadata(
            captureID: captureID,
            title: "Watch planning meeting",
            startedAt: Date(timeIntervalSince1970: 1_786_421_234),
            durationSeconds: 42,
            sha256: try WatchMeetingFileIntegrity.sha256Hex(at: sourceURL),
            sizeBytes: Int64(audio.count),
            originalFilename: "watch-capture.m4a"
        )
        _ = try inbox.store.receiveSynchronously(fileURL: sourceURL, metadata: metadata)
        return captureID
    }

    func record(_ captureID: UUID) throws -> WatchMeetingInboxRecord {
        try XCTUnwrap(inbox.allCaptures().first(where: { $0.id == captureID }))
    }

    func cleanUp() {
        try? FileManager.default.removeItem(at: rootDirectory)
    }
}

@MainActor
private final class PipelineTestInbox: WatchMeetingInboxServing {
    let store: WatchMeetingInboxStore

    init(store: WatchMeetingInboxStore) {
        self.store = store
    }

    func start() {}
    func pendingCaptures() throws -> [WatchMeetingInboxRecord] { store.pendingRecords() }
    func allCaptures() throws -> [WatchMeetingInboxRecord] { store.allRecords() }
    func fileURL(for captureID: UUID) throws -> URL { try store.fileURL(for: captureID) }
    func events() throws -> AsyncStream<WatchMeetingInboxEvent> { store.events() }
    func bindCoreDestination(
        captureID: UUID,
        coreOrigin: String,
        coreDeviceID: String
    ) throws -> WatchMeetingInboxRecord {
        try store.bindCoreDestination(
            captureID: captureID,
            coreOrigin: coreOrigin,
            coreDeviceID: coreDeviceID
        )
    }
    func bindCoreMeeting(captureID: UUID, coreMeetingID: String) throws -> WatchMeetingInboxRecord {
        try store.bindCoreMeeting(captureID: captureID, coreMeetingID: coreMeetingID)
    }
    func markUploading(captureID: UUID) throws -> WatchMeetingInboxRecord {
        try store.markUploading(captureID: captureID)
    }
    func markUploaded(captureID: UUID) throws -> WatchMeetingInboxRecord {
        try store.markUploaded(captureID: captureID)
    }
    func markProcessing(captureID: UUID) throws -> WatchMeetingInboxRecord {
        try store.markProcessing(captureID: captureID)
    }
    func markCoreAccepted(captureID: UUID) throws -> WatchMeetingInboxRecord {
        try store.markCoreAccepted(captureID: captureID).0
    }
    func markCoreFailed(
        captureID: UUID,
        message: String,
        retryable: Bool
    ) throws -> WatchMeetingInboxRecord {
        try store.markCoreFailed(
            captureID: captureID,
            message: message,
            retryable: retryable
        ).0
    }
}

@MainActor
private final class PipelineTestUploader: MeetingBackgroundUploading {
    struct Attempt {
        let endpoint: String?
        let ticket: MeetingRecordingUploadTicket?
    }

    var onEvent: ((MeetingBackgroundUploadEvent) -> Void)?
    private(set) var jobs: [MeetingBackgroundUploadJob] = []
    private(set) var enqueueAttempts: [Attempt] = []
    private(set) var retryAttempts: [Attempt] = []
    private(set) var reconciledCaptureIDs: [String] = []
    var recoveryError: Error?

    func enqueue(
        captureID: String,
        meetingID: String,
        recordingURL: URL,
        coreURL: URL,
        advertisedUploadEndpoint: String?,
        uploadTicket: MeetingRecordingUploadTicket?,
        deviceID: String,
        token: String
    ) throws -> MeetingBackgroundUploadJob {
        enqueueAttempts.append(Attempt(
            endpoint: advertisedUploadEndpoint,
            ticket: uploadTicket
        ))
        let job = MeetingBackgroundUploadJob(
            captureID: captureID,
            meetingID: meetingID,
            recordingPath: recordingURL.path,
            state: .uploading,
            uploadComplete: false,
            taskIdentifier: 1,
            attemptCount: 1,
            failureMessage: nil,
            updatedAt: .now
        )
        jobs.append(job)
        return job
    }

    func retryUpload(
        captureID: String,
        coreURL: URL,
        advertisedUploadEndpoint: String?,
        uploadTicket: MeetingRecordingUploadTicket?,
        deviceID: String,
        token: String
    ) throws -> MeetingBackgroundUploadJob {
        retryAttempts.append(Attempt(
            endpoint: advertisedUploadEndpoint,
            ticket: uploadTicket
        ))
        let index = try index(captureID)
        if jobs[index].uploadComplete {
            jobs[index].state = .awaitingProcessing
        } else {
            jobs[index].state = .uploading
            jobs[index].attemptCount += 1
        }
        jobs[index].failureMessage = nil
        return jobs[index]
    }

    func recover() async throws -> MeetingBackgroundUploadRecovery {
        if let recoveryError { throw recoveryError }
        return MeetingBackgroundUploadRecovery(
            jobs: jobs,
            processingRequiredCaptureIDs: [],
            failedCaptureIDs: [],
            orphanedTaskIdentifiers: []
        )
    }

    func markUploadReconciled(captureID: String) throws -> MeetingBackgroundUploadJob {
        let index = try index(captureID)
        jobs[index].uploadComplete = true
        jobs[index].taskIdentifier = nil
        jobs[index].state = .awaitingProcessing
        jobs[index].failureMessage = nil
        reconciledCaptureIDs.append(captureID)
        return jobs[index]
    }

    func markProcessingStarted(captureID: String) throws {
        let index = try index(captureID)
        jobs[index].state = .processing
    }

    func markProcessingFailed(captureID: String, message: String) throws {
        let index = try index(captureID)
        jobs[index].state = .failed
        jobs[index].failureMessage = message
    }

    func markProcessingCompleted(captureID: String) throws {
        let index = try index(captureID)
        jobs[index].state = .completed
    }

    func removeCompleted(captureID: String) throws {
        let index = try index(captureID)
        jobs.remove(at: index)
    }

    func job(captureID: String) -> MeetingBackgroundUploadJob? {
        jobs.first { $0.captureID == captureID }
    }

    func completeUpload(captureID: UUID) {
        let key = captureID.uuidString.lowercased()
        guard let index = jobs.firstIndex(where: { $0.captureID == key }) else { return }
        jobs[index].uploadComplete = true
        jobs[index].taskIdentifier = nil
        jobs[index].state = .awaitingProcessing
    }

    func failUpload(captureID: UUID) {
        let key = captureID.uuidString.lowercased()
        guard let index = jobs.firstIndex(where: { $0.captureID == key }) else { return }
        jobs[index].uploadComplete = false
        jobs[index].taskIdentifier = nil
        jobs[index].state = .failed
        jobs[index].failureMessage = "The upload response was lost."
    }

    func emit(_ event: MeetingBackgroundUploadEvent) {
        onEvent?(event)
    }

    private func index(_ captureID: String) throws -> Int {
        guard let index = jobs.firstIndex(where: { $0.captureID == captureID }) else {
            throw MeetingBackgroundUploadError.jobNotFound(captureID)
        }
        return index
    }
}

@MainActor
private final class PipelineTestCore: WatchMeetingCoreServing, @unchecked Sendable {
    struct TicketRequest: Equatable {
        let meetingID: String
        let sha256: String
        let sizeBytes: Int64
        let filename: String
    }

    var processError: Error?
    var ticketError: Error?
    var ticketBindingMismatch: PipelineTicketBindingMismatch?
    var lookupStatus = "recorded"
    var lookupRecording: MeetingRecording?
    var blockProcessing = false
    private(set) var processStarted = false
    private var processContinuation: CheckedContinuation<Void, Never>?
    private(set) var createCaptureIDs: [String] = []
    private(set) var processCallCount = 0
    private(set) var lookupCallCount = 0
    private(set) var ticketRequests: [TicketRequest] = []

    func createMeeting(
        title: String,
        startedAt: Date?,
        sourceCaptureID: String?
    ) async throws -> PilotMeeting {
        createCaptureIDs.append(sourceCaptureID ?? "")
        return meeting(id: "core-meeting-1", title: title, status: "created")
    }

    func meeting(_ meetingID: String) async throws -> PilotMeetingDetail {
        lookupCallCount += 1
        return PilotMeetingDetail(
            id: meetingID,
            title: "Watch planning meeting",
            language: "en-AU",
            sourceDeviceID: "pilot-ios-test",
            sourceCaptureID: createCaptureIDs.first,
            startedAt: "2026-08-11T05:00:00Z",
            endedAt: nil,
            status: lookupStatus,
            summary: nil,
            recording: lookupRecording,
            participants: [],
            transcript: [],
            decisions: [],
            actionItems: []
        )
    }

    func meetingRecordingUploadTicket(
        meetingID: String,
        sha256: String,
        sizeBytes: Int64,
        filename: String
    ) async throws -> MeetingRecordingUploadTicket {
        ticketRequests.append(TicketRequest(
            meetingID: meetingID,
            sha256: sha256,
            sizeBytes: sizeBytes,
            filename: filename
        ))
        if let ticketError { throw ticketError }
        let mismatch = ticketBindingMismatch
        return MeetingRecordingUploadTicket(
            schemaVersion: "pilot.meeting-recording-upload-ticket.v1",
            ticketID: "ticket-\(ticketRequests.count)",
            meetingID: mismatch == .meetingID ? "different-meeting" : meetingID,
            uploadURL:
                "https://uploads.pilot.example/v1/meeting-recording-uploads/ticket-\(ticketRequests.count)",
            uploadToken: "ticket-secret-\(ticketRequests.count)",
            expiresAt: "2099-08-11T05:17:03.123Z",
            recording: MeetingRecordingUploadBinding(
                filename: mismatch == .filename ? "different.m4a" : filename,
                contentType: mismatch == .contentType ? "audio/wav" : "audio/m4a",
                sha256: mismatch == .sha256
                    ? String(repeating: "0", count: 64)
                    : sha256,
                sizeBytes: mismatch == .sizeBytes ? sizeBytes + 1 : sizeBytes
            )
        )
    }

    func processMeeting(_ meetingID: String) async throws -> PilotMeeting {
        processCallCount += 1
        processStarted = true
        if blockProcessing {
            await withCheckedContinuation { continuation in
                processContinuation = continuation
            }
        }
        if let processError { throw processError }
        return meeting(id: meetingID, title: "Watch planning meeting", status: "processing")
    }

    func releaseProcessing() {
        blockProcessing = false
        processContinuation?.resume()
        processContinuation = nil
    }

    private func meeting(id: String, title: String, status: String) -> PilotMeeting {
        PilotMeeting(
            id: id,
            title: title,
            language: "en-AU",
            sourceDeviceID: "pilot-ios-test",
            sourceCaptureID: createCaptureIDs.first,
            startedAt: "2026-08-11T05:00:00Z",
            endedAt: nil,
            status: status,
            summary: nil,
            hasRecording: status != "created",
            transcriptSegmentCount: nil,
            actionItemCount: nil
        )
    }
}
