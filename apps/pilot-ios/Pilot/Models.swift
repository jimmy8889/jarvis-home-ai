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
