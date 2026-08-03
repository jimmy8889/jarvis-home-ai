import Foundation

public struct PilotCredentials: Codable, Equatable, Sendable {
    public let coreURL: URL
    public let deviceID: String
    public let deviceToken: String
    public let credentialRevision: Int?

    public init(
        coreURL: URL,
        deviceID: String,
        deviceToken: String,
        credentialRevision: Int? = nil
    ) {
        self.coreURL = coreURL
        self.deviceID = deviceID
        self.deviceToken = deviceToken
        self.credentialRevision = credentialRevision
    }
}

public struct PilotCredentialBundle: Codable, Equatable, Sendable {
    public let schemaVersion: String
    public let coreURL: URL
    public let deviceID: String
    public let deviceToken: String

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case coreURL = "core_url"
        case deviceID = "device_id"
        case deviceToken = "device_token"
    }

    public static func parse(
        _ rawValue: String,
        allowsInsecureHTTP: Bool = false
    ) throws -> PilotCredentials {
        let value = rawValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let data = value.data(using: .utf8),
              let bundle = try? JSONDecoder().decode(Self.self, from: data),
              bundle.schemaVersion == "pilot.credentials.v1",
              !bundle.deviceID.isEmpty,
              !bundle.deviceToken.isEmpty else {
            throw PilotClientError.invalidPairingCode
        }
        try PilotTransport.validate(
            coreURL: bundle.coreURL,
            allowsInsecureHTTP: allowsInsecureHTTP
        )
        return PilotCredentials(
            coreURL: bundle.coreURL,
            deviceID: bundle.deviceID,
            deviceToken: bundle.deviceToken
        )
    }
}

public struct PilotBootstrapCredentials: Codable, Equatable, Sendable {
    public let deviceID: String
    public let deviceToken: String

    enum CodingKeys: String, CodingKey {
        case deviceID = "device_id"
        case deviceToken = "device_token"
    }
}

public struct PilotCredentialRotation: Codable, Equatable, Sendable {
    public let deviceID: String
    public let deviceToken: String
    public let credentialRevision: Int
    public let rotatedAt: String

    enum CodingKeys: String, CodingKey {
        case deviceID = "device_id"
        case deviceToken = "device_token"
        case credentialRevision = "credential_revision"
        case rotatedAt = "rotated_at"
    }
}

public struct PilotClientManifest: Codable, Equatable, Sendable {
    public let schemaVersion: String
    public let coreVersion: String?
    public let features: [String: Bool]
    public let endpoints: [String: String]

    enum CodingKeys: String, CodingKey {
        case features, endpoints
        case schemaVersion = "schema_version"
        case coreVersion = "core_version"
    }
}

public struct PilotClientEvent: Codable, Equatable, Sendable {
    public let id: String?
    public let type: String
    public let revision: Int?
    public let roomID: String?
    public let payload: PilotJSONValue?
    public let occurredAt: String?

    enum CodingKeys: String, CodingKey {
        case id, type, revision, payload
        case roomID = "room_id"
        case occurredAt = "occurred_at"
    }
}

public struct PilotEventSnapshot: Codable, Equatable, Sendable {
    public let schemaVersion: String?
    public let cursor: String?
    public let revision: Int?
    public let resetRequired: Bool?
    public let resyncRequired: Bool?
    public let events: [PilotClientEvent]

    enum CodingKeys: String, CodingKey {
        case cursor, revision, events
        case schemaVersion = "schema_version"
        case resetRequired = "reset_required"
        case resyncRequired = "resync_required"
    }
}

public enum PilotJSONValue: Codable, Equatable, Sendable {
    case string(String)
    case number(Double)
    case boolean(Bool)
    case object([String: PilotJSONValue])
    case array([PilotJSONValue])
    case null

    public init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() { self = .null }
        else if let value = try? container.decode(Bool.self) { self = .boolean(value) }
        else if let value = try? container.decode(Double.self) { self = .number(value) }
        else if let value = try? container.decode(String.self) { self = .string(value) }
        else if let value = try? container.decode([String: PilotJSONValue].self) {
            self = .object(value)
        } else { self = .array(try container.decode([PilotJSONValue].self)) }
    }

    public func encode(to encoder: Encoder) throws {
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
}

public enum PilotClientError: LocalizedError, Equatable {
    case invalidURL
    case insecureTransport
    case invalidPairingCode
    case invalidResponse
    case authentication(String)
    case server(status: Int, detail: String)
    case keychain(OSStatus)

    public var errorDescription: String? {
        switch self {
        case .invalidURL: "The Pilot Core URL is invalid."
        case .insecureTransport: "Pilot Drive requires a trusted HTTPS Pilot Core URL."
        case .invalidPairingCode: "That Pilot pairing code is invalid."
        case .invalidResponse: "Pilot Core returned an invalid response."
        case let .authentication(detail): detail
        case let .server(_, detail): detail
        case let .keychain(status): "Keychain returned status \(status)."
        }
    }
}
