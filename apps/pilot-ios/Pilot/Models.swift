import Foundation

struct PilotRoom: Codable, Identifiable, Hashable, Sendable {
    let id: String
    let name: String
    let responsePlayerID: String
    let defaultMusicPlayerID: String
    let musicEnabled: Bool?
    let players: [PilotPlayer]

    enum CodingKeys: String, CodingKey {
        case id, name, players
        case responsePlayerID = "response_player_id"
        case defaultMusicPlayerID = "default_music_player_id"
        case musicEnabled = "music_enabled"
    }
}

struct PilotPlayer: Codable, Identifiable, Hashable, Sendable {
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

struct DeviceMediaEnvelope: Codable, Sendable {
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

struct MediaSnapshot: Codable, Sendable {
    let observedAt: String
    let players: [String: PilotPlayerState]

    enum CodingKeys: String, CodingKey {
        case players
        case observedAt = "observed_at"
    }
}

struct PilotPlayerState: Codable, Identifiable, Hashable, Sendable {
    let player: PilotPlayer
    let status: String
    let effective: EffectiveMediaState
    let capabilities: MediaCapabilities?

    var id: String { player.id }
}

struct EffectiveMediaState: Codable, Hashable, Sendable {
    let available: Bool?
    let powered: Bool?
    let playbackState: String?
    let volumePercent: Int?
    let muted: Bool?
    let source: String?
    let media: CurrentMedia?
    let positionSeconds: Double?
    let durationSeconds: Double?
    let capabilities: [String]?
    let artworkURL: String?
    let queue: MediaQueue?
    let group: MediaGroup?

    enum CodingKeys: String, CodingKey {
        case available, powered, muted, source, media
        case playbackState = "playback_state"
        case volumePercent = "volume_percent"
        case positionSeconds = "position_seconds"
        case durationSeconds = "duration_seconds"
        case artworkURL = "artwork_url"
        case capabilities, queue, group
    }

    init(
        available: Bool?,
        powered: Bool?,
        playbackState: String?,
        volumePercent: Int?,
        muted: Bool?,
        source: String?,
        media: CurrentMedia?,
        positionSeconds: Double? = nil,
        durationSeconds: Double? = nil,
        capabilities: [String]? = nil,
        artworkURL: String? = nil,
        queue: MediaQueue? = nil,
        group: MediaGroup? = nil
    ) {
        self.available = available
        self.powered = powered
        self.playbackState = playbackState
        self.volumePercent = volumePercent
        self.muted = muted
        self.source = source
        self.media = media
        self.positionSeconds = positionSeconds
        self.durationSeconds = durationSeconds
        self.capabilities = capabilities
        self.artworkURL = artworkURL
        self.queue = queue
        self.group = group
    }
}

struct MediaCapabilities: Codable, Hashable, Sendable {
    let actions: [String]
    let transport: Bool?
    let volume: Bool?
    let seek: Bool?
    let transfer: Bool?
    let grouping: Bool?
}

struct MediaQueue: Codable, Hashable, Sendable {
    let status: String?
    let index: Int?
    let items: [MediaQueueItem]
    let truncated: Bool?
}

struct CurrentMedia: Codable, Hashable, Sendable {
    let title: String?
    let artist: String?
    let album: String?
    let uri: String?
    let artworkURL: String?

    enum CodingKeys: String, CodingKey {
        case title, artist, album, uri
        case artworkURL = "artwork_url"
    }

    init(
        title: String?,
        artist: String?,
        album: String?,
        uri: String? = nil,
        artworkURL: String? = nil
    ) {
        self.title = title
        self.artist = artist
        self.album = album
        self.uri = uri
        self.artworkURL = artworkURL
    }
}

struct MediaQueueItem: Codable, Identifiable, Hashable, Sendable {
    let id: String
    let title: String
    let artist: String?
    let album: String?
    let uri: String?
    let artworkURL: String?
    let artwork: MediaArtwork?
    let isCurrent: Bool?

    enum CodingKeys: String, CodingKey {
        case id, title, artist, album, uri, artwork
        case artworkURL = "artwork_url"
        case isCurrent = "is_current"
    }

    var resolvedArtworkURL: URL? {
        (artworkURL ?? artwork?.proxyURL ?? artwork?.sourceURL).flatMap(URL.init(string:))
    }
}

struct MediaArtwork: Codable, Hashable, Sendable {
    let available: Bool?
    let sourceURL: String?
    let proxyURL: String?

    enum CodingKeys: String, CodingKey {
        case available
        case sourceURL = "source_url"
        case proxyURL = "proxy_url"
    }
}

struct MediaGroup: Codable, Hashable, Sendable {
    let id: String?
    let name: String?
    let playerIDs: [String]

    enum CodingKeys: String, CodingKey {
        case id, name
        case playerIDs = "player_ids"
    }
}

struct AssistantReply: Codable, Sendable {
    let responseText: String
    let conversationID: String
    let provider: String
    let continueConversation: Bool
    let roomID: String
    let status: String?
    let result: JSONValue?
    let toolCalls: [AssistantToolCall]?
    let cards: [AssistantCard]?
    let sources: [AssistantSource]?
    let actions: [AssistantAction]?

    enum CodingKeys: String, CodingKey {
        case provider, status, result, cards, sources, actions
        case responseText = "response_text"
        case conversationID = "conversation_id"
        case continueConversation = "continue_conversation"
        case roomID = "room_id"
        case toolCalls = "tool_calls"
    }
}

struct AssistantToolCall: Codable, Identifiable, Hashable, Sendable {
    let id: String?
    let name: String
    let status: String?
    let arguments: JSONValue?
    let result: JSONValue?

    var stableID: String { id ?? "\(name)-\(status ?? "complete")" }

    enum CodingKeys: String, CodingKey {
        case id, name, status, arguments
        case result = "output"
    }
}

struct AssistantCard: Codable, Identifiable, Hashable, Sendable {
    let id: String
    let kind: String
    let title: String
    let subtitle: String?
    let symbol: String?
    let values: [String: JSONValue]?
}

struct AssistantSource: Codable, Identifiable, Hashable, Sendable {
    let kind: String?
    let meetingID: String?
    let segmentID: String?
    let startMS: Int?
    let label: String?
    let tool: String?
    let url: String?

    var id: String {
        [meetingID, segmentID, tool, label].compactMap { $0 }.joined(separator: ":")
    }
    var title: String { label ?? tool?.replacingOccurrences(of: "_", with: " ").capitalized ?? "Source" }

    enum CodingKeys: String, CodingKey {
        case kind, label, tool, url
        case meetingID = "meeting_id"
        case segmentID = "segment_id"
        case startMS = "start_ms"
    }
}

struct AssistantAction: Codable, Identifiable, Hashable, Sendable {
    let id: String
    let name: String
    let status: String?
    let arguments: JSONValue?

    var title: String { name.replacingOccurrences(of: "_", with: " ").capitalized }
}

struct ChatMessage: Identifiable, Hashable {
    let id: UUID
    let role: Role
    let text: String
    let createdAt: Date
    let isError: Bool
    let provider: String?
    let cards: [AssistantCard]
    let sources: [AssistantSource]
    let actions: [AssistantAction]
    let toolCalls: [AssistantToolCall]

    init(
        id: UUID = UUID(),
        role: Role,
        text: String,
        createdAt: Date = .now,
        isError: Bool = false,
        provider: String? = nil,
        cards: [AssistantCard] = [],
        sources: [AssistantSource] = [],
        actions: [AssistantAction] = [],
        toolCalls: [AssistantToolCall] = []
    ) {
        self.id = id
        self.role = role
        self.text = text
        self.createdAt = createdAt
        self.isError = isError
        self.provider = provider
        self.cards = cards
        self.sources = sources
        self.actions = actions
        self.toolCalls = toolCalls
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

struct MusicBrowseSection: Identifiable, Hashable {
    let id: String
    let title: String
    let items: [MusicSearchResult]
}

struct MusicBrowsePage: Hashable {
    let item: MusicSearchResult
    let sections: [MusicBrowseSection]
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

struct EnergySnapshot: Codable, Equatable, Sendable {
    let status: Status
    let solarWatts: Double?
    let gridWatts: Double?
    let batteryWatts: Double?
    let batteryStateOfCharge: Double?
    let homeLoadWatts: Double?
    let observedAt: Date?
    let detail: String?

    enum Status: String, Codable, Equatable, Sendable {
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

struct EnergyEnvelope: Codable, Sendable {
    let status: String
    let solar: EnergyMeasurement?
    let grid: EnergyMeasurement?
    let battery: EnergyMeasurement?
    let batterySOC: EnergyMeasurement?
    let homeLoad: EnergyMeasurement?
    let detail: String?

    enum CodingKeys: String, CodingKey {
        case status, solar, grid, battery, detail
        case batterySOC = "battery_soc"
        case homeLoad = "home_load"
    }

    var snapshot: EnergySnapshot {
        let dates = [solar, grid, battery, batterySOC, homeLoad]
            .compactMap { $0?.observedDate }
        let mappedStatus: EnergySnapshot.Status
        switch status.lowercased() {
        case "ok", "live": mappedStatus = .live
        case "partial", "stale": mappedStatus = .stale
        default: mappedStatus = .unavailable
        }
        return EnergySnapshot(
            status: mappedStatus,
            solarWatts: solar?.value,
            gridWatts: grid?.value,
            batteryWatts: battery?.value,
            batteryStateOfCharge: batterySOC?.value,
            homeLoadWatts: homeLoad?.value,
            observedAt: dates.max(),
            detail: detail
        )
    }
}

struct DashboardSnapshot: Codable, Equatable, Sendable {
    let schemaVersion: String
    let generatedAt: String?
    let status: String
    let power: DashboardPower
    let scene: DashboardScene?
    let daily: DashboardDaily
    let vehicle: DashboardVehicle
    let tariff: DashboardTariff
    let temperatures: [DashboardTemperature]
    let history: DashboardHistory
    let weather: DashboardWeather
    let controls: DashboardControls

    enum CodingKeys: String, CodingKey {
        case status, power, scene, daily, vehicle, tariff, temperatures, history, weather, controls
        case schemaVersion = "schema_version"
        case generatedAt = "generated_at"
    }

    static let unavailable = DashboardSnapshot(
        schemaVersion: "pilot.dashboard.v1",
        generatedAt: nil,
        status: "unavailable",
        power: .empty,
        scene: nil,
        daily: .empty,
        vehicle: .empty,
        tariff: .empty,
        temperatures: [],
        history: .empty,
        weather: .empty,
        controls: .empty
    )
}

struct DashboardScene: Codable, Equatable, Sendable {
    let isDay: Bool?
    let sunState: String?
    let solarElevationDegrees: Double?

    enum CodingKeys: String, CodingKey {
        case isDay = "is_day"
        case sunState = "sun_state"
        case solarElevationDegrees = "solar_elevation_degrees"
    }
}

struct DashboardPower: Codable, Equatable, Sendable {
    let solarWatts: Double?
    let gridWatts: Double?
    let batteryWatts: Double?
    let batteryStateOfCharge: Double?
    let homeLoadWatts: Double?
    let serverRackWatts: Double?
    let vehicleWatts: Double?
    let directions: [String: String]
    let flowActive: [String: Bool]

    enum CodingKeys: String, CodingKey {
        case directions
        case solarWatts = "solar_w"
        case gridWatts = "grid_w"
        case batteryWatts = "battery_w"
        case batteryStateOfCharge = "battery_soc_percent"
        case homeLoadWatts = "home_load_w"
        case serverRackWatts = "server_rack_w"
        case vehicleWatts = "vehicle_w"
        case flowActive = "flow_active"
    }

    static let empty = DashboardPower(
        solarWatts: nil, gridWatts: nil, batteryWatts: nil,
        batteryStateOfCharge: nil, homeLoadWatts: nil, serverRackWatts: nil,
        vehicleWatts: nil, directions: [:], flowActive: [:]
    )
}

struct DashboardDaily: Codable, Equatable, Sendable {
    let solarGeneratedKWh: Double?
    let homeUsedKWh: Double?
    let gridExportedKWh: Double?

    enum CodingKeys: String, CodingKey {
        case solarGeneratedKWh = "solar_generated_kwh"
        case homeUsedKWh = "home_used_kwh"
        case gridExportedKWh = "grid_exported_kwh"
    }

    static let empty = DashboardDaily(
        solarGeneratedKWh: nil, homeUsedKWh: nil, gridExportedKWh: nil
    )
}

struct DashboardVehicle: Codable, Equatable, Sendable {
    let name: String
    let connected: Bool?
    let charging: Bool
    let powerWatts: Double?
    let stateOfCharge: Double?

    enum CodingKeys: String, CodingKey {
        case name, connected, charging
        case powerWatts = "power_w"
        case stateOfCharge = "state_of_charge_percent"
    }

    static let empty = DashboardVehicle(
        name: "Jarvis", connected: nil, charging: false,
        powerWatts: nil, stateOfCharge: nil
    )
}

struct DashboardTariffPoint: Codable, Identifiable, Equatable, Sendable {
    let at: String?
    let centsPerKWh: Double?
    var id: String { at ?? String(centsPerKWh ?? 0) }

    enum CodingKeys: String, CodingKey {
        case at
        case centsPerKWh = "cents_per_kwh"
    }
}

struct DashboardTariff: Codable, Equatable, Sendable {
    let importCentsPerKWh: Double?
    let feedInCentsPerKWh: Double?
    let feedInForecast: [DashboardTariffPoint]

    enum CodingKeys: String, CodingKey {
        case importCentsPerKWh = "import_cents_per_kwh"
        case feedInCentsPerKWh = "feed_in_cents_per_kwh"
        case feedInForecast = "feed_in_forecast"
    }

    static let empty = DashboardTariff(
        importCentsPerKWh: nil, feedInCentsPerKWh: nil, feedInForecast: []
    )
}

struct DashboardTemperature: Codable, Identifiable, Equatable, Sendable {
    let id: String
    let label: String
    let temperatureCelsius: Double?

    enum CodingKeys: String, CodingKey {
        case id, label
        case temperatureCelsius = "temperature_c"
    }
}

struct DashboardHistoryPoint: Codable, Identifiable, Equatable, Sendable {
    let at: String
    let value: Double
    var id: String { at }
}

struct DashboardHistorySeries: Codable, Identifiable, Equatable, Sendable {
    let id: String
    let label: String
    let color: String
    let unit: String
    let points: [DashboardHistoryPoint]
}

struct DashboardHistory: Codable, Equatable, Sendable {
    let periodHours: Int
    let series: [DashboardHistorySeries]

    enum CodingKeys: String, CodingKey {
        case series
        case periodHours = "period_hours"
    }

    static let empty = DashboardHistory(periodHours: 24, series: [])
}

struct DashboardForecast: Codable, Identifiable, Equatable, Sendable {
    let at: String?
    let condition: String?
    let highTemperatureCelsius: Double?
    let lowTemperatureCelsius: Double?
    let precipitationProbability: Double?
    var id: String { at ?? condition ?? "forecast" }

    enum CodingKeys: String, CodingKey {
        case at, condition
        case highTemperatureCelsius = "high_temperature_c"
        case lowTemperatureCelsius = "low_temperature_c"
        case precipitationProbability = "precipitation_probability"
    }
}

struct DashboardWeather: Codable, Equatable, Sendable {
    let status: String
    let condition: String?
    let temperatureCelsius: Double?
    let apparentTemperatureCelsius: Double?
    let humidityPercent: Double?
    let windSpeed: Double?
    let windSpeedUnit: String?
    let forecast: [DashboardForecast]

    enum CodingKeys: String, CodingKey {
        case status, condition, forecast
        case temperatureCelsius = "temperature_c"
        case apparentTemperatureCelsius = "apparent_temperature_c"
        case humidityPercent = "humidity_percent"
        case windSpeed = "wind_speed"
        case windSpeedUnit = "wind_speed_unit"
    }

    static let empty = DashboardWeather(
        status: "unavailable", condition: nil, temperatureCelsius: nil,
        apparentTemperatureCelsius: nil, humidityPercent: nil,
        windSpeed: nil, windSpeedUnit: nil, forecast: []
    )
}

struct DashboardChargingMode: Codable, Equatable, Sendable {
    let value: String?
    let options: [String]
    let available: Bool
}

struct DashboardMediaRoomMode: Codable, Equatable, Sendable {
    let available: Bool
}

struct DashboardControls: Codable, Equatable, Sendable {
    let chargingMode: DashboardChargingMode
    let mediaRoomMode: DashboardMediaRoomMode

    enum CodingKeys: String, CodingKey {
        case chargingMode = "tesla_charging_mode"
        case mediaRoomMode = "media_room_mode"
    }

    static let empty = DashboardControls(
        chargingMode: DashboardChargingMode(value: nil, options: [], available: false),
        mediaRoomMode: DashboardMediaRoomMode(available: false)
    )
}

struct EnergyMeasurement: Codable, Sendable {
    let value: Double?
    let unit: String?
    let observedAt: String?
    let direction: String?

    enum CodingKeys: String, CodingKey {
        case value, unit, direction
        case observedAt = "observed_at"
    }

    var observedDate: Date? {
        guard let observedAt else { return nil }
        return ISO8601DateFormatter().date(from: observedAt)
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
    var positionSeconds: Double? = nil
    var muted: Bool? = nil
    var shuffle: Bool? = nil
    var repeatMode: String? = nil

    enum CodingKeys: String, CodingKey {
        case action, volume, source
        case playerID = "player_id"
        case mediaURI = "media_uri"
        case targetRoomID = "target_room_id"
        case targetPlayerID = "target_player_id"
        case positionSeconds = "position_seconds"
        case repeatMode = "repeat_mode"
        case muted, shuffle
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

    var string: String? {
        if case let .string(value) = self { value } else { nil }
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
    let presentation: HomeEntityPresentation?

    enum CodingKeys: String, CodingKey {
        case domain, name, state, attributes, availability, unavailable, stale, actions, presentation
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

    var displayName: String { presentation?.displayName ?? name }
    var displayActions: [String] { presentation?.supportedActions ?? actions }
    var displayPriority: Int { presentation?.priority ?? 100 }
    var displaySection: String { presentation?.section ?? domain }
    var shouldDisplay: Bool { presentation?.included ?? true }
}

struct HomeEntityPresentation: Codable, Hashable, Sendable {
    let exposurePolicy: String?
    let included: Bool?
    let reason: String?
    let category: String?
    let priority: Int?
    let room: HomeRoomTrust?
    let supportedActions: [String]?
    let canonicalID: String?
    let duplicateOf: String?
    let displayName: String?
    let icon: String?
    let section: String?

    enum CodingKeys: String, CodingKey {
        case included, reason, category, priority, room, icon, section
        case exposurePolicy = "exposure_policy"
        case supportedActions = "supported_actions"
        case canonicalID = "canonical_id"
        case duplicateOf = "duplicate_of"
        case displayName = "display_name"
    }
}

struct HomeRoomTrust: Codable, Hashable, Sendable {
    let trust: String?
    let authoritative: Bool?
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

struct PendingMeetingRecording: Codable, Identifiable, Hashable, Sendable {
    let id: String
    let meetingID: String
    let title: String
    let recordingPath: String
    var state: State
    var uploadComplete: Bool
    var failureMessage: String?
    var updatedAt: Date

    enum State: String, Codable, Sendable {
        case ready
        case uploading
        case processing
        case failed
    }

    var recordingURL: URL { URL(fileURLWithPath: recordingPath) }
}

struct BootstrapCredentials: Codable, Sendable {
    let deviceID: String
    let deviceToken: String

    enum CodingKeys: String, CodingKey {
        case deviceID = "device_id"
        case deviceToken = "device_token"
    }
}

struct PilotClientManifest: Codable, Sendable {
    let schemaVersion: String
    let coreVersion: String?
    let features: [String: Bool]
    let endpoints: [String: String]

    enum CodingKeys: String, CodingKey {
        case features, endpoints
        case schemaVersion = "schema_version"
        case coreVersion = "core_version"
    }
}

struct PilotClientEvent: Codable, Sendable {
    let id: String?
    let type: String
    let revision: Int?
    let roomID: String?
    let payload: JSONValue?
    let occurredAt: String?

    enum CodingKeys: String, CodingKey {
        case id, type, revision, payload
        case roomID = "room_id"
        case occurredAt = "occurred_at"
    }
}
