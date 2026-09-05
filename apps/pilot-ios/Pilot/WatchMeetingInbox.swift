import CryptoKit
import Foundation

#if canImport(WatchConnectivity) && os(iOS)
import WatchConnectivity
#endif

enum WatchMeetingTransferContract {
    static let transferSchema = "pilot.watch.meeting.transfer.v1"
    static let acknowledgementSchema = "pilot.watch.meeting.ack.v1"

    enum Key {
        static let schemaVersion = "schema_version"
        static let captureID = "capture_id"
        static let title = "title"
        static let startedAt = "started_at"
        static let durationSeconds = "duration_seconds"
        static let sha256 = "sha256"
        static let sizeBytes = "size_bytes"
        static let originalFilename = "original_filename"
        static let state = "state"
        static let acknowledgedAt = "acknowledged_at"
        static let coreMeetingID = "core_meeting_id"
        static let message = "message"
        static let retryable = "retryable"
    }
}

struct WatchMeetingTransferMetadata: Codable, Hashable, Sendable {
    let captureID: UUID
    let title: String
    let startedAt: Date
    let durationSeconds: TimeInterval
    let sha256: String
    let sizeBytes: Int64
    let originalFilename: String

    init(
        captureID: UUID,
        title: String,
        startedAt: Date,
        durationSeconds: TimeInterval,
        sha256: String,
        sizeBytes: Int64,
        originalFilename: String = "recording.m4a"
    ) throws {
        let normalizedTitle = title.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !normalizedTitle.isEmpty, normalizedTitle.count <= 200 else {
            throw WatchMeetingInboxError.invalidMetadata("title")
        }
        guard startedAt.timeIntervalSince1970.isFinite else {
            throw WatchMeetingInboxError.invalidMetadata("started_at")
        }
        guard durationSeconds.isFinite,
              durationSeconds > 0,
              durationSeconds <= 24 * 60 * 60 else {
            throw WatchMeetingInboxError.invalidMetadata("duration_seconds")
        }
        let normalizedHash = sha256.lowercased()
        let hexCharacters = CharacterSet(charactersIn: "0123456789abcdef")
        guard normalizedHash.utf8.count == 64,
              normalizedHash.unicodeScalars.allSatisfy(hexCharacters.contains) else {
            throw WatchMeetingInboxError.invalidMetadata("sha256")
        }
        guard sizeBytes > 0, sizeBytes <= 10 * 1_024 * 1_024 * 1_024 else {
            throw WatchMeetingInboxError.invalidMetadata("size_bytes")
        }
        let filename = originalFilename.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !filename.isEmpty,
              filename.count <= 255,
              URL(fileURLWithPath: filename).lastPathComponent == filename,
              !filename.contains("/") else {
            throw WatchMeetingInboxError.invalidMetadata("original_filename")
        }

        self.captureID = captureID
        self.title = normalizedTitle
        self.startedAt = startedAt
        self.durationSeconds = durationSeconds
        self.sha256 = normalizedHash
        self.sizeBytes = sizeBytes
        self.originalFilename = filename
    }

    init(propertyList: [String: Any]) throws {
        guard propertyList[WatchMeetingTransferContract.Key.schemaVersion] as? String
                == WatchMeetingTransferContract.transferSchema else {
            throw WatchMeetingInboxError.invalidMetadata("schema_version")
        }
        guard let captureIDString = propertyList[WatchMeetingTransferContract.Key.captureID] as? String,
              let captureID = UUID(uuidString: captureIDString) else {
            throw WatchMeetingInboxError.invalidMetadata("capture_id")
        }
        guard let title = propertyList[WatchMeetingTransferContract.Key.title] as? String else {
            throw WatchMeetingInboxError.invalidMetadata("title")
        }
        guard let startedAtString = propertyList[WatchMeetingTransferContract.Key.startedAt] as? String,
              let startedAt = WatchMeetingISO8601.date(from: startedAtString) else {
            throw WatchMeetingInboxError.invalidMetadata("started_at")
        }
        guard let duration = Self.finiteDouble(
            propertyList[WatchMeetingTransferContract.Key.durationSeconds]
        ) else {
            throw WatchMeetingInboxError.invalidMetadata("duration_seconds")
        }
        guard let hash = propertyList[WatchMeetingTransferContract.Key.sha256] as? String else {
            throw WatchMeetingInboxError.invalidMetadata("sha256")
        }
        guard let size = Self.exactInt64(propertyList[WatchMeetingTransferContract.Key.sizeBytes]) else {
            throw WatchMeetingInboxError.invalidMetadata("size_bytes")
        }
        let filename = propertyList[WatchMeetingTransferContract.Key.originalFilename] as? String
            ?? "recording.m4a"
        try self.init(
            captureID: captureID,
            title: title,
            startedAt: startedAt,
            durationSeconds: duration,
            sha256: hash,
            sizeBytes: size,
            originalFilename: filename
        )
    }

    var propertyList: [String: Any] {
        [
            WatchMeetingTransferContract.Key.schemaVersion: WatchMeetingTransferContract.transferSchema,
            WatchMeetingTransferContract.Key.captureID: captureID.uuidString.lowercased(),
            WatchMeetingTransferContract.Key.title: title,
            WatchMeetingTransferContract.Key.startedAt: WatchMeetingISO8601.string(from: startedAt),
            WatchMeetingTransferContract.Key.durationSeconds: durationSeconds,
            WatchMeetingTransferContract.Key.sha256: sha256,
            WatchMeetingTransferContract.Key.sizeBytes: sizeBytes,
            WatchMeetingTransferContract.Key.originalFilename: originalFilename,
        ]
    }

    private static func finiteDouble(_ value: Any?) -> Double? {
        guard let number = value as? NSNumber, !Self.isBoolean(number) else { return nil }
        let result = number.doubleValue
        return result.isFinite ? result : nil
    }

    private static func exactInt64(_ value: Any?) -> Int64? {
        guard let number = value as? NSNumber, !Self.isBoolean(number) else { return nil }
        let double = number.doubleValue
        guard double.isFinite,
              double.rounded(.towardZero) == double,
              double >= Double(Int64.min),
              double <= Double(Int64.max) else { return nil }
        return number.int64Value
    }

    private static func isBoolean(_ number: NSNumber) -> Bool {
        CFGetTypeID(number) == CFBooleanGetTypeID()
    }
}

enum WatchMeetingPipelineState: String, Codable, CaseIterable, Sendable {
    case received
    case meetingCreated = "meeting_created"
    case uploading
    case uploaded
    case processing
    case coreAccepted = "core_accepted"

    fileprivate var rank: Int {
        switch self {
        case .received: 0
        case .meetingCreated: 1
        case .uploading: 2
        case .uploaded: 3
        case .processing: 4
        case .coreAccepted: 5
        }
    }
}

struct WatchMeetingPipelineFailure: Codable, Hashable, Sendable {
    let message: String
    let retryable: Bool
    let occurredAt: Date
}

struct WatchMeetingInboxRecord: Codable, Hashable, Identifiable, Sendable {
    var id: UUID { metadata.captureID }
    let metadata: WatchMeetingTransferMetadata
    let storedFilename: String
    let receivedAt: Date
    var updatedAt: Date
    var state: WatchMeetingPipelineState
    var coreOrigin: String?
    var coreDeviceID: String?
    var coreMeetingID: String?
    var failure: WatchMeetingPipelineFailure?
    var acknowledgementQueuedAt: Date?
}

struct WatchMeetingAcknowledgement: Codable, Hashable, Sendable {
    enum State: String, Codable, Sendable {
        case durableReceived = "durable_received"
        case coreAccepted = "core_accepted"
        case failed
    }

    let captureID: UUID
    let state: State
    let acknowledgedAt: Date
    let coreMeetingID: String?
    let message: String?
    let retryable: Bool?

    static func durableReceived(
        captureID: UUID,
        at date: Date = .now
    ) -> WatchMeetingAcknowledgement {
        WatchMeetingAcknowledgement(
            captureID: captureID,
            state: .durableReceived,
            acknowledgedAt: date,
            coreMeetingID: nil,
            message: nil,
            retryable: nil
        )
    }

    static func coreAccepted(
        captureID: UUID,
        coreMeetingID: String,
        at date: Date = .now
    ) -> WatchMeetingAcknowledgement {
        WatchMeetingAcknowledgement(
            captureID: captureID,
            state: .coreAccepted,
            acknowledgedAt: date,
            coreMeetingID: coreMeetingID,
            message: nil,
            retryable: nil
        )
    }

    static func failed(
        captureID: UUID,
        message: String,
        retryable: Bool,
        at date: Date = .now
    ) -> WatchMeetingAcknowledgement {
        WatchMeetingAcknowledgement(
            captureID: captureID,
            state: .failed,
            acknowledgedAt: date,
            coreMeetingID: nil,
            message: message,
            retryable: retryable
        )
    }

    var propertyList: [String: Any] {
        var payload: [String: Any] = [
            WatchMeetingTransferContract.Key.schemaVersion:
                WatchMeetingTransferContract.acknowledgementSchema,
            WatchMeetingTransferContract.Key.captureID: captureID.uuidString.lowercased(),
            WatchMeetingTransferContract.Key.state: state.rawValue,
            WatchMeetingTransferContract.Key.acknowledgedAt:
                WatchMeetingISO8601.string(from: acknowledgedAt),
        ]
        if let coreMeetingID {
            payload[WatchMeetingTransferContract.Key.coreMeetingID] = coreMeetingID
        }
        if let message {
            payload[WatchMeetingTransferContract.Key.message] = message
        }
        if let retryable {
            payload[WatchMeetingTransferContract.Key.retryable] = retryable
        }
        return payload
    }
}

struct WatchMeetingInboxReceipt: Sendable {
    let record: WatchMeetingInboxRecord
    let isDuplicate: Bool
    let acknowledgement: WatchMeetingAcknowledgement
}

enum WatchMeetingInboxEvent: Sendable {
    case snapshot([WatchMeetingInboxRecord])
    case received(WatchMeetingInboxRecord, isDuplicate: Bool)
    case pipelineUpdated(WatchMeetingInboxRecord)
    case receiveFailed(captureID: UUID?, message: String)
}

enum WatchMeetingInboxError: LocalizedError, Equatable {
    case invalidMetadata(String)
    case fileSizeMismatch(expected: Int64, actual: Int64)
    case checksumMismatch
    case metadataConflict(UUID)
    case unknownCapture(UUID)
    case retainedFileMissing(UUID)
    case invalidTransition(from: WatchMeetingPipelineState, to: WatchMeetingPipelineState)
    case invalidCoreMeetingID
    case invalidCoreIdentity
    case coreIdentityConflict(UUID)
    case storageUnavailable(String)
    case corruptLedger

    var errorDescription: String? {
        switch self {
        case let .invalidMetadata(field): "Invalid Watch meeting metadata: \(field)."
        case let .fileSizeMismatch(expected, actual):
            "Watch meeting file size mismatch (expected \(expected), received \(actual))."
        case .checksumMismatch: "Watch meeting file checksum did not match."
        case let .metadataConflict(id): "Capture \(id) was redelivered with different metadata."
        case let .unknownCapture(id): "Unknown Watch meeting capture \(id)."
        case let .retainedFileMissing(id): "The retained recording for \(id) is missing."
        case let .invalidTransition(from, to):
            "Cannot advance Watch meeting capture from \(from.rawValue) to \(to.rawValue)."
        case .invalidCoreMeetingID: "Pilot Core returned an invalid meeting identifier."
        case .invalidCoreIdentity: "The Pilot Core destination identity is invalid."
        case let .coreIdentityConflict(id):
            "Capture \(id) belongs to a different Pilot Core device. Reconnect that device to continue."
        case let .storageUnavailable(message): "Watch meeting inbox is unavailable: \(message)"
        case .corruptLedger: "The Watch meeting inbox ledger is corrupt."
        }
    }
}

enum WatchMeetingFileIntegrity {
    static func sha256Hex(at fileURL: URL) throws -> String {
        let handle = try FileHandle(forReadingFrom: fileURL)
        defer { try? handle.close() }
        var hasher = SHA256()
        while let chunk = try handle.read(upToCount: 1_048_576), !chunk.isEmpty {
            hasher.update(data: chunk)
        }
        return hasher.finalize().map { String(format: "%02x", $0) }.joined()
    }

    static func verify(fileURL: URL, metadata: WatchMeetingTransferMetadata) throws {
        let attributes = try FileManager.default.attributesOfItem(atPath: fileURL.path)
        guard let size = (attributes[.size] as? NSNumber)?.int64Value else {
            throw WatchMeetingInboxError.fileSizeMismatch(expected: metadata.sizeBytes, actual: -1)
        }
        guard size == metadata.sizeBytes else {
            throw WatchMeetingInboxError.fileSizeMismatch(expected: metadata.sizeBytes, actual: size)
        }
        guard try sha256Hex(at: fileURL) == metadata.sha256 else {
            throw WatchMeetingInboxError.checksumMismatch
        }
    }
}

final class WatchMeetingInboxStore: @unchecked Sendable {
    private struct Ledger: Codable {
        let schemaVersion: Int
        let records: [WatchMeetingInboxRecord]
    }

    private let rootDirectory: URL
    private let ledgerURL: URL
    private let fileManager: FileManager
    private let lock = NSLock()
    private let continuationLock = NSLock()
    private var recordsByID: [UUID: WatchMeetingInboxRecord]
    private var continuations: [UUID: AsyncStream<WatchMeetingInboxEvent>.Continuation] = [:]

    init(rootDirectory: URL, fileManager: FileManager = .default) throws {
        self.rootDirectory = rootDirectory
        self.ledgerURL = rootDirectory.appendingPathComponent("ledger.json", isDirectory: false)
        self.fileManager = fileManager
        try fileManager.createDirectory(at: rootDirectory, withIntermediateDirectories: true)
        Self.protectInboxDirectory(rootDirectory, fileManager: fileManager)
        self.recordsByID = try Self.loadLedger(at: ledgerURL, fileManager: fileManager)
        cleanupAcceptedRecordings()
    }

    static func defaultRootDirectory(fileManager: FileManager = .default) throws -> URL {
        try fileManager.url(
            for: .applicationSupportDirectory,
            in: .userDomainMask,
            appropriateFor: nil,
            create: true
        ).appendingPathComponent("WatchMeetingInbox", isDirectory: true)
    }

    func allRecords() -> [WatchMeetingInboxRecord] {
        lock.withCriticalScope {
            recordsByID.values.sorted { $0.receivedAt < $1.receivedAt }
        }
    }

    func pendingRecords() -> [WatchMeetingInboxRecord] {
        allRecords().filter { $0.state != .coreAccepted }
    }

    func fileURL(for captureID: UUID) throws -> URL {
        try lock.withCriticalScope {
            guard let record = recordsByID[captureID] else {
                throw WatchMeetingInboxError.unknownCapture(captureID)
            }
            let url = rootDirectory.appendingPathComponent(record.storedFilename, isDirectory: false)
            guard fileManager.fileExists(atPath: url.path) else {
                throw WatchMeetingInboxError.retainedFileMissing(captureID)
            }
            return url
        }
    }

    func events() -> AsyncStream<WatchMeetingInboxEvent> {
        AsyncStream(bufferingPolicy: .bufferingNewest(100)) { continuation in
            let id = UUID()
            continuationLock.withCriticalScope { continuations[id] = continuation }
            continuation.yield(.snapshot(allRecords()))
            continuation.onTermination = { [weak self] _ in
                _ = self?.continuationLock.withCriticalScope {
                    self?.continuations.removeValue(forKey: id)
                }
            }
        }
    }

    func receiveSynchronously(
        fileURL temporaryURL: URL,
        metadata: WatchMeetingTransferMetadata,
        now: Date = .now
    ) throws -> WatchMeetingInboxReceipt {
        let receipt = try lock.withCriticalScope {
            if let existing = recordsByID[metadata.captureID] {
                guard existing.metadata == metadata else {
                    throw WatchMeetingInboxError.metadataConflict(metadata.captureID)
                }
                if existing.state == .coreAccepted {
                    return WatchMeetingInboxReceipt(
                        record: existing,
                        isDuplicate: true,
                        acknowledgement: .coreAccepted(
                            captureID: metadata.captureID,
                            coreMeetingID: existing.coreMeetingID ?? "unknown",
                            at: now
                        )
                    )
                }
                let retainedURL = rootDirectory.appendingPathComponent(
                    existing.storedFilename,
                    isDirectory: false
                )
                if fileManager.fileExists(atPath: retainedURL.path),
                   (try? WatchMeetingFileIntegrity.verify(fileURL: retainedURL, metadata: metadata)) != nil {
                    return WatchMeetingInboxReceipt(
                        record: existing,
                        isDuplicate: true,
                        acknowledgement: .durableReceived(captureID: metadata.captureID, at: now)
                    )
                }
                try copyAndVerify(temporaryURL: temporaryURL, destinationURL: retainedURL, metadata: metadata)
                return WatchMeetingInboxReceipt(
                    record: existing,
                    isDuplicate: true,
                    acknowledgement: .durableReceived(captureID: metadata.captureID, at: now)
                )
            }

            let storedFilename = Self.storedFilename(for: metadata)
            let retainedURL = rootDirectory.appendingPathComponent(storedFilename, isDirectory: false)
            if fileManager.fileExists(atPath: retainedURL.path) {
                do {
                    try WatchMeetingFileIntegrity.verify(fileURL: retainedURL, metadata: metadata)
                } catch {
                    try fileManager.removeItem(at: retainedURL)
                    try copyAndVerify(
                        temporaryURL: temporaryURL,
                        destinationURL: retainedURL,
                        metadata: metadata
                    )
                }
            } else {
                try copyAndVerify(
                    temporaryURL: temporaryURL,
                    destinationURL: retainedURL,
                    metadata: metadata
                )
            }

            let record = WatchMeetingInboxRecord(
                metadata: metadata,
                storedFilename: storedFilename,
                receivedAt: now,
                updatedAt: now,
                state: .received,
                coreOrigin: nil,
                coreDeviceID: nil,
                coreMeetingID: nil,
                failure: nil,
                acknowledgementQueuedAt: nil
            )
            var candidate = recordsByID
            candidate[metadata.captureID] = record
            try persist(candidate)
            recordsByID = candidate
            return WatchMeetingInboxReceipt(
                record: record,
                isDuplicate: false,
                acknowledgement: .durableReceived(captureID: metadata.captureID, at: now)
            )
        }
        publish(.received(receipt.record, isDuplicate: receipt.isDuplicate))
        return receipt
    }

    func bindCoreMeeting(
        captureID: UUID,
        coreMeetingID: String,
        now: Date = .now
    ) throws -> WatchMeetingInboxRecord {
        let normalizedID = coreMeetingID.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !normalizedID.isEmpty, normalizedID.count <= 200 else {
            throw WatchMeetingInboxError.invalidCoreMeetingID
        }
        return try mutate(captureID: captureID) { record in
            if let existingID = record.coreMeetingID, existingID != normalizedID {
                throw WatchMeetingInboxError.invalidCoreMeetingID
            }
            guard record.state == .received || record.state.rank >= WatchMeetingPipelineState.meetingCreated.rank else {
                throw WatchMeetingInboxError.invalidTransition(from: record.state, to: .meetingCreated)
            }
            record.coreMeetingID = normalizedID
            if record.state == .received { record.state = .meetingCreated }
            record.failure = nil
            record.updatedAt = now
        }
    }

    func bindCoreDestination(
        captureID: UUID,
        coreOrigin: String,
        coreDeviceID: String,
        now: Date = .now
    ) throws -> WatchMeetingInboxRecord {
        let origin = coreOrigin.trimmingCharacters(in: .whitespacesAndNewlines)
            .trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        let deviceID = coreDeviceID.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let url = URL(string: origin),
              ["http", "https"].contains(url.scheme?.lowercased() ?? ""),
              url.host != nil,
              url.user == nil,
              url.password == nil,
              !deviceID.isEmpty,
              deviceID.count <= 128 else {
            throw WatchMeetingInboxError.invalidCoreIdentity
        }
        return try mutate(captureID: captureID) { record in
            if let existingOrigin = record.coreOrigin, existingOrigin != origin {
                throw WatchMeetingInboxError.coreIdentityConflict(captureID)
            }
            if let existingDeviceID = record.coreDeviceID, existingDeviceID != deviceID {
                throw WatchMeetingInboxError.coreIdentityConflict(captureID)
            }
            record.coreOrigin = origin
            record.coreDeviceID = deviceID
            record.failure = nil
            record.updatedAt = now
        }
    }

    func markUploading(captureID: UUID, now: Date = .now) throws -> WatchMeetingInboxRecord {
        try advance(captureID: captureID, to: .uploading, now: now)
    }

    func markUploaded(captureID: UUID, now: Date = .now) throws -> WatchMeetingInboxRecord {
        try advance(captureID: captureID, to: .uploaded, now: now)
    }

    func markProcessing(captureID: UUID, now: Date = .now) throws -> WatchMeetingInboxRecord {
        try advance(captureID: captureID, to: .processing, now: now)
    }

    func markCoreAccepted(
        captureID: UUID,
        now: Date = .now
    ) throws -> (WatchMeetingInboxRecord, WatchMeetingAcknowledgement) {
        let record = try advance(captureID: captureID, to: .coreAccepted, now: now)
        guard let coreMeetingID = record.coreMeetingID else {
            throw WatchMeetingInboxError.invalidCoreMeetingID
        }
        let retainedURL = rootDirectory.appendingPathComponent(record.storedFilename, isDirectory: false)
        try? fileManager.removeItem(at: retainedURL)
        return (
            record,
            .coreAccepted(captureID: captureID, coreMeetingID: coreMeetingID, at: now)
        )
    }

    func markCoreFailed(
        captureID: UUID,
        message: String,
        retryable: Bool,
        now: Date = .now
    ) throws -> (WatchMeetingInboxRecord, WatchMeetingAcknowledgement) {
        let normalized = String(
            message.trimmingCharacters(in: .whitespacesAndNewlines).prefix(500)
        )
        let safeMessage = normalized.isEmpty ? "Pilot Core did not accept the recording." : normalized
        let record = try mutate(captureID: captureID) { record in
            guard record.state != .coreAccepted else {
                throw WatchMeetingInboxError.invalidTransition(from: record.state, to: record.state)
            }
            record.failure = WatchMeetingPipelineFailure(
                message: safeMessage,
                retryable: retryable,
                occurredAt: now
            )
            record.acknowledgementQueuedAt = nil
            record.updatedAt = now
        }
        return (
            record,
            .failed(captureID: captureID, message: safeMessage, retryable: retryable, at: now)
        )
    }

    func publishReceiveFailure(captureID: UUID?, error: Error) {
        publish(.receiveFailed(captureID: captureID, message: error.localizedDescription))
    }

    func markAcknowledgementQueued(
        captureID: UUID,
        at date: Date = .now
    ) throws -> WatchMeetingInboxRecord {
        try mutate(captureID: captureID) { record in
            record.acknowledgementQueuedAt = date
            record.updatedAt = date
        }
    }

    func cleanupAcceptedRecordings() {
        lock.withCriticalScope {
            for record in recordsByID.values where record.state == .coreAccepted {
                let url = rootDirectory.appendingPathComponent(
                    record.storedFilename,
                    isDirectory: false
                )
                try? fileManager.removeItem(at: url)
            }
        }
    }

    private func advance(
        captureID: UUID,
        to target: WatchMeetingPipelineState,
        now: Date
    ) throws -> WatchMeetingInboxRecord {
        try mutate(captureID: captureID) { record in
            guard record.coreMeetingID != nil else {
                throw WatchMeetingInboxError.invalidCoreMeetingID
            }
            if record.state.rank < target.rank {
                guard record.state.rank + 1 == target.rank else {
                    throw WatchMeetingInboxError.invalidTransition(from: record.state, to: target)
                }
                record.state = target
            }
            if target == .coreAccepted {
                record.acknowledgementQueuedAt = nil
            }
            record.failure = nil
            record.updatedAt = now
        }
    }

    private func mutate(
        captureID: UUID,
        body: (inout WatchMeetingInboxRecord) throws -> Void
    ) throws -> WatchMeetingInboxRecord {
        let updated = try lock.withCriticalScope {
            guard var record = recordsByID[captureID] else {
                throw WatchMeetingInboxError.unknownCapture(captureID)
            }
            try body(&record)
            var candidate = recordsByID
            candidate[captureID] = record
            try persist(candidate)
            recordsByID = candidate
            return record
        }
        publish(.pipelineUpdated(updated))
        return updated
    }

    private func copyAndVerify(
        temporaryURL: URL,
        destinationURL: URL,
        metadata: WatchMeetingTransferMetadata
    ) throws {
        let stagingURL = rootDirectory.appendingPathComponent(
            ".\(metadata.captureID.uuidString.lowercased()).\(UUID().uuidString).incoming",
            isDirectory: false
        )
        defer { try? fileManager.removeItem(at: stagingURL) }
        try fileManager.copyItem(at: temporaryURL, to: stagingURL)
        try WatchMeetingFileIntegrity.verify(fileURL: stagingURL, metadata: metadata)
        if fileManager.fileExists(atPath: destinationURL.path) {
            try fileManager.removeItem(at: destinationURL)
        }
        try fileManager.moveItem(at: stagingURL, to: destinationURL)
        try? fileManager.setAttributes(
            [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication],
            ofItemAtPath: destinationURL.path
        )
    }

    private func persist(_ records: [UUID: WatchMeetingInboxRecord]) throws {
        let ledger = Ledger(
            schemaVersion: 1,
            records: records.values.sorted { $0.receivedAt < $1.receivedAt }
        )
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        try encoder.encode(ledger).write(
            to: ledgerURL,
            options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication]
        )
    }

    private func publish(_ event: WatchMeetingInboxEvent) {
        let current = continuationLock.withCriticalScope { Array(continuations.values) }
        current.forEach { $0.yield(event) }
    }

    private static func storedFilename(for metadata: WatchMeetingTransferMetadata) -> String {
        let rawExtension = URL(fileURLWithPath: metadata.originalFilename).pathExtension.lowercased()
        let safeExtension = rawExtension.range(of: "^[a-z0-9]{1,8}$", options: .regularExpression) == nil
            ? "m4a"
            : rawExtension
        return "\(metadata.captureID.uuidString.lowercased()).\(safeExtension)"
    }

    private static func protectInboxDirectory(_ url: URL, fileManager: FileManager) {
        try? fileManager.setAttributes(
            [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication],
            ofItemAtPath: url.path
        )
        var values = URLResourceValues()
        values.isExcludedFromBackup = true
        var mutableURL = url
        try? mutableURL.setResourceValues(values)
    }

    private static func loadLedger(
        at ledgerURL: URL,
        fileManager: FileManager
    ) throws -> [UUID: WatchMeetingInboxRecord] {
        guard fileManager.fileExists(atPath: ledgerURL.path) else { return [:] }
        do {
            let decoder = JSONDecoder()
            decoder.dateDecodingStrategy = .iso8601
            let ledger = try decoder.decode(Ledger.self, from: Data(contentsOf: ledgerURL))
            guard ledger.schemaVersion == 1 else { throw WatchMeetingInboxError.corruptLedger }
            var result: [UUID: WatchMeetingInboxRecord] = [:]
            for record in ledger.records {
                guard result[record.id] == nil,
                      URL(fileURLWithPath: record.storedFilename).lastPathComponent
                        == record.storedFilename else {
                    throw WatchMeetingInboxError.corruptLedger
                }
                result[record.id] = record
            }
            return result
        } catch let error as WatchMeetingInboxError {
            throw error
        } catch {
            throw WatchMeetingInboxError.corruptLedger
        }
    }
}

/// Owns the iPhone side of Watch recording delivery. WCSession file URLs are only
/// valid during the delegate call, so `receiveSynchronously` completes the durable
/// copy, integrity checks, and ledger commit before that callback returns.
final class WatchMeetingInbox: NSObject, @unchecked Sendable {
    static let shared = WatchMeetingInbox()

    private let store: WatchMeetingInboxStore?
    private let setupFailure: String?

#if canImport(WatchConnectivity) && os(iOS)
    private let session: WCSession?
#endif

    override init() {
        do {
            let root = try WatchMeetingInboxStore.defaultRootDirectory()
            self.store = try WatchMeetingInboxStore(rootDirectory: root)
            self.setupFailure = nil
        } catch {
            self.store = nil
            self.setupFailure = error.localizedDescription
        }
#if canImport(WatchConnectivity) && os(iOS)
        self.session = WCSession.isSupported() ? .default : nil
#endif
        super.init()
    }

    init(store: WatchMeetingInboxStore) {
        self.store = store
        self.setupFailure = nil
#if canImport(WatchConnectivity) && os(iOS)
        self.session = WCSession.isSupported() ? .default : nil
#endif
        super.init()
    }

    func start() {
#if canImport(WatchConnectivity) && os(iOS)
        session?.delegate = self
        session?.activate()
        store?.cleanupAcceptedRecordings()
        replayUnqueuedAcknowledgements()
#endif
    }

    func pendingCaptures() throws -> [WatchMeetingInboxRecord] {
        try availableStore().pendingRecords()
    }

    func allCaptures() throws -> [WatchMeetingInboxRecord] {
        try availableStore().allRecords()
    }

    func fileURL(for captureID: UUID) throws -> URL {
        try availableStore().fileURL(for: captureID)
    }

    func events() throws -> AsyncStream<WatchMeetingInboxEvent> {
        try availableStore().events()
    }

    func bindCoreMeeting(captureID: UUID, coreMeetingID: String) throws -> WatchMeetingInboxRecord {
        try availableStore().bindCoreMeeting(captureID: captureID, coreMeetingID: coreMeetingID)
    }

    func bindCoreDestination(
        captureID: UUID,
        coreOrigin: String,
        coreDeviceID: String
    ) throws -> WatchMeetingInboxRecord {
        try availableStore().bindCoreDestination(
            captureID: captureID,
            coreOrigin: coreOrigin,
            coreDeviceID: coreDeviceID
        )
    }

    func markUploading(captureID: UUID) throws -> WatchMeetingInboxRecord {
        try availableStore().markUploading(captureID: captureID)
    }

    func markUploaded(captureID: UUID) throws -> WatchMeetingInboxRecord {
        try availableStore().markUploaded(captureID: captureID)
    }

    func markProcessing(captureID: UUID) throws -> WatchMeetingInboxRecord {
        try availableStore().markProcessing(captureID: captureID)
    }

    @discardableResult
    func markCoreAccepted(captureID: UUID) throws -> WatchMeetingInboxRecord {
        let result = try availableStore().markCoreAccepted(captureID: captureID)
        enqueueAndRecord(result.1)
        return result.0
    }

    @discardableResult
    func markCoreFailed(
        captureID: UUID,
        message: String,
        retryable: Bool = true
    ) throws -> WatchMeetingInboxRecord {
        let result = try availableStore().markCoreFailed(
            captureID: captureID,
            message: message,
            retryable: retryable
        )
        enqueueAndRecord(result.1)
        return result.0
    }

    @discardableResult
    func receiveTransferredFileSynchronously(
        at temporaryURL: URL,
        metadata propertyList: [String: Any]
    ) throws -> WatchMeetingInboxReceipt {
        let rawCaptureID = (propertyList[WatchMeetingTransferContract.Key.captureID] as? String)
            .flatMap(UUID.init(uuidString:))
        if let rawCaptureID {
            Task { @MainActor in
                PilotWatchBackgroundExecution.shared.begin(captureID: rawCaptureID)
            }
        }
        do {
            let metadata = try WatchMeetingTransferMetadata(propertyList: propertyList)
            let receipt = try availableStore().receiveSynchronously(
                fileURL: temporaryURL,
                metadata: metadata
            )
            enqueueAndRecord(receipt.acknowledgement)
            return receipt
        } catch {
            if let rawCaptureID {
                _ = enqueue(.failed(
                    captureID: rawCaptureID,
                    message: error.localizedDescription,
                    retryable: Self.receiveFailureIsRetryable(error)
                ))
            }
            store?.publishReceiveFailure(captureID: rawCaptureID, error: error)
            if let rawCaptureID {
                Task { @MainActor in
                    PilotWatchBackgroundExecution.shared.end(captureID: rawCaptureID)
                }
            }
            throw error
        }
    }

    private func availableStore() throws -> WatchMeetingInboxStore {
        guard let store else {
            throw WatchMeetingInboxError.storageUnavailable(setupFailure ?? "unknown error")
        }
        return store
    }

    @discardableResult
    private func enqueue(_ acknowledgement: WatchMeetingAcknowledgement) -> Bool {
#if canImport(WatchConnectivity) && os(iOS)
        guard let session else { return false }
        if session.activationState == .notActivated {
            session.delegate = self
            session.activate()
        }
        // transferUserInfo is queued by WatchConnectivity and does not require
        // the Watch to be reachable when this method is called.
        session.transferUserInfo(acknowledgement.propertyList)
        return true
#else
        return false
#endif
    }

    private func enqueueAndRecord(_ acknowledgement: WatchMeetingAcknowledgement) {
        guard enqueue(acknowledgement) else { return }
        // If the app exits after transferUserInfo but before this ledger update,
        // start() safely replays the idempotent acknowledgement on next launch.
        _ = try? store?.markAcknowledgementQueued(captureID: acknowledgement.captureID)
    }

    private func replayUnqueuedAcknowledgements() {
        guard let records = store?.allRecords() else { return }
        for record in records where record.acknowledgementQueuedAt == nil {
            let acknowledgement: WatchMeetingAcknowledgement
            if record.state == .coreAccepted, let coreMeetingID = record.coreMeetingID {
                acknowledgement = .coreAccepted(
                    captureID: record.id,
                    coreMeetingID: coreMeetingID
                )
            } else if let failure = record.failure {
                acknowledgement = .failed(
                    captureID: record.id,
                    message: failure.message,
                    retryable: failure.retryable
                )
            } else {
                acknowledgement = .durableReceived(captureID: record.id)
            }
            enqueueAndRecord(acknowledgement)
        }
    }

    private static func receiveFailureIsRetryable(_ error: Error) -> Bool {
        switch error as? WatchMeetingInboxError {
        case .invalidMetadata, .metadataConflict:
            false
        case .fileSizeMismatch, .checksumMismatch, .storageUnavailable,
             .retainedFileMissing, .corruptLedger:
            true
        case .invalidCoreIdentity, .coreIdentityConflict:
            false
        case .unknownCapture, .invalidTransition, .invalidCoreMeetingID, .none:
            true
        }
    }
}

#if canImport(WatchConnectivity) && os(iOS)
extension WatchMeetingInbox: WCSessionDelegate {
    func session(
        _ session: WCSession,
        activationDidCompleteWith activationState: WCSessionActivationState,
        error: Error?
    ) {}

    func sessionDidBecomeInactive(_ session: WCSession) {}

    func sessionDidDeactivate(_ session: WCSession) {
        session.activate()
    }

    func session(_ session: WCSession, didReceive file: WCSessionFile) {
        _ = try? receiveTransferredFileSynchronously(
            at: file.fileURL,
            metadata: file.metadata ?? [:]
        )
    }
}
#endif

private enum WatchMeetingISO8601 {
    static func date(from string: String) -> Date? {
        let fractional = ISO8601DateFormatter()
        fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = fractional.date(from: string) { return date }
        let whole = ISO8601DateFormatter()
        whole.formatOptions = [.withInternetDateTime]
        return whole.date(from: string)
    }

    static func string(from date: Date) -> String {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter.string(from: date)
    }
}

private extension NSLock {
    func withCriticalScope<T>(_ body: () throws -> T) rethrows -> T {
        lock()
        defer { unlock() }
        return try body()
    }
}
