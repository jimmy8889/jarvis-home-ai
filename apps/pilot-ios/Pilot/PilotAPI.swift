import Foundation

struct PilotAPI: Sendable {
    let coreURL: URL
    let deviceID: String
    let token: String

    private func request(
        path: String,
        method: String = "GET",
        body: Data? = nil
    ) async throws -> Data {
        let url = coreURL.appending(path: path)
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.httpBody = body
        request.timeoutInterval = 70
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.setValue(deviceID, forHTTPHeaderField: "X-Pilot-Device-ID")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if body != nil {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            let detail = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["detail"]
            throw PilotAPIError.server(detail as? String ?? "Pilot Core request failed")
        }
        return data
    }

    func media() async throws -> DeviceMediaEnvelope {
        let data = try await request(path: "v1/devices/\(deviceID)/media")
        return try JSONDecoder().decode(DeviceMediaEnvelope.self, from: data)
    }

    func send(_ command: MediaCommand) async throws {
        let body = try JSONEncoder().encode(command)
        _ = try await request(
            path: "v1/devices/\(deviceID)/media",
            method: "POST",
            body: body
        )
    }

    func search(_ query: String) async throws -> [MusicSearchResult] {
        let body = try JSONSerialization.data(withJSONObject: [
            "query": query,
            "limit": 20,
            "library_only": false,
        ])
        let data = try await request(
            path: "v1/devices/\(deviceID)/media/search",
            method: "POST",
            body: body
        )
        let object = try JSONSerialization.jsonObject(with: data)
        return Self.flattenSearch(object)
    }

    func ask(
        _ text: String,
        roomID: String,
        conversationID: String?
    ) async throws -> AssistantReply {
        var payload: [String: Any] = [
            "text": text,
            "language": "en-AU",
            "room_id": roomID,
        ]
        if let conversationID {
            payload["conversation_id"] = conversationID
        }
        let body = try JSONSerialization.data(withJSONObject: payload)
        let data = try await request(
            path: "v1/devices/\(deviceID)/assistant",
            method: "POST",
            body: body
        )
        return try JSONDecoder().decode(AssistantReply.self, from: data)
    }

    static func flattenSearch(_ object: Any) -> [MusicSearchResult] {
        var output: [MusicSearchResult] = []
        func visit(_ value: Any) {
            if let values = value as? [Any] {
                values.forEach(visit)
                return
            }
            guard let row = value as? [String: Any] else { return }
            if let uri = (row["uri"] ?? row["media_uri"]) as? String,
               let title = (row["name"] ?? row["title"]) as? String {
                output.append(
                    MusicSearchResult(
                        id: uri,
                        title: title,
                        subtitle: (row["artist"] ?? row["album"] ?? row["media_type"]) as? String ?? "",
                        uri: uri
                    )
                )
                return
            }
            row.values.forEach(visit)
        }
        visit(object)
        return Array(output.prefix(40))
    }
}

enum PilotAPIError: LocalizedError {
    case notConfigured
    case invalidURL
    case server(String)

    var errorDescription: String? {
        switch self {
        case .notConfigured: "Pilot is not configured."
        case .invalidURL: "The Pilot Core URL is invalid."
        case let .server(detail): detail
        }
    }
}
