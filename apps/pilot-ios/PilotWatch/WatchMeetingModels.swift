import Foundation

enum WatchMeetingDeliveryState: String, Codable, Sendable {
    case recording
    case queued
    case transferring
    case durableReceived
    case coreAccepted
    case failed

    var label: String {
        switch self {
        case .recording: "Recording"
        case .queued: "Waiting for iPhone"
        case .transferring: "Sending to iPhone"
        case .durableReceived: "Uploading to Pilot"
        case .coreAccepted: "Saved in Pilot Core"
        case .failed: "Needs attention"
        }
    }
}

struct WatchMeetingCapture: Identifiable, Codable, Equatable, Sendable {
    let id: UUID
    var title: String
    let startedAt: Date
    var durationSeconds: TimeInterval
    let originalFilename: String
    var sha256: String
    var sizeBytes: Int64
    var deliveryState: WatchMeetingDeliveryState
    var attemptCount: Int
    var lastAttemptAt: Date?
    var acknowledgedAt: Date?
    var coreMeetingID: String?
    var lastError: String?
    var retryable: Bool

    var hasLocalAudio: Bool {
        deliveryState != .coreAccepted
    }
}

enum WatchRecordingPresentation: Equatable, Sendable {
    case idle
    case requestingPermission
    case recording
    case finalizing
    case interrupted(String)
    case failed(String)

    var label: String {
        switch self {
        case .idle: "Ready"
        case .requestingPermission: "Checking microphone"
        case .recording: "Recording"
        case .finalizing: "Saving"
        case .interrupted: "Recording interrupted"
        case .failed: "Needs attention"
        }
    }
}

enum WatchMeetingProtocol {
    static let transferSchema = "pilot.watch.meeting.transfer.v1"
    static let acknowledgementSchema = "pilot.watch.meeting.ack.v1"

    static func iso8601String(from date: Date) -> String {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter.string(from: date)
    }

    static func date(fromISO8601 value: String) -> Date? {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter.date(from: value)
    }
}

struct WatchMeetingAcknowledgement: Sendable {
    enum State: String, Sendable {
        case durableReceived = "durable_received"
        case coreAccepted = "core_accepted"
        case failed
    }

    let captureID: UUID
    let state: State
    let acknowledgedAt: Date
    let coreMeetingID: String?
    let message: String?
    let retryable: Bool

    init?(propertyList: [String: Any]) {
        guard
            propertyList["schema_version"] as? String == WatchMeetingProtocol.acknowledgementSchema,
            let captureIDString = propertyList["capture_id"] as? String,
            let captureID = UUID(uuidString: captureIDString),
            let stateString = propertyList["state"] as? String,
            let state = State(rawValue: stateString)
        else {
            return nil
        }

        self.captureID = captureID
        self.state = state
        if
            let value = propertyList["acknowledged_at"] as? String,
            let date = WatchMeetingProtocol.date(fromISO8601: value)
        {
            acknowledgedAt = date
        } else {
            acknowledgedAt = Date()
        }
        coreMeetingID = propertyList["core_meeting_id"] as? String
        message = propertyList["message"] as? String
        retryable = propertyList["retryable"] as? Bool ?? false
    }
}
