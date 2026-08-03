import Foundation

public struct PilotPairingPayload: Equatable, Sendable {
    public let coreURL: URL
    public let bootstrapToken: String

    public init(coreURL: URL, bootstrapToken: String) {
        self.coreURL = coreURL
        self.bootstrapToken = bootstrapToken
    }

    public static func parse(
        _ rawValue: String,
        defaultCoreURL: URL? = nil,
        allowsInsecureHTTP: Bool = false
    ) throws -> PilotPairingPayload {
        let value = rawValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !value.isEmpty else { throw PilotClientError.invalidPairingCode }
        var core: String?
        var token: String?
        if let data = value.data(using: .utf8),
           let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            core = (object["core_url"] ?? object["core"]) as? String
            token = (object["bootstrap_token"] ?? object["token"]) as? String
        } else if let components = URLComponents(string: value), components.scheme == "pilot" {
            let values = Dictionary(
                uniqueKeysWithValues: (components.queryItems ?? []).map {
                    ($0.name, $0.value ?? "")
                }
            )
            core = values["core_url"] ?? values["core"]
            token = values["bootstrap_token"] ?? values["token"] ?? values["code"]
        } else if let defaultCoreURL, !value.contains(where: \.isWhitespace) {
            core = defaultCoreURL.absoluteString
            token = value
        }
        guard let core, let token, !token.isEmpty, let coreURL = URL(string: core) else {
            throw PilotClientError.invalidPairingCode
        }
        try PilotTransport.validate(coreURL: coreURL, allowsInsecureHTTP: allowsInsecureHTTP)
        return PilotPairingPayload(coreURL: coreURL, bootstrapToken: token)
    }
}
