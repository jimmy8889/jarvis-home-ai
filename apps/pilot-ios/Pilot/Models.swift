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

struct CurrentMedia: Codable {
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
    let id = UUID()
    let role: Role
    let text: String

    enum Role {
        case user
        case pilot
    }
}

struct MusicSearchResult: Identifiable, Hashable {
    let id: String
    let title: String
    let subtitle: String
    let uri: String
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
