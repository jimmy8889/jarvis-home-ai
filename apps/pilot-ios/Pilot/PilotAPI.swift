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
        guard let http = response as? HTTPURLResponse else {
            throw PilotAPIError.invalidResponse
        }
        guard (200..<300).contains(http.statusCode) else {
            let detail = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["detail"]
            if http.statusCode == 401 || http.statusCode == 403 {
                throw PilotAPIError.authentication(
                    detail as? String ?? "This Pilot device credential was rejected."
                )
            }
            throw PilotAPIError.server(
                detail as? String ?? "Pilot Core returned HTTP \(http.statusCode)."
            )
        }
        return data
    }

    func media() async throws -> DeviceMediaEnvelope {
        let data = try await request(path: "v1/devices/\(deviceID)/media")
        return try JSONDecoder().decode(DeviceMediaEnvelope.self, from: data)
    }

    func home(roomID: String) async throws -> HomeProjection {
        var components = URLComponents(
            url: coreURL.appending(path: "v1/devices/\(deviceID)/home"),
            resolvingAgainstBaseURL: false
        )
        components?.queryItems = [URLQueryItem(name: "room_id", value: roomID)]
        guard let url = components?.url else { throw PilotAPIError.invalidURL }
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.timeoutInterval = 30
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.setValue(deviceID, forHTTPHeaderField: "X-Pilot-Device-ID")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        let (data, response) = try await URLSession.shared.data(for: request)
        try Self.validate(response, data: data)
        return try JSONDecoder().decode(HomeProjection.self, from: data)
    }

    func homeAction(_ command: HomeActionRequest) async throws -> HomeActionEnvelope {
        let body = try JSONEncoder().encode(command)
        let data = try await request(
            path: "v1/devices/\(deviceID)/home/actions",
            method: "POST",
            body: body
        )
        return try JSONDecoder().decode(HomeActionEnvelope.self, from: data)
    }

    func confirmHomeAction(_ actionID: String) async throws -> HomeActionEnvelope {
        let data = try await request(
            path: "v1/devices/\(deviceID)/home/actions/\(actionID)/confirm",
            method: "POST",
            body: Data()
        )
        return try JSONDecoder().decode(HomeActionEnvelope.self, from: data)
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

    func meetings() async throws -> [PilotMeeting] {
        let data = try await request(path: "v1/devices/\(deviceID)/meetings")
        return try JSONDecoder().decode(MeetingEnvelope.self, from: data).meetings
    }

    func createMeeting(title: String) async throws -> PilotMeeting {
        let body = try JSONSerialization.data(withJSONObject: [
            "title": title,
            "language": "en-AU",
        ])
        let data = try await request(
            path: "v1/devices/\(deviceID)/meetings",
            method: "POST",
            body: body
        )
        return try JSONDecoder().decode(PilotMeeting.self, from: data)
    }

    func uploadMeetingRecording(
        meetingID: String,
        recordingURL: URL
    ) async throws {
        let url = coreURL.appending(
            path: "v1/devices/\(deviceID)/meetings/\(meetingID)/recording"
        )
        var request = URLRequest(url: url)
        request.httpMethod = "PUT"
        request.timeoutInterval = 600
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.setValue(deviceID, forHTTPHeaderField: "X-Pilot-Device-ID")
        request.setValue(recordingURL.lastPathComponent, forHTTPHeaderField: "X-Pilot-Filename")
        request.setValue("audio/m4a", forHTTPHeaderField: "Content-Type")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        let (data, response) = try await URLSession.shared.upload(
            for: request,
            fromFile: recordingURL
        )
        try Self.validate(response, data: data)
    }

    func processMeeting(_ meetingID: String) async throws -> PilotMeeting {
        let data = try await request(
            path: "v1/devices/\(deviceID)/meetings/\(meetingID)/process",
            method: "POST",
            body: Data()
        )
        return try JSONDecoder().decode(MeetingProcessEnvelope.self, from: data).meeting
    }

    static func flattenSearch(_ object: Any) -> [MusicSearchResult] {
        var output: [MusicSearchResult] = []
        var seen = Set<String>()

        func inferredKind(_ value: Any?, fallback: MusicResultKind) -> MusicResultKind {
            guard let raw = value as? String else { return fallback }
            let normalized = raw.lowercased()
            if normalized.contains("track") || normalized.contains("song") { return .track }
            if normalized.contains("album") { return .album }
            if normalized.contains("artist") { return .artist }
            if normalized.contains("playlist") { return .playlist }
            if normalized.contains("radio") { return .radio }
            return fallback
        }

        func containerKind(_ key: String) -> MusicResultKind {
            inferredKind(key, fallback: .other)
        }

        func visit(_ value: Any, kind: MusicResultKind = .other) {
            if let values = value as? [Any] {
                values.forEach { visit($0, kind: kind) }
                return
            }
            guard let row = value as? [String: Any] else { return }
            if let uri = (row["uri"] ?? row["media_uri"]) as? String,
               let title = (row["name"] ?? row["title"]) as? String,
               seen.insert(uri).inserted {
                let artwork = (
                    row["image_url"]
                    ?? row["artwork_url"]
                    ?? row["thumbnail"]
                ) as? String
                output.append(
                    MusicSearchResult(
                        id: uri,
                        title: title,
                        subtitle: (row["artist"] ?? row["album"] ?? row["media_type"]) as? String ?? "",
                        uri: uri,
                        kind: inferredKind(row["media_type"] ?? row["type"], fallback: kind),
                        artworkURL: artwork.flatMap(URL.init(string:))
                    )
                )
                return
            }
            row.forEach { key, value in
                visit(value, kind: containerKind(key))
            }
        }
        visit(object)
        return Array(output.prefix(40))
    }

    private static func validate(_ response: URLResponse, data: Data) throws {
        guard let http = response as? HTTPURLResponse else {
            throw PilotAPIError.invalidResponse
        }
        guard (200..<300).contains(http.statusCode) else {
            let detail = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["detail"]
            if http.statusCode == 401 || http.statusCode == 403 {
                throw PilotAPIError.authentication(
                    detail as? String ?? "This Pilot device credential was rejected."
                )
            }
            throw PilotAPIError.server(
                detail as? String ?? "Pilot Core returned HTTP \(http.statusCode)."
            )
        }
    }
}

enum PilotAPIError: LocalizedError {
    case notConfigured
    case invalidURL
    case invalidResponse
    case authentication(String)
    case server(String)

    var errorDescription: String? {
        switch self {
        case .notConfigured: "Pilot is not configured."
        case .invalidURL: "The Pilot Core URL is invalid."
        case .invalidResponse: "Pilot Core returned an invalid response."
        case let .authentication(detail): detail
        case let .server(detail): detail
        }
    }
}
