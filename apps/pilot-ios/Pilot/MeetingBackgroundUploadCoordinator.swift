import Foundation

struct MeetingBackgroundUploadJob: Codable, Identifiable, Hashable, Sendable {
    enum State: String, Codable, Sendable {
        case queued
        case uploading
        case awaitingProcessing
        case processing
        case completed
        case failed
    }

    var id: String { captureID }

    let captureID: String
    let meetingID: String
    let recordingPath: String
    var state: State
    var uploadComplete: Bool
    var taskIdentifier: Int?
    var attemptCount: Int
    var failureMessage: String?
    var updatedAt: Date

    var recordingURL: URL { URL(fileURLWithPath: recordingPath) }
}

enum MeetingBackgroundUploadEvent: Sendable, Equatable {
    case uploadSucceeded(MeetingBackgroundUploadJob)
    case uploadFailed(MeetingBackgroundUploadJob)
    case processingRequired(MeetingBackgroundUploadJob)
    case processingFailed(MeetingBackgroundUploadJob)
    case completed(MeetingBackgroundUploadJob)
    case backgroundSessionEventsFinished
}

struct MeetingBackgroundUploadRecovery: Sendable, Equatable {
    let jobs: [MeetingBackgroundUploadJob]
    let processingRequiredCaptureIDs: [String]
    let failedCaptureIDs: [String]
    let orphanedTaskIdentifiers: [Int]
}

enum MeetingBackgroundUploadError: LocalizedError, Equatable {
    case duplicateCapture(String)
    case invalidAdvertisedEndpoint
    case invalidUploadTicket
    case invalidRecordingFile
    case jobNotFound(String)
    case invalidTransition(String)
    case orphanedTransfersStillActive([Int])
    case transferUnavailable

    var errorDescription: String? {
        switch self {
        case let .duplicateCapture(captureID):
            "Capture \(captureID) already has a durable upload job."
        case .invalidAdvertisedEndpoint:
            "Pilot Core advertised an invalid meeting upload endpoint."
        case .invalidUploadTicket:
            "Pilot Core returned an invalid or expired meeting upload ticket."
        case .invalidRecordingFile:
            "The retained meeting recording file is unavailable."
        case let .jobNotFound(captureID):
            "No durable upload job exists for capture \(captureID)."
        case let .invalidTransition(detail):
            detail
        case let .orphanedTransfersStillActive(taskIdentifiers):
            "Unowned background meeting uploads are still cancelling: \(taskIdentifiers)."
        case .transferUnavailable:
            "The background transfer is no longer available."
        }
    }
}

protocol MeetingBackgroundUploadLedger: Sendable {
    func load() throws -> Data?
    func save(_ data: Data) throws
}

struct FileMeetingBackgroundUploadLedger: MeetingBackgroundUploadLedger {
    let fileURL: URL

    init(fileURL: URL = Self.defaultFileURL()) {
        self.fileURL = fileURL
    }

    func load() throws -> Data? {
        guard FileManager.default.fileExists(atPath: fileURL.path) else { return nil }
        return try Data(contentsOf: fileURL)
    }

    func save(_ data: Data) throws {
        let directory = fileURL.deletingLastPathComponent()
        try FileManager.default.createDirectory(
            at: directory,
            withIntermediateDirectories: true
        )
        try data.write(
            to: fileURL,
            options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication]
        )
    }

    private static func defaultFileURL() -> URL {
        let base = FileManager.default.urls(
            for: .applicationSupportDirectory,
            in: .userDomainMask
        )[0]
        return base
            .appending(path: "Pilot", directoryHint: .isDirectory)
            .appending(path: "meeting-background-uploads-v1.json")
    }
}

struct MeetingBackgroundUploadTaskSnapshot: Sendable, Equatable {
    enum State: Sendable, Equatable {
        case running
        case suspended
        case canceling
        case completed
        case unknown
    }

    let taskIdentifier: Int
    let taskDescription: String?
    let state: State

    init(
        taskIdentifier: Int,
        taskDescription: String?,
        state: State = .running
    ) {
        self.taskIdentifier = taskIdentifier
        self.taskDescription = taskDescription
        self.state = state
    }
}

struct MeetingBackgroundUploadTransportCompletion: Sendable, Equatable {
    let taskIdentifier: Int
    let taskDescription: String?
    let statusCode: Int?
    let responseData: Data
    let errorDescription: String?
}

enum MeetingBackgroundUploadTransportEvent: Sendable, Equatable {
    case completed(MeetingBackgroundUploadTransportCompletion)
    case backgroundEventsFinished
}

protocol MeetingBackgroundUploadTransport: AnyObject, Sendable {
    var eventHandler: (@Sendable (MeetingBackgroundUploadTransportEvent) -> Void)? { get set }

    func makeUploadTask(
        request: URLRequest,
        fromFile fileURL: URL,
        taskDescription: String
    ) throws -> Int
    func resume(taskIdentifier: Int) throws
    func cancel(taskIdentifier: Int)
    func outstandingTasks() async -> [MeetingBackgroundUploadTaskSnapshot]
}

final class URLSessionMeetingBackgroundUploadTransport: NSObject,
    MeetingBackgroundUploadTransport,
    URLSessionDataDelegate,
    URLSessionTaskDelegate,
    @unchecked Sendable
{
    static let sessionIdentifier = "com.jameshazell.pilot.meeting-recording-upload.v1"

    var eventHandler: (@Sendable (MeetingBackgroundUploadTransportEvent) -> Void)? {
        get { locked { _eventHandler } }
        set { locked { _eventHandler = newValue } }
    }

    private let lock = NSLock()
    private var _eventHandler: (@Sendable (MeetingBackgroundUploadTransportEvent) -> Void)?
    private var tasks: [Int: URLSessionTask] = [:]
    private var responseBodies: [Int: Data] = [:]

    private lazy var session: URLSession = {
        let configuration = Self.backgroundConfiguration()
        return URLSession(
            configuration: configuration,
            delegate: self,
            delegateQueue: nil
        )
    }()

    static func backgroundConfiguration() -> URLSessionConfiguration {
        let configuration = URLSessionConfiguration.background(
            withIdentifier: sessionIdentifier
        )
        configuration.sessionSendsLaunchEvents = true
        configuration.isDiscretionary = false
        configuration.waitsForConnectivity = true
        configuration.allowsCellularAccess = true
        configuration.timeoutIntervalForRequest = 600
        return configuration
    }

    func makeUploadTask(
        request: URLRequest,
        fromFile fileURL: URL,
        taskDescription: String
    ) throws -> Int {
        guard fileURL.isFileURL else {
            throw MeetingBackgroundUploadError.invalidRecordingFile
        }
        let task = session.uploadTask(with: request, fromFile: fileURL)
        task.taskDescription = taskDescription
        locked { tasks[task.taskIdentifier] = task }
        return task.taskIdentifier
    }

    func resume(taskIdentifier: Int) throws {
        guard let task = locked({ tasks[taskIdentifier] }) else {
            throw MeetingBackgroundUploadError.transferUnavailable
        }
        task.resume()
    }

    func cancel(taskIdentifier: Int) {
        locked { tasks[taskIdentifier] }?.cancel()
    }

    func outstandingTasks() async -> [MeetingBackgroundUploadTaskSnapshot] {
        await withCheckedContinuation { continuation in
            session.getAllTasks { tasks in
                let snapshots = tasks.map {
                    MeetingBackgroundUploadTaskSnapshot(
                        taskIdentifier: $0.taskIdentifier,
                        taskDescription: $0.taskDescription,
                        state: Self.snapshotState($0.state)
                    )
                }
                self.locked {
                    for task in tasks {
                        self.tasks[task.taskIdentifier] = task
                    }
                }
                continuation.resume(returning: snapshots)
            }
        }
    }

    func urlSession(
        _ session: URLSession,
        dataTask: URLSessionDataTask,
        didReceive data: Data
    ) {
        locked {
            var body = responseBodies[dataTask.taskIdentifier, default: Data()]
            // Meeting upload responses are small JSON envelopes. Bound retained
            // response data so a bad endpoint cannot grow app memory without limit.
            if body.count < 65_536 {
                body.append(data.prefix(65_536 - body.count))
            }
            responseBodies[dataTask.taskIdentifier] = body
        }
    }

    func urlSession(
        _ session: URLSession,
        task: URLSessionTask,
        didCompleteWithError error: Error?
    ) {
        let handler: (@Sendable (MeetingBackgroundUploadTransportEvent) -> Void)?
        let body: Data
        (handler, body) = locked {
            tasks.removeValue(forKey: task.taskIdentifier)
            let body = responseBodies.removeValue(forKey: task.taskIdentifier) ?? Data()
            return (_eventHandler, body)
        }
        handler?(
            .completed(
                MeetingBackgroundUploadTransportCompletion(
                    taskIdentifier: task.taskIdentifier,
                    taskDescription: task.taskDescription,
                    statusCode: (task.response as? HTTPURLResponse)?.statusCode,
                    responseData: body,
                    errorDescription: error?.localizedDescription
                )
            )
        )
    }

    func urlSessionDidFinishEvents(forBackgroundURLSession session: URLSession) {
        locked { _eventHandler }?(.backgroundEventsFinished)
    }

    private func locked<T>(_ body: () -> T) -> T {
        lock.lock()
        defer { lock.unlock() }
        return body()
    }

    private static func snapshotState(
        _ state: URLSessionTask.State
    ) -> MeetingBackgroundUploadTaskSnapshot.State {
        switch state {
        case .running: .running
        case .suspended: .suspended
        case .canceling: .canceling
        case .completed: .completed
        @unknown default: .unknown
        }
    }
}

@MainActor
final class MeetingBackgroundUploadCoordinator {
    nonisolated static let backgroundSessionIdentifier =
        URLSessionMeetingBackgroundUploadTransport.sessionIdentifier

    var onEvent: ((MeetingBackgroundUploadEvent) -> Void)?
    private(set) var jobs: [MeetingBackgroundUploadJob]

    private let ledger: any MeetingBackgroundUploadLedger
    private let transport: any MeetingBackgroundUploadTransport
    private let now: @Sendable () -> Date

    init(
        ledger: any MeetingBackgroundUploadLedger = FileMeetingBackgroundUploadLedger(),
        transport: any MeetingBackgroundUploadTransport =
            URLSessionMeetingBackgroundUploadTransport(),
        now: @escaping @Sendable () -> Date = Date.init
    ) {
        self.ledger = ledger
        self.transport = transport
        self.now = now
        self.jobs = Self.restoreJobs(from: ledger)
        transport.eventHandler = { [weak self] event in
            Task { @MainActor in
                self?.handle(event)
            }
        }
    }

    deinit {
        transport.eventHandler = nil
    }

    @discardableResult
    func enqueue(
        captureID: String,
        meetingID: String,
        recordingURL: URL,
        coreURL: URL,
        advertisedUploadEndpoint: String?,
        uploadTicket: MeetingRecordingUploadTicket? = nil,
        deviceID: String,
        token: String
    ) throws -> MeetingBackgroundUploadJob {
        guard jobs.first(where: { $0.captureID == captureID }) == nil else {
            throw MeetingBackgroundUploadError.duplicateCapture(captureID)
        }
        return try scheduleUpload(
            captureID: captureID,
            meetingID: meetingID,
            recordingURL: recordingURL,
            coreURL: coreURL,
            advertisedUploadEndpoint: advertisedUploadEndpoint,
            uploadTicket: uploadTicket,
            deviceID: deviceID,
            token: token,
            attemptCount: 1
        )
    }

    @discardableResult
    func retryUpload(
        captureID: String,
        coreURL: URL,
        advertisedUploadEndpoint: String?,
        uploadTicket: MeetingRecordingUploadTicket? = nil,
        deviceID: String,
        token: String
    ) throws -> MeetingBackgroundUploadJob {
        guard let index = jobs.firstIndex(where: { $0.captureID == captureID }) else {
            throw MeetingBackgroundUploadError.jobNotFound(captureID)
        }
        let existing = jobs[index]
        if existing.uploadComplete {
            if existing.state == .completed { return existing }
            jobs[index].state = .awaitingProcessing
            jobs[index].failureMessage = nil
            jobs[index].updatedAt = now()
            try persist()
            onEvent?(.processingRequired(jobs[index]))
            return jobs[index]
        }
        if let taskIdentifier = existing.taskIdentifier {
            transport.cancel(taskIdentifier: taskIdentifier)
        }
        jobs.remove(at: index)
        do {
            return try scheduleUpload(
                captureID: existing.captureID,
                meetingID: existing.meetingID,
                recordingURL: existing.recordingURL,
                coreURL: coreURL,
                advertisedUploadEndpoint: advertisedUploadEndpoint,
                uploadTicket: uploadTicket,
                deviceID: deviceID,
                token: token,
                attemptCount: existing.attemptCount + 1
            )
        } catch {
            if !jobs.contains(where: { $0.captureID == captureID }) {
                var failed = existing
                failed.state = .failed
                failed.taskIdentifier = nil
                failed.attemptCount += 1
                failed.failureMessage = error.localizedDescription
                failed.updatedAt = now()
                jobs.insert(failed, at: min(index, jobs.endIndex))
            }
            try? persist()
            throw error
        }
    }

    func recover() async throws -> MeetingBackgroundUploadRecovery {
        let activeTasks = await transport.outstandingTasks()
        let activeByIdentifier = Dictionary(
            uniqueKeysWithValues: activeTasks.map { ($0.taskIdentifier, $0) }
        )
        var claimedTaskIdentifiers = Set<Int>()
        var changed = false
        var events: [MeetingBackgroundUploadEvent] = []

        for index in jobs.indices {
            if jobs[index].uploadComplete {
                if jobs[index].state == .processing {
                    // A foreground /process call was interrupted. The Core endpoint
                    // is queue-oriented, so surface it for a safe retry.
                    jobs[index].state = .awaitingProcessing
                    jobs[index].failureMessage = nil
                    jobs[index].updatedAt = now()
                    changed = true
                }
                if jobs[index].state == .awaitingProcessing {
                    events.append(.processingRequired(jobs[index]))
                }
                continue
            }

            let direct = jobs[index].taskIdentifier
                .flatMap { activeByIdentifier[$0] }
                .flatMap { task -> MeetingBackgroundUploadTaskSnapshot? in
                    guard let identity = Self.taskIdentity(from: task.taskDescription) else {
                        return task
                    }
                    return identity.captureID == jobs[index].captureID
                        && identity.meetingID == jobs[index].meetingID
                        ? task
                        : nil
                }
            let described = activeTasks.first { task in
                guard let identity = Self.taskIdentity(from: task.taskDescription) else {
                    return false
                }
                return identity.captureID == jobs[index].captureID
                    && identity.meetingID == jobs[index].meetingID
            }
            if let active = direct ?? described {
                claimedTaskIdentifiers.insert(active.taskIdentifier)
                if active.state == .canceling
                    || active.state == .completed
                    || active.state == .unknown
                {
                    jobs[index].taskIdentifier = nil
                    jobs[index].state = .failed
                    jobs[index].failureMessage =
                        "The restored background transfer cannot continue; retry is required."
                    jobs[index].updatedAt = now()
                    changed = true
                    events.append(.uploadFailed(jobs[index]))
                } else {
                    if active.state == .suspended {
                        do {
                            try transport.resume(taskIdentifier: active.taskIdentifier)
                        } catch {
                            jobs[index].taskIdentifier = nil
                            jobs[index].state = .failed
                            jobs[index].failureMessage = error.localizedDescription
                            jobs[index].updatedAt = now()
                            changed = true
                            events.append(.uploadFailed(jobs[index]))
                            continue
                        }
                    }
                    if jobs[index].taskIdentifier != active.taskIdentifier
                        || jobs[index].state != .uploading
                    {
                        jobs[index].taskIdentifier = active.taskIdentifier
                        jobs[index].state = .uploading
                        jobs[index].failureMessage = nil
                        jobs[index].updatedAt = now()
                        changed = true
                    }
                }
            } else if jobs[index].state == .queued || jobs[index].state == .uploading {
                jobs[index].state = .failed
                jobs[index].taskIdentifier = nil
                jobs[index].failureMessage =
                    "The background transfer is no longer registered; retry is required."
                jobs[index].updatedAt = now()
                changed = true
                events.append(.uploadFailed(jobs[index]))
            }
        }

        if changed { try persist() }
        events.forEach { onEvent?($0) }

        // Any system task not claimed by the durable ledger is unsafe to let
        // race a newly-created upload. This includes a recognizable Pilot task
        // whose ledger was lost or corrupt. Cancel it and wait until URLSession
        // no longer reports it before recovery may succeed.
        let orphanedTaskIdentifiers = activeTasks
            .map(\.taskIdentifier)
            .filter { !claimedTaskIdentifiers.contains($0) }
            .sorted()
        if !orphanedTaskIdentifiers.isEmpty {
            orphanedTaskIdentifiers.forEach {
                transport.cancel(taskIdentifier: $0)
            }
            try await awaitOrphanCancellation(
                taskIdentifiers: Set(orphanedTaskIdentifiers)
            )
        }

        let orderedJobs = jobs.sorted { $0.updatedAt > $1.updatedAt }
        return MeetingBackgroundUploadRecovery(
            jobs: orderedJobs,
            processingRequiredCaptureIDs: orderedJobs
                .filter { $0.state == .awaitingProcessing }
                .map(\.captureID),
            failedCaptureIDs: orderedJobs
                .filter { $0.state == .failed }
                .map(\.captureID),
            orphanedTaskIdentifiers: orphanedTaskIdentifiers
        )
    }

    private func awaitOrphanCancellation(
        taskIdentifiers: Set<Int>
    ) async throws {
        let clock = ContinuousClock()
        let deadline = clock.now.advanced(by: .seconds(2))
        while true {
            let outstanding = await transport.outstandingTasks()
            let remaining = outstanding
                .map(\.taskIdentifier)
                .filter(taskIdentifiers.contains)
                .sorted()
            if remaining.isEmpty { return }
            guard clock.now < deadline else {
                throw MeetingBackgroundUploadError.orphanedTransfersStillActive(
                    remaining
                )
            }
            try await Task.sleep(for: .milliseconds(50))
        }
    }

    func markProcessingStarted(captureID: String) throws {
        let index = try indexForJob(captureID)
        guard jobs[index].uploadComplete,
              jobs[index].state == .awaitingProcessing
                || jobs[index].state == .failed
        else {
            throw MeetingBackgroundUploadError.invalidTransition(
                "The meeting recording must finish uploading before processing starts."
            )
        }
        jobs[index].state = .processing
        jobs[index].failureMessage = nil
        jobs[index].updatedAt = now()
        try persist()
    }

    @discardableResult
    func markUploadReconciled(captureID: String) throws -> MeetingBackgroundUploadJob {
        let index = try indexForJob(captureID)
        guard !jobs[index].uploadComplete,
              jobs[index].state == .failed,
              jobs[index].taskIdentifier == nil else {
            throw MeetingBackgroundUploadError.invalidTransition(
                "Only a failed meeting upload can be reconciled from Core state."
            )
        }
        jobs[index].uploadComplete = true
        jobs[index].state = .awaitingProcessing
        jobs[index].failureMessage = nil
        jobs[index].updatedAt = now()
        try persist()
        let job = jobs[index]
        onEvent?(.uploadSucceeded(job))
        onEvent?(.processingRequired(job))
        return job
    }

    func markProcessingFailed(captureID: String, message: String) throws {
        let index = try indexForJob(captureID)
        guard jobs[index].uploadComplete, jobs[index].state == .processing else {
            throw MeetingBackgroundUploadError.invalidTransition(
                "A processing failure cannot be recorded before upload completes."
            )
        }
        jobs[index].state = .failed
        jobs[index].failureMessage = message
        jobs[index].updatedAt = now()
        try persist()
        onEvent?(.processingFailed(jobs[index]))
    }

    func markProcessingCompleted(captureID: String) throws {
        let index = try indexForJob(captureID)
        guard jobs[index].uploadComplete, jobs[index].state == .processing else {
            throw MeetingBackgroundUploadError.invalidTransition(
                "The meeting recording must finish uploading before processing completes."
            )
        }
        jobs[index].state = .completed
        jobs[index].failureMessage = nil
        jobs[index].updatedAt = now()
        try persist()
        onEvent?(.completed(jobs[index]))
    }

    func removeCompleted(captureID: String) throws {
        let index = try indexForJob(captureID)
        guard jobs[index].state == .completed else {
            throw MeetingBackgroundUploadError.invalidTransition(
                "Only completed meeting upload jobs can be removed."
            )
        }
        jobs.remove(at: index)
        try persist()
    }

    func job(captureID: String) -> MeetingBackgroundUploadJob? {
        jobs.first { $0.captureID == captureID }
    }

    nonisolated static func uploadRequest(
        coreURL: URL,
        deviceID: String,
        token: String,
        meetingID: String,
        recordingURL: URL,
        advertisedUploadEndpoint: String?,
        uploadTicket: MeetingRecordingUploadTicket? = nil
    ) throws -> URLRequest {
        let url: URL
        if let uploadTicket {
            url = try resolvedTicketUploadURL(
                uploadTicket,
                coreURL: coreURL,
                meetingID: meetingID
            )
        } else {
            url = try resolvedUploadURL(
                coreURL: coreURL,
                deviceID: deviceID,
                meetingID: meetingID,
                advertisedUploadEndpoint: advertisedUploadEndpoint
            )
        }
        var request = URLRequest(url: url)
        request.httpMethod = "PUT"
        request.timeoutInterval = 600
        request.setValue(
            "Bearer \(uploadTicket?.uploadToken ?? token)",
            forHTTPHeaderField: "Authorization"
        )
        if uploadTicket == nil {
            request.setValue(deviceID, forHTTPHeaderField: "X-Pilot-Device-ID")
        }
        // The ticket is already bound to Core's expected filename. Omitting the
        // legacy filename header prevents a retained local basename from
        // conflicting with that binding.
        if uploadTicket == nil {
            request.setValue(
                recordingURL.lastPathComponent,
                forHTTPHeaderField: "X-Pilot-Filename"
            )
        }
        request.setValue("audio/m4a", forHTTPHeaderField: "Content-Type")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        return request
    }

    static func processingRequest(
        coreURL: URL,
        deviceID: String,
        token: String,
        meetingID: String
    ) -> URLRequest {
        let url = coreURL.appending(
            path: "v1/devices/\(deviceID)/meetings/\(meetingID)/process"
        )
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.timeoutInterval = 60
        request.httpBody = Data()
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.setValue(deviceID, forHTTPHeaderField: "X-Pilot-Device-ID")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        return request
    }

    private struct LedgerEnvelope: Codable, Sendable {
        let schemaVersion: Int
        var jobs: [MeetingBackgroundUploadJob]
    }

    private struct TaskIdentity: Codable, Sendable, Equatable {
        let captureID: String
        let meetingID: String
    }

    private static let taskDescriptionPrefix = "pilot-meeting-upload-v1:"

    private func scheduleUpload(
        captureID: String,
        meetingID: String,
        recordingURL: URL,
        coreURL: URL,
        advertisedUploadEndpoint: String?,
        uploadTicket: MeetingRecordingUploadTicket?,
        deviceID: String,
        token: String,
        attemptCount: Int
    ) throws -> MeetingBackgroundUploadJob {
        guard recordingURL.isFileURL,
              FileManager.default.fileExists(atPath: recordingURL.path)
        else { throw MeetingBackgroundUploadError.invalidRecordingFile }

        let request = try Self.uploadRequest(
            coreURL: coreURL,
            deviceID: deviceID,
            token: token,
            meetingID: meetingID,
            recordingURL: recordingURL,
            advertisedUploadEndpoint: advertisedUploadEndpoint,
            uploadTicket: uploadTicket
        )
        var job = MeetingBackgroundUploadJob(
            captureID: captureID,
            meetingID: meetingID,
            recordingPath: recordingURL.path,
            state: .queued,
            uploadComplete: false,
            taskIdentifier: nil,
            attemptCount: attemptCount,
            failureMessage: nil,
            updatedAt: now()
        )
        jobs.append(job)
        do {
            try persist()
        } catch {
            jobs.removeAll { $0.captureID == captureID }
            throw error
        }

        var createdTaskIdentifier: Int?
        do {
            let taskIdentifier = try transport.makeUploadTask(
                request: request,
                fromFile: recordingURL,
                taskDescription: Self.taskDescription(
                    captureID: captureID,
                    meetingID: meetingID
                )
            )
            createdTaskIdentifier = taskIdentifier
            job.taskIdentifier = taskIdentifier
            job.state = .uploading
            job.updatedAt = now()
            replace(job)
            do {
                // Persist the task mapping before resume. If the app is killed as
                // soon as the transfer starts, relaunch can still recover it.
                try persist()
            } catch {
                transport.cancel(taskIdentifier: taskIdentifier)
                throw error
            }
            try transport.resume(taskIdentifier: taskIdentifier)
            return job
        } catch {
            if let createdTaskIdentifier {
                transport.cancel(taskIdentifier: createdTaskIdentifier)
            }
            if let index = jobs.firstIndex(where: { $0.captureID == captureID }) {
                jobs[index].state = .failed
                jobs[index].taskIdentifier = nil
                jobs[index].failureMessage = error.localizedDescription
                jobs[index].updatedAt = now()
                try? persist()
            }
            throw error
        }
    }

    private func handle(_ event: MeetingBackgroundUploadTransportEvent) {
        switch event {
        case .backgroundEventsFinished:
            onEvent?(.backgroundSessionEventsFinished)
        case let .completed(completion):
            handleCompletion(completion)
        }
    }

    private func handleCompletion(_ completion: MeetingBackgroundUploadTransportCompletion) {
        guard let index = indexForCompletion(completion) else { return }
        jobs[index].taskIdentifier = nil
        jobs[index].updatedAt = now()

        if let failure = Self.failureMessage(for: completion) {
            jobs[index].state = .failed
            jobs[index].failureMessage = failure
            try? persist()
            onEvent?(.uploadFailed(jobs[index]))
            return
        }

        jobs[index].uploadComplete = true
        jobs[index].state = .awaitingProcessing
        jobs[index].failureMessage = nil
        try? persist()
        let job = jobs[index]
        onEvent?(.uploadSucceeded(job))
        onEvent?(.processingRequired(job))
    }

    private func indexForCompletion(
        _ completion: MeetingBackgroundUploadTransportCompletion
    ) -> Int? {
        if let direct = jobs.firstIndex(where: {
            $0.taskIdentifier == completion.taskIdentifier
        }) {
            return direct
        }
        guard let identity = Self.taskIdentity(from: completion.taskDescription) else {
            return nil
        }
        return jobs.firstIndex {
            $0.captureID == identity.captureID
                && $0.meetingID == identity.meetingID
                && ($0.taskIdentifier == nil
                    || $0.taskIdentifier == completion.taskIdentifier)
        }
    }

    private func indexForJob(_ captureID: String) throws -> Int {
        guard let index = jobs.firstIndex(where: { $0.captureID == captureID }) else {
            throw MeetingBackgroundUploadError.jobNotFound(captureID)
        }
        return index
    }

    private func replace(_ job: MeetingBackgroundUploadJob) {
        guard let index = jobs.firstIndex(where: { $0.captureID == job.captureID }) else {
            return
        }
        jobs[index] = job
    }

    private func persist() throws {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        encoder.outputFormatting = [.sortedKeys]
        try ledger.save(
            encoder.encode(LedgerEnvelope(schemaVersion: 1, jobs: jobs))
        )
    }

    private static func restoreJobs(
        from ledger: any MeetingBackgroundUploadLedger
    ) -> [MeetingBackgroundUploadJob] {
        guard let data = try? ledger.load() else { return [] }
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        guard let envelope = try? decoder.decode(LedgerEnvelope.self, from: data),
              envelope.schemaVersion == 1
        else { return [] }
        return envelope.jobs
    }

    nonisolated private static func resolvedUploadURL(
        coreURL: URL,
        deviceID: String,
        meetingID: String,
        advertisedUploadEndpoint: String?
    ) throws -> URL {
        if let advertisedUploadEndpoint, !advertisedUploadEndpoint.isEmpty {
            let resolved = advertisedUploadEndpoint.replacingOccurrences(
                of: "{meeting_id}",
                with: meetingID
            )
            guard let advertisedURL = URL(string: resolved) else {
                throw MeetingBackgroundUploadError.invalidAdvertisedEndpoint
            }
            // A permanent device bearer never crosses the paired Core origin.
            // Off-origin upload URLs require a short-lived scoped ticket.
            if advertisedURL.scheme != nil,
               !sameOrigin(advertisedURL, coreURL) {
                throw MeetingBackgroundUploadError.invalidAdvertisedEndpoint
            }
            return advertisedURL.scheme == nil
                ? coreURL.appending(path: resolved)
                : advertisedURL
        }
        return coreURL.appending(
            path: "v1/devices/\(deviceID)/meetings/\(meetingID)/recording"
        )
    }

    nonisolated private static func resolvedTicketUploadURL(
        _ ticket: MeetingRecordingUploadTicket,
        coreURL: URL,
        meetingID: String
    ) throws -> URL {
        guard ticket.schemaVersion == "pilot.meeting-recording-upload-ticket.v1",
              ticket.meetingID == meetingID,
              !ticket.ticketID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              !ticket.recording.filename.isEmpty,
              normalizedContentType(ticket.recording.contentType) == "audio/m4a",
              !ticket.uploadToken.isEmpty,
              let expiresAt = iso8601Date(ticket.expiresAt),
              expiresAt > Date(),
              let candidate = URL(string: ticket.uploadURL, relativeTo: coreURL)?.absoluteURL,
              candidate.user == nil,
              candidate.password == nil,
              (candidate.scheme?.lowercased() == "https"
                || sameOrigin(candidate, coreURL))
        else { throw MeetingBackgroundUploadError.invalidUploadTicket }
        return candidate
    }

    nonisolated static func advertisedEndpointIsOffOrigin(
        _ endpoint: String?,
        coreURL: URL
    ) -> Bool {
        guard let endpoint, !endpoint.isEmpty,
              let url = URL(string: endpoint.replacingOccurrences(
                of: "{meeting_id}",
                with: "meeting-id"
              )),
              url.scheme != nil else { return false }
        return !sameOrigin(url, coreURL)
    }

    nonisolated private static func iso8601Date(_ value: String) -> Date? {
        let fractional = ISO8601DateFormatter()
        fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = fractional.date(from: value) { return date }
        return ISO8601DateFormatter().date(from: value)
    }

    nonisolated private static func normalizedContentType(_ value: String) -> String {
        String(value.split(separator: ";", maxSplits: 1).first ?? "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
    }

    nonisolated private static func sameOrigin(_ lhs: URL, _ rhs: URL) -> Bool {
        lhs.scheme?.lowercased() == rhs.scheme?.lowercased()
            && lhs.host?.lowercased() == rhs.host?.lowercased()
            && effectivePort(lhs) == effectivePort(rhs)
    }

    nonisolated private static func effectivePort(_ url: URL) -> Int? {
        if let port = url.port { return port }
        return switch url.scheme?.lowercased() {
        case "http": 80
        case "https": 443
        default: nil
        }
    }

    private static func taskDescription(captureID: String, meetingID: String) -> String {
        let identity = TaskIdentity(captureID: captureID, meetingID: meetingID)
        let data = (try? JSONEncoder().encode(identity)) ?? Data()
        let encoded = data.base64EncodedString()
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
        return taskDescriptionPrefix + encoded
    }

    private static func taskIdentity(from description: String?) -> TaskIdentity? {
        guard let description,
              description.hasPrefix(taskDescriptionPrefix)
        else { return nil }
        var encoded = String(description.dropFirst(taskDescriptionPrefix.count))
            .replacingOccurrences(of: "-", with: "+")
            .replacingOccurrences(of: "_", with: "/")
        let remainder = encoded.count % 4
        if remainder != 0 {
            encoded.append(String(repeating: "=", count: 4 - remainder))
        }
        guard let data = Data(base64Encoded: encoded) else { return nil }
        return try? JSONDecoder().decode(TaskIdentity.self, from: data)
    }

    private static func failureMessage(
        for completion: MeetingBackgroundUploadTransportCompletion
    ) -> String? {
        if let errorDescription = completion.errorDescription {
            return errorDescription
        }
        guard let statusCode = completion.statusCode else {
            return "Pilot Core returned an invalid upload response."
        }
        guard !(200..<300).contains(statusCode) else { return nil }
        let detail = (try? JSONSerialization.jsonObject(
            with: completion.responseData
        ) as? [String: Any])?["detail"] as? String
        if statusCode == 401 || statusCode == 403 {
            return detail ?? "This Pilot device credential was rejected."
        }
        return detail ?? "Pilot Core returned HTTP \(statusCode)."
    }
}
