import Foundation

public final class PilotTransport: @unchecked Sendable {
    public let credentials: PilotCredentials
    public let allowsInsecureHTTP: Bool
    private let session: URLSession

    public init(
        credentials: PilotCredentials,
        allowsInsecureHTTP: Bool = false,
        session: URLSession = .shared
    ) throws {
        try Self.validate(
            coreURL: credentials.coreURL,
            allowsInsecureHTTP: allowsInsecureHTTP
        )
        self.credentials = credentials
        self.allowsInsecureHTTP = allowsInsecureHTTP
        self.session = session
    }

    public static func validate(coreURL: URL, allowsInsecureHTTP: Bool) throws {
        guard coreURL.host != nil,
              coreURL.user == nil,
              coreURL.password == nil,
              coreURL.fragment == nil
        else { throw PilotClientError.invalidURL }
        if coreURL.scheme == "https" { return }
        if allowsInsecureHTTP && coreURL.scheme == "http" { return }
        throw PilotClientError.insecureTransport
    }

    public func data(
        path: String,
        method: String = "GET",
        body: Data? = nil,
        queryItems: [URLQueryItem] = [],
        contentType: String? = nil,
        timeout: TimeInterval = 70
    ) async throws -> Data {
        guard !path.contains(".."), !path.contains("://") else {
            throw PilotClientError.invalidURL
        }
        var components = URLComponents(
            url: credentials.coreURL.appending(path: path),
            resolvingAgainstBaseURL: false
        )
        if !queryItems.isEmpty { components?.queryItems = queryItems }
        guard let url = components?.url else { throw PilotClientError.invalidURL }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.httpBody = body
        request.timeoutInterval = timeout
        request.setValue(
            "Bearer \(credentials.deviceToken)",
            forHTTPHeaderField: "Authorization"
        )
        request.setValue(credentials.deviceID, forHTTPHeaderField: "X-Pilot-Device-ID")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if let contentType { request.setValue(contentType, forHTTPHeaderField: "Content-Type") }
        else if body != nil { request.setValue("application/json", forHTTPHeaderField: "Content-Type") }
        let (data, response) = try await session.data(for: request)
        try Self.validate(response: response, data: data)
        return data
    }

    public func decode<T: Decodable & Sendable>(
        _ type: T.Type,
        path: String,
        method: String = "GET",
        body: Data? = nil,
        queryItems: [URLQueryItem] = []
    ) async throws -> T {
        let data = try await data(
            path: path, method: method, body: body, queryItems: queryItems
        )
        return try JSONDecoder().decode(type, from: data)
    }

    public func manifest() async throws -> PilotClientManifest {
        try await decode(
            PilotClientManifest.self,
            path: "v1/devices/\(credentials.deviceID)/manifest"
        )
    }

    public func eventSnapshot(after cursor: String?) async throws -> PilotEventSnapshot {
        try await decode(
            PilotEventSnapshot.self,
            path: "v1/devices/\(credentials.deviceID)/events/snapshot",
            queryItems: cursor.map { [URLQueryItem(name: "cursor", value: $0)] } ?? []
        )
    }

    public func pollEvents(after cursor: String?) async throws -> PilotEventSnapshot {
        var items = [URLQueryItem(name: "timeout_seconds", value: "25")]
        if let cursor, !cursor.isEmpty { items.append(URLQueryItem(name: "cursor", value: cursor)) }
        return try await decode(
            PilotEventSnapshot.self,
            path: "v1/devices/\(credentials.deviceID)/events",
            queryItems: items
        )
    }

    public func rotateCredentials() async throws -> PilotCredentials {
        let rotation = try await decode(
            PilotCredentialRotation.self,
            path: "v1/devices/\(credentials.deviceID)/credentials/rotate-self",
            method: "POST",
            body: Data()
        )
        return PilotCredentials(
            coreURL: credentials.coreURL,
            deviceID: rotation.deviceID,
            deviceToken: rotation.deviceToken,
            credentialRevision: rotation.credentialRevision
        )
    }

    public static func redeem(
        _ payload: PilotPairingPayload,
        allowsInsecureHTTP: Bool = false,
        session: URLSession = .shared
    ) async throws -> PilotCredentials {
        try validate(coreURL: payload.coreURL, allowsInsecureHTTP: allowsInsecureHTTP)
        var request = URLRequest(url: payload.coreURL.appending(path: "v1/devices/bootstrap"))
        request.httpMethod = "POST"
        request.timeoutInterval = 30
        request.setValue(
            "Bearer \(payload.bootstrapToken)",
            forHTTPHeaderField: "Authorization"
        )
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        let (data, response) = try await session.data(for: request)
        try validate(response: response, data: data)
        let bootstrap = try JSONDecoder().decode(PilotBootstrapCredentials.self, from: data)
        return PilotCredentials(
            coreURL: payload.coreURL,
            deviceID: bootstrap.deviceID,
            deviceToken: bootstrap.deviceToken
        )
    }

    static func validate(response: URLResponse, data: Data) throws {
        guard let response = response as? HTTPURLResponse else {
            throw PilotClientError.invalidResponse
        }
        guard (200..<300).contains(response.statusCode) else {
            let detail = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["detail"] as? String
                ?? "Pilot Core returned HTTP \(response.statusCode)."
            if response.statusCode == 401 || response.statusCode == 403 {
                throw PilotClientError.authentication(detail)
            }
            throw PilotClientError.server(status: response.statusCode, detail: detail)
        }
    }
}
