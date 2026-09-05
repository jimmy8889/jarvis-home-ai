import Foundation
import XCTest
@testable import Pilot

final class MeetingBackgroundUploadCoordinatorTests: XCTestCase {
    @MainActor
    func testSameOriginUploadUsesPermanentDeviceAuthentication() throws {
        let recordingURL = URL(fileURLWithPath: "/tmp/meeting one.m4a")
        let request = try MeetingBackgroundUploadCoordinator.uploadRequest(
            coreURL: try XCTUnwrap(URL(string: "https://pilot.example")),
            deviceID: "pilot-ios-james",
            token: "device-secret",
            meetingID: "meeting-1",
            recordingURL: recordingURL,
            advertisedUploadEndpoint:
                "https://pilot.example/v1/meetings/{meeting_id}/recording"
        )

        XCTAssertEqual(request.httpMethod, "PUT")
        XCTAssertEqual(
            request.url?.absoluteString,
            "https://pilot.example/v1/meetings/meeting-1/recording"
        )
        XCTAssertEqual(
            request.value(forHTTPHeaderField: "Authorization"),
            "Bearer device-secret"
        )
        XCTAssertEqual(
            request.value(forHTTPHeaderField: "X-Pilot-Device-ID"),
            "pilot-ios-james"
        )
        XCTAssertEqual(
            request.value(forHTTPHeaderField: "X-Pilot-Filename"),
            "meeting one.m4a"
        )
        XCTAssertEqual(request.value(forHTTPHeaderField: "Content-Type"), "audio/m4a")

        let fallback = try MeetingBackgroundUploadCoordinator.uploadRequest(
            coreURL: try XCTUnwrap(URL(string: "http://pilot.local:8770")),
            deviceID: "pilot-ios-james",
            token: "device-secret",
            meetingID: "meeting-1",
            recordingURL: recordingURL,
            advertisedUploadEndpoint: nil
        )
        XCTAssertEqual(
            fallback.url?.path,
            "/v1/devices/pilot-ios-james/meetings/meeting-1/recording"
        )
    }

    @MainActor
    func testOffOriginUploadFailsClosedWithoutTicket() throws {
        let recordingURL = URL(fileURLWithPath: "/tmp/meeting.m4a")
        XCTAssertThrowsError(
            try MeetingBackgroundUploadCoordinator.uploadRequest(
                coreURL: try XCTUnwrap(URL(string: "http://pilot.local:8770")),
                deviceID: "pilot-ios-james",
                token: "device-secret",
                meetingID: "meeting-1",
                recordingURL: recordingURL,
                advertisedUploadEndpoint:
                    "https://uploads.pilot.example/v1/meetings/{meeting_id}/recording"
            )
        ) { error in
            XCTAssertEqual(
                error as? MeetingBackgroundUploadError,
                .invalidAdvertisedEndpoint
            )
        }

    }

    @MainActor
    func testOffOriginUploadUsesOnlyFractionalExpiryTicketAuthentication() throws {
        let recordingURL = URL(fileURLWithPath: "/tmp/retained-watch-name.m4a")
        let request = try MeetingBackgroundUploadCoordinator.uploadRequest(
            coreURL: try XCTUnwrap(URL(string: "http://pilot.local:8770")),
            deviceID: "pilot-ios-james",
            token: "device-secret",
            meetingID: "meeting-1",
            recordingURL: recordingURL,
            advertisedUploadEndpoint:
                "https://uploads.pilot.example/v1/meetings/{meeting_id}/recording",
            uploadTicket: MeetingRecordingUploadTicket(
                schemaVersion: "pilot.meeting-recording-upload-ticket.v1",
                ticketID: "ticket-1",
                meetingID: "meeting-1",
                uploadURL: "https://uploads.pilot.example/v1/meeting-recording-uploads/ticket-1",
                uploadToken: "short-lived-ticket-secret",
                expiresAt: "2099-08-11T05:17:03.123456Z",
                recording: MeetingRecordingUploadBinding(
                    filename: "meeting one.m4a",
                    contentType: "audio/m4a",
                    sha256: String(repeating: "a", count: 64),
                    sizeBytes: 14
                )
            )
        )

        XCTAssertEqual(
            request.url?.absoluteString,
            "https://uploads.pilot.example/v1/meeting-recording-uploads/ticket-1"
        )
        XCTAssertEqual(
            request.value(forHTTPHeaderField: "Authorization"),
            "Bearer short-lived-ticket-secret"
        )
        XCTAssertNil(request.value(forHTTPHeaderField: "X-Pilot-Device-ID"))
        XCTAssertNil(request.value(forHTTPHeaderField: "X-Pilot-Filename"))
        XCTAssertFalse(
            request.allHTTPHeaderFields?.values.contains(where: {
                $0.contains("device-secret") || $0.contains("pilot-ios-james")
            }) == true
        )
    }

    @MainActor
    func testCoordinatorRejectsWrongMeetingAndContentTypeTickets() throws {
        let recordingURL = URL(fileURLWithPath: "/tmp/meeting.m4a")
        let binding = MeetingRecordingUploadBinding(
            filename: "meeting.m4a",
            contentType: "audio/m4a",
            sha256: String(repeating: "a", count: 64),
            sizeBytes: 14
        )
        let tickets = [
            MeetingRecordingUploadTicket(
                schemaVersion: "pilot.meeting-recording-upload-ticket.v1",
                ticketID: "wrong-meeting-ticket",
                meetingID: "different-meeting",
                uploadURL:
                    "https://uploads.pilot.example/v1/meeting-recording-uploads/wrong-meeting-ticket",
                uploadToken: "wrong-meeting-token",
                expiresAt: "2099-08-11T05:17:03.123Z",
                recording: binding
            ),
            MeetingRecordingUploadTicket(
                schemaVersion: "pilot.meeting-recording-upload-ticket.v1",
                ticketID: "wrong-type-ticket",
                meetingID: "meeting-1",
                uploadURL:
                    "https://uploads.pilot.example/v1/meeting-recording-uploads/wrong-type-ticket",
                uploadToken: "wrong-type-token",
                expiresAt: "2099-08-11T05:17:03.123Z",
                recording: MeetingRecordingUploadBinding(
                    filename: binding.filename,
                    contentType: "audio/wav",
                    sha256: binding.sha256,
                    sizeBytes: binding.sizeBytes
                )
            ),
        ]

        for ticket in tickets {
            XCTAssertThrowsError(
                try MeetingBackgroundUploadCoordinator.uploadRequest(
                    coreURL: try XCTUnwrap(URL(string: "https://pilot.example")),
                    deviceID: "pilot-ios-james",
                    token: "permanent-device-secret",
                    meetingID: "meeting-1",
                    recordingURL: recordingURL,
                    advertisedUploadEndpoint: nil,
                    uploadTicket: ticket
                )
            ) { error in
                XCTAssertEqual(
                    error as? MeetingBackgroundUploadError,
                    .invalidUploadTicket
                )
            }
        }
    }

    func testTicketDecodesCompleteCoreBinding() throws {
        let data = Data(
            """
            {
              "schema_version":"pilot.meeting-recording-upload-ticket.v1",
              "ticket_id":"ticket-123",
              "meeting_id":"meeting-123",
              "upload_url":"https://uploads.pilot.example/v1/meeting-recording-uploads/ticket-123",
              "upload_token":"scoped-secret",
              "expires_at":"2099-08-11T05:17:03.123456+00:00",
              "recording":{
                "filename":"watch-capture.m4a",
                "content_type":"audio/m4a",
                "sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "size_bytes":4242
              }
            }
            """.utf8
        )

        let ticket = try JSONDecoder().decode(
            MeetingRecordingUploadTicket.self,
            from: data
        )
        XCTAssertEqual(ticket.ticketID, "ticket-123")
        XCTAssertEqual(ticket.meetingID, "meeting-123")
        XCTAssertEqual(ticket.recording.filename, "watch-capture.m4a")
        XCTAssertEqual(ticket.recording.contentType, "audio/m4a")
        XCTAssertEqual(ticket.recording.sizeBytes, 4242)
        XCTAssertTrue(ticket.isBound(
            toMeetingID: "meeting-123",
            filename: "watch-capture.m4a",
            sha256: String(repeating: "A", count: 64),
            sizeBytes: 4242
        ))
    }

    @MainActor
    func testEnqueueUsesFileTaskPersistsMappingAndNeverLedgersToken() throws {
        let ledger = TestMeetingUploadLedger()
        let transport = TestMeetingUploadTransport(firstTaskIdentifier: 41)
        let recordingURL = try makeRecording()
        defer { try? FileManager.default.removeItem(at: recordingURL) }
        let coordinator = MeetingBackgroundUploadCoordinator(
            ledger: ledger,
            transport: transport,
            now: { Date(timeIntervalSince1970: 10) }
        )

        let job = try coordinator.enqueue(
            captureID: "watch-capture-1",
            meetingID: "meeting-1",
            recordingURL: recordingURL,
            coreURL: try XCTUnwrap(URL(string: "http://pilot.local:8770")),
            advertisedUploadEndpoint: nil,
            deviceID: "pilot-ios-james",
            token: "do-not-persist-this-token"
        )

        XCTAssertEqual(job.state, .uploading)
        XCTAssertEqual(job.taskIdentifier, 41)
        XCTAssertEqual(transport.createdTasks.count, 1)
        XCTAssertEqual(transport.createdTasks[0].fileURL, recordingURL)
        XCTAssertEqual(
            transport.createdTasks[0].request.value(
                forHTTPHeaderField: "Authorization"
            ),
            "Bearer do-not-persist-this-token"
        )
        XCTAssertTrue(transport.resumedTaskIdentifiers.contains(41))
        let persisted = try XCTUnwrap(ledger.data)
        XCTAssertFalse(
            String(decoding: persisted, as: UTF8.self)
                .contains("do-not-persist-this-token")
        )
    }

    @MainActor
    func testTicketUploadLedgerContainsNeitherTicketNorDeviceToken() throws {
        let ledger = TestMeetingUploadLedger()
        let transport = TestMeetingUploadTransport(firstTaskIdentifier: 42)
        let recordingURL = try makeRecording()
        defer { try? FileManager.default.removeItem(at: recordingURL) }
        let coordinator = MeetingBackgroundUploadCoordinator(
            ledger: ledger,
            transport: transport
        )

        _ = try coordinator.enqueue(
            captureID: "watch-capture-ticket",
            meetingID: "meeting-ticket",
            recordingURL: recordingURL,
            coreURL: try XCTUnwrap(URL(string: "https://pilot.example")),
            advertisedUploadEndpoint:
                "https://uploads.pilot.example/v1/meetings/{meeting_id}/recording",
            uploadTicket: MeetingRecordingUploadTicket(
                schemaVersion: "pilot.meeting-recording-upload-ticket.v1",
                ticketID: "ticket-42",
                meetingID: "meeting-ticket",
                uploadURL: "https://uploads.pilot.example/v1/meeting-recording-uploads/ticket-42",
                uploadToken: "short-lived-do-not-persist",
                expiresAt: "2099-08-11T05:17:03.123Z",
                recording: MeetingRecordingUploadBinding(
                    filename: recordingURL.lastPathComponent,
                    contentType: "audio/m4a",
                    sha256: try WatchMeetingFileIntegrity.sha256Hex(at: recordingURL),
                    sizeBytes: 14
                )
            ),
            deviceID: "pilot-ios-james",
            token: "permanent-do-not-persist"
        )

        let request = try XCTUnwrap(transport.createdTasks.first?.request)
        XCTAssertEqual(
            request.value(forHTTPHeaderField: "Authorization"),
            "Bearer short-lived-do-not-persist"
        )
        XCTAssertNil(request.value(forHTTPHeaderField: "X-Pilot-Device-ID"))
        let persisted = String(decoding: try XCTUnwrap(ledger.data), as: UTF8.self)
        XCTAssertFalse(persisted.contains("short-lived-do-not-persist"))
        XCTAssertFalse(persisted.contains("permanent-do-not-persist"))
    }

    func testForegroundMeetingUploadUsesTicketDespiteRelativeLegacyEndpoint() async throws {
        let recordingURL = try makeRecording()
        defer { try? FileManager.default.removeItem(at: recordingURL) }
        let probe = ForegroundMeetingUploadProbe()
        let api = PilotAPI(
            coreURL: try XCTUnwrap(URL(string: "https://pilot.example")),
            deviceID: "pilot-ios-james",
            token: "permanent-device-secret",
            meetingTicketIssuer: { meetingID, sha256, sizeBytes, filename in
                await probe.issueTicket(
                    meetingID: meetingID,
                    sha256: sha256,
                    sizeBytes: sizeBytes,
                    filename: filename
                )
            },
            meetingUploadPerformer: { request, fileURL in
                try await probe.perform(request: request, fileURL: fileURL)
            }
        )

        try await api.uploadMeetingRecording(
            meetingID: "meeting-foreground",
            recordingURL: recordingURL,
            uploadEndpoint:
                "v1/devices/pilot-ios-james/meetings/{meeting_id}/recording"
        )

        let ticketInputs = await probe.ticketInputs
        let ticketInput = try XCTUnwrap(ticketInputs.first)
        XCTAssertEqual(ticketInput.meetingID, "meeting-foreground")
        XCTAssertEqual(ticketInput.filename, recordingURL.lastPathComponent)
        XCTAssertEqual(ticketInput.sizeBytes, 14)
        XCTAssertEqual(ticketInput.sha256.count, 64)
        let uploadRequests = await probe.uploadRequests
        let request = try XCTUnwrap(uploadRequests.first)
        XCTAssertEqual(request.url?.host, "uploads.pilot.example")
        XCTAssertEqual(
            request.value(forHTTPHeaderField: "Authorization"),
            "Bearer foreground-ticket-secret"
        )
        XCTAssertNil(request.value(forHTTPHeaderField: "X-Pilot-Device-ID"))
        XCTAssertNil(request.value(forHTTPHeaderField: "X-Pilot-Filename"))
    }

    func testForegroundTicketFailureNeverSendsDeviceTokenOffOrigin() async throws {
        let recordingURL = try makeRecording()
        defer { try? FileManager.default.removeItem(at: recordingURL) }
        let probe = ForegroundMeetingUploadProbe()
        let api = PilotAPI(
            coreURL: try XCTUnwrap(URL(string: "https://pilot.example")),
            deviceID: "pilot-ios-james",
            token: "permanent-device-secret",
            meetingTicketIssuer: { _, _, _, _ in
                throw URLError(.unsupportedURL)
            },
            meetingUploadPerformer: { request, fileURL in
                try await probe.perform(request: request, fileURL: fileURL)
            }
        )

        try await api.uploadMeetingRecording(
            meetingID: "meeting-fallback",
            recordingURL: recordingURL,
            uploadEndpoint:
                "https://uploads.pilot.example/v1/meetings/{meeting_id}/recording"
        )

        let uploadRequests = await probe.uploadRequests
        let request = try XCTUnwrap(uploadRequests.first)
        XCTAssertEqual(request.url?.host, "pilot.example")
        XCTAssertEqual(
            request.url?.path,
            "/v1/devices/pilot-ios-james/meetings/meeting-fallback/recording"
        )
        XCTAssertEqual(
            request.value(forHTTPHeaderField: "Authorization"),
            "Bearer permanent-device-secret"
        )
        XCTAssertEqual(
            request.value(forHTTPHeaderField: "X-Pilot-Device-ID"),
            "pilot-ios-james"
        )
    }

    func testForegroundRejectsEveryMismatchedTicketBindingBeforeUpload() async throws {
        for mismatch in ForegroundTicketBindingMismatch.allCases {
            let recordingURL = try makeRecording()
            defer { try? FileManager.default.removeItem(at: recordingURL) }
            let probe = ForegroundMeetingUploadProbe(ticketBindingMismatch: mismatch)
            let api = PilotAPI(
                coreURL: try XCTUnwrap(URL(string: "https://pilot.example")),
                deviceID: "pilot-ios-james",
                token: "permanent-device-secret",
                meetingTicketIssuer: { meetingID, sha256, sizeBytes, filename in
                    await probe.issueTicket(
                        meetingID: meetingID,
                        sha256: sha256,
                        sizeBytes: sizeBytes,
                        filename: filename
                    )
                },
                meetingUploadPerformer: { request, fileURL in
                    try await probe.perform(request: request, fileURL: fileURL)
                }
            )

            try await api.uploadMeetingRecording(
                meetingID: "meeting-foreground",
                recordingURL: recordingURL,
                uploadEndpoint:
                    "v1/devices/pilot-ios-james/meetings/{meeting_id}/recording"
            )

            let uploadRequests = await probe.uploadRequests
            XCTAssertEqual(
                uploadRequests.count,
                1,
                "unexpected request count for \(mismatch)"
            )
            let request = try XCTUnwrap(uploadRequests.first)
            XCTAssertEqual(request.url?.host, "pilot.example")
            XCTAssertEqual(
                request.value(forHTTPHeaderField: "Authorization"),
                "Bearer permanent-device-secret"
            )
            XCTAssertNotEqual(
                request.value(forHTTPHeaderField: "Authorization"),
                "Bearer foreground-ticket-secret",
                "mismatched \(mismatch) ticket escaped validation"
            )
            XCTAssertEqual(
                request.value(forHTTPHeaderField: "X-Pilot-Device-ID"),
                "pilot-ios-james"
            )
        }
    }

    @MainActor
    func testRelaunchRecoveryMapsSystemTaskBackToCaptureAndMeeting() async throws {
        let ledger = TestMeetingUploadLedger()
        let firstTransport = TestMeetingUploadTransport(firstTaskIdentifier: 72)
        let recordingURL = try makeRecording()
        defer { try? FileManager.default.removeItem(at: recordingURL) }
        let firstCoordinator = MeetingBackgroundUploadCoordinator(
            ledger: ledger,
            transport: firstTransport
        )
        _ = try firstCoordinator.enqueue(
            captureID: "watch-capture-72",
            meetingID: "meeting-72",
            recordingURL: recordingURL,
            coreURL: try XCTUnwrap(URL(string: "http://pilot.local:8770")),
            advertisedUploadEndpoint: nil,
            deviceID: "pilot-ios-james",
            token: "secret"
        )
        let created = try XCTUnwrap(firstTransport.createdTasks.first)

        let restoredTransport = TestMeetingUploadTransport(firstTaskIdentifier: 90)
        restoredTransport.snapshots = [
            MeetingBackgroundUploadTaskSnapshot(
                taskIdentifier: 72,
                taskDescription: created.taskDescription,
                state: .suspended
            )
        ]
        let restoredCoordinator = MeetingBackgroundUploadCoordinator(
            ledger: ledger,
            transport: restoredTransport
        )
        let recovery = try await restoredCoordinator.recover()

        XCTAssertEqual(recovery.jobs.count, 1)
        XCTAssertEqual(recovery.jobs[0].captureID, "watch-capture-72")
        XCTAssertEqual(recovery.jobs[0].meetingID, "meeting-72")
        XCTAssertEqual(recovery.jobs[0].taskIdentifier, 72)
        XCTAssertEqual(recovery.jobs[0].state, .uploading)
        XCTAssertTrue(restoredTransport.resumedTaskIdentifiers.contains(72))
        XCTAssertFalse(restoredTransport.cancelledTaskIdentifiers.contains(72))
        XCTAssertTrue(recovery.orphanedTaskIdentifiers.isEmpty)
    }

    @MainActor
    func testCorruptLedgerCancelsRecognizableOrphanBeforeRecoverySucceeds() async throws {
        let ledger = TestMeetingUploadLedger()
        let initialTransport = TestMeetingUploadTransport(firstTaskIdentifier: 81)
        let recordingURL = try makeRecording()
        defer { try? FileManager.default.removeItem(at: recordingURL) }
        let initialCoordinator = MeetingBackgroundUploadCoordinator(
            ledger: ledger,
            transport: initialTransport
        )
        _ = try initialCoordinator.enqueue(
            captureID: "watch-capture-81",
            meetingID: "meeting-81",
            recordingURL: recordingURL,
            coreURL: try XCTUnwrap(URL(string: "https://pilot.example")),
            advertisedUploadEndpoint: nil,
            deviceID: "pilot-ios-james",
            token: "secret"
        )
        let taskDescription = try XCTUnwrap(
            initialTransport.createdTasks.first?.taskDescription
        )
        try ledger.save(Data("{corrupt-ledger".utf8))

        let restoredTransport = TestMeetingUploadTransport(firstTaskIdentifier: 90)
        restoredTransport.cancellationPollsBeforeDisappearance = 1
        restoredTransport.snapshots = [
            MeetingBackgroundUploadTaskSnapshot(
                taskIdentifier: 81,
                taskDescription: taskDescription,
                state: .running
            ),
        ]
        let restoredCoordinator = MeetingBackgroundUploadCoordinator(
            ledger: ledger,
            transport: restoredTransport
        )

        let recovery = try await restoredCoordinator.recover()

        XCTAssertTrue(recovery.jobs.isEmpty)
        XCTAssertEqual(recovery.orphanedTaskIdentifiers, [81])
        XCTAssertEqual(restoredTransport.cancelledTaskIdentifiers, [81])
        XCTAssertTrue(restoredTransport.snapshots.isEmpty)
        XCTAssertGreaterThanOrEqual(restoredTransport.outstandingTaskCallCount, 3)
    }

    @MainActor
    func testSuccessfulUploadRequiresDurableProcessingBeforeCompletion() async throws {
        let ledger = TestMeetingUploadLedger()
        let transport = TestMeetingUploadTransport(firstTaskIdentifier: 8)
        let recordingURL = try makeRecording()
        defer { try? FileManager.default.removeItem(at: recordingURL) }
        let coordinator = MeetingBackgroundUploadCoordinator(
            ledger: ledger,
            transport: transport
        )
        _ = try coordinator.enqueue(
            captureID: "watch-capture-8",
            meetingID: "meeting-8",
            recordingURL: recordingURL,
            coreURL: try XCTUnwrap(URL(string: "http://pilot.local:8770")),
            advertisedUploadEndpoint: nil,
            deviceID: "pilot-ios-james",
            token: "secret"
        )
        let processingRequired = expectation(description: "processing required")
        coordinator.onEvent = { event in
            if case .processingRequired = event {
                processingRequired.fulfill()
            }
        }

        transport.complete(taskIdentifier: 8, statusCode: 201)
        await fulfillment(of: [processingRequired], timeout: 1)

        XCTAssertEqual(coordinator.job(captureID: "watch-capture-8")?.state, .awaitingProcessing)
        XCTAssertEqual(coordinator.job(captureID: "watch-capture-8")?.uploadComplete, true)
        XCTAssertTrue(FileManager.default.fileExists(atPath: recordingURL.path))

        try coordinator.markProcessingStarted(captureID: "watch-capture-8")

        let relaunched = MeetingBackgroundUploadCoordinator(
            ledger: ledger,
            transport: TestMeetingUploadTransport(firstTaskIdentifier: 9)
        )
        let recovery = try await relaunched.recover()
        XCTAssertEqual(recovery.processingRequiredCaptureIDs, ["watch-capture-8"])
        XCTAssertEqual(recovery.jobs[0].state, .awaitingProcessing)

        try relaunched.markProcessingStarted(captureID: "watch-capture-8")
        try relaunched.markProcessingCompleted(captureID: "watch-capture-8")
        XCTAssertEqual(relaunched.job(captureID: "watch-capture-8")?.state, .completed)
        try relaunched.removeCompleted(captureID: "watch-capture-8")
        XCTAssertTrue(relaunched.jobs.isEmpty)
    }

    @MainActor
    func testUploadFailureRetainsJobAndServerDetailForRetry() async throws {
        let ledger = TestMeetingUploadLedger()
        let transport = TestMeetingUploadTransport(firstTaskIdentifier: 5)
        let recordingURL = try makeRecording()
        defer { try? FileManager.default.removeItem(at: recordingURL) }
        let coordinator = MeetingBackgroundUploadCoordinator(
            ledger: ledger,
            transport: transport
        )
        _ = try coordinator.enqueue(
            captureID: "watch-capture-5",
            meetingID: "meeting-5",
            recordingURL: recordingURL,
            coreURL: try XCTUnwrap(URL(string: "http://pilot.local:8770")),
            advertisedUploadEndpoint: nil,
            deviceID: "pilot-ios-james",
            token: "secret"
        )
        let failed = expectation(description: "upload failed")
        coordinator.onEvent = { event in
            if case .uploadFailed = event { failed.fulfill() }
        }

        transport.complete(
            taskIdentifier: 5,
            statusCode: 503,
            responseData: Data(#"{"detail":"Meeting storage is unavailable."}"#.utf8)
        )
        await fulfillment(of: [failed], timeout: 1)

        let job = try XCTUnwrap(coordinator.job(captureID: "watch-capture-5"))
        XCTAssertEqual(job.state, .failed)
        XCTAssertFalse(job.uploadComplete)
        XCTAssertEqual(job.failureMessage, "Meeting storage is unavailable.")
        XCTAssertTrue(FileManager.default.fileExists(atPath: recordingURL.path))

        let restored = MeetingBackgroundUploadCoordinator(
            ledger: ledger,
            transport: TestMeetingUploadTransport(firstTaskIdentifier: 6)
        )
        XCTAssertEqual(restored.jobs.first?.failureMessage, "Meeting storage is unavailable.")
    }

    @MainActor
    func testMissingBackgroundTaskBecomesRecoverableFailure() async throws {
        let ledger = TestMeetingUploadLedger()
        let transport = TestMeetingUploadTransport(firstTaskIdentifier: 12)
        let recordingURL = try makeRecording()
        defer { try? FileManager.default.removeItem(at: recordingURL) }
        let coordinator = MeetingBackgroundUploadCoordinator(
            ledger: ledger,
            transport: transport
        )
        _ = try coordinator.enqueue(
            captureID: "watch-capture-12",
            meetingID: "meeting-12",
            recordingURL: recordingURL,
            coreURL: try XCTUnwrap(URL(string: "http://pilot.local:8770")),
            advertisedUploadEndpoint: nil,
            deviceID: "pilot-ios-james",
            token: "secret"
        )

        let restored = MeetingBackgroundUploadCoordinator(
            ledger: ledger,
            transport: TestMeetingUploadTransport(firstTaskIdentifier: 13)
        )
        let recovery = try await restored.recover()

        XCTAssertEqual(recovery.failedCaptureIDs, ["watch-capture-12"])
        XCTAssertEqual(recovery.jobs[0].state, .failed)
        XCTAssertTrue(
            recovery.jobs[0].failureMessage?.contains("retry is required") == true
        )
    }

    @MainActor
    func testProcessRequestIsSmallAndAuthenticated() throws {
        let request = MeetingBackgroundUploadCoordinator.processingRequest(
            coreURL: try XCTUnwrap(URL(string: "http://pilot.local:8770")),
            deviceID: "pilot-ios-james",
            token: "device-secret",
            meetingID: "meeting-1"
        )
        XCTAssertEqual(request.httpMethod, "POST")
        XCTAssertEqual(
            request.url?.path,
            "/v1/devices/pilot-ios-james/meetings/meeting-1/process"
        )
        XCTAssertEqual(request.httpBody, Data())
        XCTAssertEqual(
            request.value(forHTTPHeaderField: "Authorization"),
            "Bearer device-secret"
        )
        XCTAssertEqual(
            request.value(forHTTPHeaderField: "X-Pilot-Device-ID"),
            "pilot-ios-james"
        )
    }

    func testBackgroundConfigurationUsesStableIdentifierAndLaunchEvents() {
        let configuration =
            URLSessionMeetingBackgroundUploadTransport.backgroundConfiguration()
        XCTAssertEqual(
            configuration.identifier,
            MeetingBackgroundUploadCoordinator.backgroundSessionIdentifier
        )
        XCTAssertTrue(configuration.sessionSendsLaunchEvents)
        XCTAssertTrue(configuration.waitsForConnectivity)
        XCTAssertFalse(configuration.isDiscretionary)
    }

    private func makeRecording() throws -> URL {
        let url = FileManager.default.temporaryDirectory
            .appending(path: "pilot-meeting-\(UUID().uuidString).m4a")
        try Data("test recording".utf8).write(to: url)
        return url
    }
}

private enum ForegroundTicketBindingMismatch: String, CaseIterable {
    case meetingID
    case filename
    case contentType
    case sha256
    case sizeBytes
}

private actor ForegroundMeetingUploadProbe {
    struct TicketInput: Equatable, Sendable {
        let meetingID: String
        let sha256: String
        let sizeBytes: Int64
        let filename: String
    }

    private(set) var ticketInputs: [TicketInput] = []
    private(set) var uploadRequests: [URLRequest] = []
    private let ticketBindingMismatch: ForegroundTicketBindingMismatch?

    init(ticketBindingMismatch: ForegroundTicketBindingMismatch? = nil) {
        self.ticketBindingMismatch = ticketBindingMismatch
    }

    func issueTicket(
        meetingID: String,
        sha256: String,
        sizeBytes: Int64,
        filename: String
    ) -> MeetingRecordingUploadTicket {
        ticketInputs.append(TicketInput(
            meetingID: meetingID,
            sha256: sha256,
            sizeBytes: sizeBytes,
            filename: filename
        ))
        let mismatch = ticketBindingMismatch
        return MeetingRecordingUploadTicket(
            schemaVersion: "pilot.meeting-recording-upload-ticket.v1",
            ticketID: "foreground-ticket",
            meetingID: mismatch == .meetingID ? "different-meeting" : meetingID,
            uploadURL:
                "https://uploads.pilot.example/v1/meeting-recording-uploads/foreground-ticket",
            uploadToken: "foreground-ticket-secret",
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

    func perform(
        request: URLRequest,
        fileURL: URL
    ) throws -> (Data, URLResponse) {
        uploadRequests.append(request)
        guard fileURL.isFileURL,
              let url = request.url,
              let response = HTTPURLResponse(
                url: url,
                statusCode: 201,
                httpVersion: "HTTP/1.1",
                headerFields: nil
              ) else {
            throw URLError(.badServerResponse)
        }
        return (Data(), response)
    }
}

private final class TestMeetingUploadLedger: MeetingBackgroundUploadLedger,
    @unchecked Sendable
{
    private let lock = NSLock()
    private var storedData: Data?

    var data: Data? {
        lock.lock()
        defer { lock.unlock() }
        return storedData
    }

    func load() throws -> Data? {
        lock.lock()
        defer { lock.unlock() }
        return storedData
    }

    func save(_ data: Data) throws {
        lock.lock()
        defer { lock.unlock() }
        storedData = data
    }
}

private final class TestMeetingUploadTransport: MeetingBackgroundUploadTransport,
    @unchecked Sendable
{
    struct CreatedTask {
        let taskIdentifier: Int
        let request: URLRequest
        let fileURL: URL
        let taskDescription: String
    }

    var eventHandler: (@Sendable (MeetingBackgroundUploadTransportEvent) -> Void)?
    var snapshots: [MeetingBackgroundUploadTaskSnapshot] = []
    var cancellationPollsBeforeDisappearance = 0
    private(set) var createdTasks: [CreatedTask] = []
    private(set) var resumedTaskIdentifiers = Set<Int>()
    private(set) var cancelledTaskIdentifiers = Set<Int>()
    private(set) var outstandingTaskCallCount = 0
    private var pendingCancellationTaskIdentifiers = Set<Int>()
    private var nextTaskIdentifier: Int

    init(firstTaskIdentifier: Int) {
        nextTaskIdentifier = firstTaskIdentifier
    }

    func makeUploadTask(
        request: URLRequest,
        fromFile fileURL: URL,
        taskDescription: String
    ) throws -> Int {
        let identifier = nextTaskIdentifier
        nextTaskIdentifier += 1
        createdTasks.append(
            CreatedTask(
                taskIdentifier: identifier,
                request: request,
                fileURL: fileURL,
                taskDescription: taskDescription
            )
        )
        snapshots.append(
            MeetingBackgroundUploadTaskSnapshot(
                taskIdentifier: identifier,
                taskDescription: taskDescription,
                state: .suspended
            )
        )
        return identifier
    }

    func resume(taskIdentifier: Int) throws {
        resumedTaskIdentifiers.insert(taskIdentifier)
        if let index = snapshots.firstIndex(where: {
            $0.taskIdentifier == taskIdentifier
        }) {
            snapshots[index] = MeetingBackgroundUploadTaskSnapshot(
                taskIdentifier: snapshots[index].taskIdentifier,
                taskDescription: snapshots[index].taskDescription,
                state: .running
            )
        }
    }

    func cancel(taskIdentifier: Int) {
        cancelledTaskIdentifiers.insert(taskIdentifier)
        if cancellationPollsBeforeDisappearance == 0 {
            snapshots.removeAll { $0.taskIdentifier == taskIdentifier }
        } else {
            pendingCancellationTaskIdentifiers.insert(taskIdentifier)
        }
    }

    func outstandingTasks() async -> [MeetingBackgroundUploadTaskSnapshot] {
        outstandingTaskCallCount += 1
        if !pendingCancellationTaskIdentifiers.isEmpty {
            if cancellationPollsBeforeDisappearance > 0 {
                cancellationPollsBeforeDisappearance -= 1
            } else {
                snapshots.removeAll {
                    pendingCancellationTaskIdentifiers.contains($0.taskIdentifier)
                }
                pendingCancellationTaskIdentifiers.removeAll()
            }
        }
        return snapshots
    }

    func complete(
        taskIdentifier: Int,
        statusCode: Int?,
        responseData: Data = Data(),
        errorDescription: String? = nil
    ) {
        let description = snapshots.first {
            $0.taskIdentifier == taskIdentifier
        }?.taskDescription
        snapshots.removeAll { $0.taskIdentifier == taskIdentifier }
        eventHandler?(
            .completed(
                MeetingBackgroundUploadTransportCompletion(
                    taskIdentifier: taskIdentifier,
                    taskDescription: description,
                    statusCode: statusCode,
                    responseData: responseData,
                    errorDescription: errorDescription
                )
            )
        )
    }
}
