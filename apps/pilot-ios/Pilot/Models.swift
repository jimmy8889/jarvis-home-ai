import Foundation

struct PilotRoom: Codable, Identifiable, Hashable {
    let id: String
    let name: String
    let responsePlayerID: String
    let defaultMusicPlayerID: String
    let players: [PilotPlayer]

    enum CodingKeys: String, CodingKey {
        case id, name, players
        case responsePlayerID = "response_player_id"
        case defaultMusicPlayerID = "default_music_player_id"
    }
}

struct PilotPlayer: Codable, Identifiable, Hashable {
    let id: String
    let roomID: String
    let name: String
    let kind: String
    let protocolName: String
    let enabled: Bool
    let controlEnabled: Bool

    enum CodingKeys: String, CodingKey {
        case id, name, kind, enabled
        case roomID = "room_id"
        case protocolName = "protocol"
        case controlEnabled = "control_enabled"
    }
}

struct DeviceMediaEnvelope: Codable {
    let deviceID: String
    let roomID: String
    let rooms: [PilotRoom]
    let media: MediaSnapshot

    enum CodingKeys: String, CodingKey {
        case rooms, media
        case deviceID = "device_id"
        case roomID = "room_id"
    }
}

struct MediaSnapshot: Codable {
    let observedAt: String
    let players: [String: PilotPlayerState]

    enum CodingKeys: String, CodingKey {
        case players
        case observedAt = "observed_at"
    }
}

struct PilotPlayerState: Codable, Identifiable {
    let player: PilotPlayer
    let status: String
    let effective: EffectiveMediaState

    var id: String { player.id }
}

struct EffectiveMediaState: Codable {
    let available: Bool?
    let powered: Bool?
    let playbackState: String?
    let volumePercent: Int?
    let muted: Bool?
    let source: String?
    let media: CurrentMedia?

    enum CodingKeys: String, CodingKey {
        case available, powered, muted, source, media
        case playbackState = "playback_state"
        case volumePercent = "volume_percent"
    }
}

struct CurrentMedia: Codable, Hashable {
    let title: String?
    let artist: String?
    let album: String?
}

struct AssistantReply: Codable {
    let responseText: String
    let conversationID: String
    let provider: String
    let continueConversation: Bool
    let roomID: String

    enum CodingKeys: String, CodingKey {
        case provider
        case responseText = "response_text"
        case conversationID = "conversation_id"
        case continueConversation = "continue_conversation"
        case roomID = "room_id"
    }
}

struct ChatMessage: Identifiable, Hashable {
    let id: UUID
    let role: Role
    let text: String
    let createdAt: Date
    let isError: Bool

    init(
        id: UUID = UUID(),
        role: Role,
        text: String,
        createdAt: Date = .now,
        isError: Bool = false
    ) {
        self.id = id
        self.role = role
        self.text = text
        self.createdAt = createdAt
        self.isError = isError
    }

    enum Role: Hashable {
        case user
        case pilot
    }
}

struct MusicSearchResult: Identifiable, Hashable {
    let id: String
    let title: String
    let subtitle: String
    let uri: String
    let kind: MusicResultKind
    let artworkURL: URL?
}

enum MusicResultKind: String, Hashable, CaseIterable {
    case track
    case album
    case artist
    case playlist
    case radio
    case other

    var title: String {
        switch self {
        case .track: "Songs"
        case .album: "Albums"
        case .artist: "Artists"
        case .playlist: "Playlists"
        case .radio: "Radio"
        case .other: "More"
        }
    }

    var symbol: String {
        switch self {
        case .track: "music.note"
        case .album: "square.stack"
        case .artist: "person.wave.2"
        case .playlist: "music.note.list"
        case .radio: "dot.radiowaves.left.and.right"
        case .other: "waveform"
        }
    }
}

struct EnergySnapshot: Equatable {
    let status: Status
    let solarWatts: Double?
    let gridWatts: Double?
    let batteryWatts: Double?
    let batteryStateOfCharge: Double?
    let homeLoadWatts: Double?
    let observedAt: Date?
    let detail: String?

    enum Status: Equatable {
        case live
        case stale
        case unavailable
    }

    static let awaitingBackend = EnergySnapshot(
        status: .unavailable,
        solarWatts: nil,
        gridWatts: nil,
        batteryWatts: nil,
        batteryStateOfCharge: nil,
        homeLoadWatts: nil,
        observedAt: nil,
        detail: "Energy access for portable clients is waiting on a device-scoped Pilot Core contract."
    )

    var isPopulated: Bool {
        [solarWatts, gridWatts, batteryWatts, batteryStateOfCharge, homeLoadWatts]
            .contains { $0 != nil }
    }
}

enum PilotConnectionState: Equatable {
    case notConfigured
    case connecting
    case connected
    case offline(String)

    var label: String {
        switch self {
        case .notConfigured: "Not configured"
        case .connecting: "Connecting"
        case .connected: "Connected"
        case let .offline(message): message
        }
    }

    var isConnected: Bool {
        self == .connected
    }
}

struct MediaCommand: Encodable {
    let action: String
    var playerID: String?
    var mediaURI: String?
    var targetRoomID: String?
    var targetPlayerID: String?
    var volume: Int?
    var source: String?

    enum CodingKeys: String, CodingKey {
        case action, volume, source
        case playerID = "player_id"
        case mediaURI = "media_uri"
        case targetRoomID = "target_room_id"
        case targetPlayerID = "target_player_id"
    }
}

enum JSONValue: Codable, Hashable, Sendable {
    case string(String)
    case number(Double)
    case boolean(Bool)
    case object([String: JSONValue])
    case array([JSONValue])
    case null

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() { self = .null }
        else if let value = try? container.decode(Bool.self) { self = .boolean(value) }
        else if let value = try? container.decode(Double.self) { self = .number(value) }
        else if let value = try? container.decode(String.self) { self = .string(value) }
        else if let value = try? container.decode([String: JSONValue].self) { self = .object(value) }
        else { self = .array(try container.decode([JSONValue].self)) }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case let .string(value): try container.encode(value)
        case let .number(value): try container.encode(value)
        case let .boolean(value): try container.encode(value)
        case let .object(value): try container.encode(value)
        case let .array(value): try container.encode(value)
        case .null: try container.encodeNil()
        }
    }

    var number: Double? {
        if case let .number(value) = self { value } else { nil }
    }
}

struct HomeRoom: Codable, Hashable, Sendable {
    let id: String
    let name: String
    let homeAreaIDs: [String]

    enum CodingKeys: String, CodingKey {
        case id, name
        case homeAreaIDs = "home_area_ids"
    }
}

struct HomeEntity: Codable, Identifiable, Hashable, Sendable {
    var id: String { entityID }
    let entityID: String
    let domain: String
    let name: String
    let state: String
    let attributes: [String: JSONValue]
    let areaID: String?
    let availability: String
    let unavailable: Bool
    let stale: Bool
    let observedAt: String?
    let actions: [String]

    enum CodingKeys: String, CodingKey {
        case domain, name, state, attributes, availability, unavailable, stale, actions
        case entityID = "entity_id"
        case areaID = "area_id"
        case observedAt = "observed_at"
    }

    var isOn: Bool {
        ["on", "open", "opening", "unlocked", "active", "heat", "cool"]
            .contains(state.lowercased())
    }

    var brightnessPercent: Double? {
        attributes["brightness"]?.number.map { min(max($0 / 255 * 100, 0), 100) }
    }
}

struct HomeProjection: Codable, Sendable {
    let deviceID: String
    let selectedRoomID: String
    let room: HomeRoom
    let entityCount: Int
    let entities: [HomeEntity]

    enum CodingKeys: String, CodingKey {
        case room, entities
        case deviceID = "device_id"
        case selectedRoomID = "selected_room_id"
        case entityCount = "entity_count"
    }
}

struct HomeActionRequest: Encodable, Sendable {
    let roomID: String
    let entityID: String
    let action: String
    let parameters: [String: JSONValue]

    enum CodingKeys: String, CodingKey {
        case action, parameters
        case roomID = "room_id"
        case entityID = "entity_id"
    }
}

struct HomeActionEnvelope: Codable, Sendable {
    let action: HomeAction
}

struct HomeAction: Codable, Identifiable, Sendable {
    let id: String
    let status: String
    let roomID: String
    let entityID: String
    let action: String
    let risk: String
    let confirmationRequired: Bool
    let description: String?

    enum CodingKeys: String, CodingKey {
        case id, status, action, risk, description
        case roomID = "room_id"
        case entityID = "entity_id"
        case confirmationRequired = "confirmation_required"
    }
}

struct MeetingEnvelope: Codable, Sendable {
    let meetings: [PilotMeeting]
}

struct MeetingProcessEnvelope: Codable, Sendable {
    let meeting: PilotMeeting
}

struct PilotMeeting: Codable, Identifiable, Hashable, Sendable {
    let id: String
    let title: String
    let language: String
    let sourceDeviceID: String?
    let startedAt: String
    let endedAt: String?
    let status: String
    let summary: String?
    let hasRecording: Bool?
    let transcriptSegmentCount: Int?
    let actionItemCount: Int?

    enum CodingKeys: String, CodingKey {
        case id, title, language, status, summary
        case sourceDeviceID = "source_device_id"
        case startedAt = "started_at"
        case endedAt = "ended_at"
        case hasRecording = "has_recording"
        case transcriptSegmentCount = "transcript_segment_count"
        case actionItemCount = "action_item_count"
    }

    var statusLabel: String {
        switch status {
        case "created": "Ready to record"
        case "recorded": "Uploaded"
        case "processing": "Processing locally"
        case "transcribed": "Analysing"
        case "ready": "Ready"
        case "failed": "Needs attention"
        default: status.capitalized
        }
    }
}

struct PilotMeetingDetail: Codable, Identifiable, Hashable, Sendable {
    let id: String
    let title: String
    let language: String
    let sourceDeviceID: String?
    let startedAt: String
    let endedAt: String?
    let status: String
    let summary: String?
    let recording: MeetingRecording?
    let participants: [MeetingParticipant]
    let transcript: [MeetingTranscriptSegment]
    let decisions: [MeetingDecision]
    let actionItems: [MeetingActionItem]

    enum CodingKeys: String, CodingKey {
        case id, title, language, status, summary, recording, participants, transcript, decisions
        case sourceDeviceID = "source_device_id"
        case startedAt = "started_at"
        case endedAt = "ended_at"
        case actionItems = "action_items"
    }
}

struct MeetingRecording: Codable, Hashable, Sendable {
    let filename: String
    let contentType: String
    let sha256: String
    let sizeBytes: Int
    let createdAt: String

    enum CodingKeys: String, CodingKey {
        case filename, sha256
        case contentType = "content_type"
        case sizeBytes = "size_bytes"
        case createdAt = "created_at"
    }
}

struct MeetingParticipant: Codable, Identifiable, Hashable, Sendable {
    let id: String
    let displayName: String?
    let speakerLabel: String

    enum CodingKeys: String, CodingKey {
        case id
        case displayName = "display_name"
        case speakerLabel = "speaker_label"
    }
}

struct MeetingTranscriptSegment: Codable, Identifiable, Hashable, Sendable {
    let id: String
    let sequence: Int
    let speakerLabel: String
    let startMS: Int
    let endMS: Int
    let text: String
    let confidence: Double?

    enum CodingKeys: String, CodingKey {
        case id, sequence, text, confidence
        case speakerLabel = "speaker_label"
        case startMS = "start_ms"
        case endMS = "end_ms"
    }
}

struct MeetingDecision: Codable, Identifiable, Hashable, Sendable {
    let id: String
    let summary: String
    let segmentIDs: [String]

    enum CodingKeys: String, CodingKey {
        case id, summary
        case segmentIDs = "segment_ids"
    }
}

struct MeetingActionItem: Codable, Identifiable, Hashable, Sendable {
    let id: String
    let task: String
    let owner: String?
    let dueAt: String?
    let status: String
    let confidence: Double?
    let segmentIDs: [String]

    enum CodingKeys: String, CodingKey {
        case id, task, owner, status, confidence
        case dueAt = "due_at"
        case segmentIDs = "segment_ids"
    }
}
