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

    func manifest() async throws -> PilotClientManifest {
        let data = try await request(path: "v1/devices/\(deviceID)/manifest")
        return try JSONDecoder().decode(PilotClientManifest.self, from: data)
    }

    func energy() async throws -> EnergySnapshot {
        let data = try await request(path: "v1/devices/\(deviceID)/energy")
        if let direct = try? JSONDecoder().decode(EnergyEnvelope.self, from: data) {
            return direct.snapshot
        }
        let object = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        guard
            let energy = object?["energy"],
            JSONSerialization.isValidJSONObject(energy)
        else { throw PilotAPIError.invalidResponse }
        let nested = try JSONSerialization.data(withJSONObject: energy)
        return try JSONDecoder().decode(EnergyEnvelope.self, from: nested).snapshot
    }

    func dashboard() async throws -> DashboardSnapshot {
        let data = try await request(path: "v1/devices/\(deviceID)/dashboard")
        return try JSONDecoder().decode(DashboardSnapshot.self, from: data)
    }

    func dashboardAction(_ action: String, value: String) async throws {
        let body = try JSONSerialization.data(withJSONObject: [
            "action": action,
            "value": value,
        ])
        _ = try await request(
            path: "v1/devices/\(deviceID)/dashboard/actions",
            method: "POST",
            body: body
        )
    }

    func surfaceEnergy() async throws -> EnergySnapshot {
        let data = try await request(path: "v1/devices/\(deviceID)/surface")
        let object = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        guard
            let energy = object?["energy"],
            JSONSerialization.isValidJSONObject(energy)
        else { throw PilotAPIError.invalidResponse }
        let nested = try JSONSerialization.data(withJSONObject: energy)
        return try JSONDecoder().decode(EnergyEnvelope.self, from: nested).snapshot
    }

    static func redeemBootstrap(
        token bootstrapToken: String,
        coreURL: URL
    ) async throws -> BootstrapCredentials {
        let url = coreURL.appending(path: "v1/devices/bootstrap")
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.timeoutInterval = 30
        request.setValue("Bearer \(bootstrapToken)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        let (data, response) = try await URLSession.shared.data(for: request)
        try validate(response, data: data)
        return try JSONDecoder().decode(BootstrapCredentials.self, from: data)
    }

    func eventSnapshot(after cursor: String?) async throws -> ClientEventSnapshot {
        var components = URLComponents(
            url: coreURL.appending(path: "v1/devices/\(deviceID)/events/snapshot"),
            resolvingAgainstBaseURL: false
        )
        if let cursor, !cursor.isEmpty {
            components?.queryItems = [URLQueryItem(name: "cursor", value: cursor)]
        }
        guard let url = components?.url else { throw PilotAPIError.invalidURL }
        var eventRequest = URLRequest(url: url)
        eventRequest.timeoutInterval = 30
        eventRequest.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        eventRequest.setValue(deviceID, forHTTPHeaderField: "X-Pilot-Device-ID")
        let (data, response) = try await URLSession.shared.data(for: eventRequest)
        try Self.validate(response, data: data)
        return try JSONDecoder().decode(ClientEventSnapshot.self, from: data)
    }

    func pollEvents(after cursor: String?) async throws -> ClientEventSnapshot {
        var components = URLComponents(
            url: coreURL.appending(path: "v1/devices/\(deviceID)/events"),
            resolvingAgainstBaseURL: false
        )
        var query = [URLQueryItem(name: "timeout_seconds", value: "25")]
        if let cursor, !cursor.isEmpty {
            query.append(URLQueryItem(name: "cursor", value: cursor))
        }
        components?.queryItems = query
        guard let url = components?.url else { throw PilotAPIError.invalidURL }
        var eventRequest = URLRequest(url: url)
        eventRequest.timeoutInterval = 35
        eventRequest.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        eventRequest.setValue(deviceID, forHTTPHeaderField: "X-Pilot-Device-ID")
        let (data, response) = try await URLSession.shared.data(for: eventRequest)
        try Self.validate(response, data: data)
        return try JSONDecoder().decode(ClientEventSnapshot.self, from: data)
    }

    func receiveEvents(
        after cursor: String?,
        handler: @escaping @MainActor @Sendable (PilotClientEvent) async -> Void
    ) async throws {
        var components = URLComponents(
            url: coreURL.appending(path: "v1/devices/\(deviceID)/events/ws"),
            resolvingAgainstBaseURL: false
        )
        if let cursor, !cursor.isEmpty {
            components?.queryItems = [URLQueryItem(name: "cursor", value: cursor)]
        }
        guard var url = components?.url else { throw PilotAPIError.invalidURL }
        if url.scheme == "http" {
            var replaced = URLComponents(url: url, resolvingAgainstBaseURL: false)
            replaced?.scheme = "ws"
            if let websocketURL = replaced?.url { url = websocketURL }
        } else if url.scheme == "https" {
            var replaced = URLComponents(url: url, resolvingAgainstBaseURL: false)
            replaced?.scheme = "wss"
            if let websocketURL = replaced?.url { url = websocketURL }
        }
        var eventRequest = URLRequest(url: url)
        eventRequest.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        eventRequest.setValue(deviceID, forHTTPHeaderField: "X-Pilot-Device-ID")
        let socket = URLSession.shared.webSocketTask(with: eventRequest)
        socket.resume()
        try await withTaskCancellationHandler {
            while !Task.isCancelled {
                let message = try await socket.receive()
                let data: Data
                switch message {
                case let .data(value): data = value
                case let .string(value): data = Data(value.utf8)
                @unknown default: continue
                }
                let event = try JSONDecoder().decode(PilotClientEvent.self, from: data)
                await handler(event)
            }
        } onCancel: {
            socket.cancel(with: .goingAway, reason: nil)
        }
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

    func sendToLocalPlayer(_ command: MediaCommand) async throws {
        let body = try JSONEncoder().encode(command)
        _ = try await request(
            path: "v1/devices/\(deviceID)/media/local",
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

    func browse(_ result: MusicSearchResult) async throws -> MusicBrowsePage {
        let body = try JSONSerialization.data(withJSONObject: [
            "uri": result.uri,
            "media_type": result.kind.rawValue,
        ])
        let data = try await request(
            path: "v1/devices/\(deviceID)/media/browse",
            method: "POST",
            body: body
        )
        guard let root = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { throw PilotAPIError.invalidResponse }
        let resolved = root["item"].flatMap { Self.flattenSearch($0).first } ?? result
        let sections: [MusicBrowseSection] = (root["sections"] as? [[String: Any]] ?? []).compactMap { section -> MusicBrowseSection? in
            guard let id = section["id"] as? String else { return nil }
            return MusicBrowseSection(
                id: id,
                title: section["title"] as? String ?? id.capitalized,
                items: Self.flattenSearch(section["items"] as Any)
            )
        }
        return MusicBrowsePage(item: resolved, sections: sections)
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

    func meeting(_ meetingID: String) async throws -> PilotMeetingDetail {
        let data = try await request(
            path: "v1/devices/\(deviceID)/meetings/\(meetingID)"
        )
        return try JSONDecoder().decode(PilotMeetingDetail.self, from: data)
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

struct ClientEventSnapshot: Codable, Sendable {
    let schemaVersion: String?
    let cursor: String?
    let revision: Int?
    let resetRequired: Bool?
    let resyncRequired: Bool?
    let events: [PilotClientEvent]

    enum CodingKeys: String, CodingKey {
        case cursor, revision, events
        case schemaVersion = "schema_version"
        case resetRequired = "reset_required"
        case resyncRequired = "resync_required"
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
