import AVFoundation
import Foundation
import Observation
import SendspinKit

@MainActor
@Observable
final class PhonePlaybackController {
    enum Status: Equatable {
        case idle
        case connecting
        case connected
        case streaming
        case failed(String)

        var label: String {
            switch self {
            case .idle: "Ready"
            case .connecting: "Connecting"
            case .connected: "Connected"
            case .streaming: "Playing on this iPhone"
            case let .failed(message): message
            }
        }
    }

    private(set) var status: Status = .idle
    private(set) var title: String?
    private(set) var artist: String?
    private(set) var album: String?
    private(set) var artworkURL: URL?
    private(set) var isPlaying = false
    private(set) var volume = 100
    private(set) var muted = false
    private(set) var positionSeconds = 0.0
    private(set) var durationSeconds = 0.0

    @ObservationIgnored private var client: SendspinClient?
    @ObservationIgnored private var eventsTask: Task<Void, Never>?
    @ObservationIgnored private var progressTask: Task<Void, Never>?
    @ObservationIgnored private var activeIdentity: String?
    @ObservationIgnored private var activeServerURL: URL?

    var hasMedia: Bool { title != nil || isPlaying }
    var isReady: Bool {
        switch status {
        case .connected, .streaming: true
        default: false
        }
    }

    @discardableResult
    func connect(serverURL: String, deviceID: String) async -> Bool {
        let identity = "pilot-native-\(deviceID)"
        let targetURL: URL
        do {
            targetURL = try Self.normalizedSendspinURL(from: serverURL)
        } catch {
            status = .failed("Enter a valid Sendspin endpoint")
            return false
        }
        if activeIdentity == identity,
           activeServerURL == targetURL,
           client != nil {
            if isReady { return true }
            if status == .connecting { return await waitForRegistration() }
        }
        await disconnect()
        status = .connecting

        do {
            try configureAudioSession()
            let formats = [
                try AudioFormatSpec(codec: .opus, channels: 2, sampleRate: 48_000, bitDepth: 16),
                try AudioFormatSpec(codec: .flac, channels: 2, sampleRate: 48_000, bitDepth: 16),
                try AudioFormatSpec(codec: .pcm, channels: 2, sampleRate: 48_000, bitDepth: 16),
            ]
            let configuration = try PlayerConfiguration(
                bufferCapacity: 2_097_152,
                supportedFormats: formats,
                initialStaticDelayMs: UserDefaults.standard.integer(
                    forKey: "pilot.sendspin.staticDelayMs"
                ),
                volumeMode: .software
            )
            let player = try SendspinClient(
                clientId: identity,
                name: "Pilot · This iPhone",
                roles: [.playerV1, .metadataV1, .controllerV1],
                playerConfig: configuration
            )
            client = player
            activeIdentity = identity
            activeServerURL = targetURL
            observe(player)
            try await player.connect(to: targetURL)
            guard await waitForRegistration() else {
                throw ConnectionError.registrationTimedOut
            }
            // Music Assistant publishes the newly registered player into its
            // queue registry asynchronously. Give that bounded hand-off a
            // moment before Pilot Core sends the first play command.
            try await Task.sleep(for: .milliseconds(250))
            return true
        } catch {
            let message = Self.message(error)
            await tearDown(clearPlayback: false)
            status = .failed(message)
            return false
        }
    }

    func disconnect() async {
        await tearDown(clearPlayback: true)
        status = .idle
    }

    private func tearDown(clearPlayback: Bool) async {
        eventsTask?.cancel()
        progressTask?.cancel()
        eventsTask = nil
        progressTask = nil
        if let client { await client.disconnect() }
        client = nil
        activeIdentity = nil
        activeServerURL = nil
        isPlaying = false
        if clearPlayback {
            title = nil
            artist = nil
            album = nil
            artworkURL = nil
            positionSeconds = 0
            durationSeconds = 0
        }
    }

    private func observe(_ player: SendspinClient) {
        eventsTask = Task { [weak self] in
            for await event in player.events {
                guard let self, !Task.isCancelled else { return }
                switch event {
                case .serverConnected:
                    status = .connected
                case .streamStarted, .streamFormatChanged:
                    isPlaying = true
                    status = .streaming
                case .streamEnded:
                    isPlaying = false
                    status = .connected
                case let .metadataReceived(metadata):
                    title = metadata.title
                    artist = metadata.artist
                    album = metadata.album
                    artworkURL = metadata.artworkURL.flatMap(URL.init(string:))
                    updateProgress(metadata.progress)
                case let .groupUpdated(group):
                    isPlaying = group.playbackState == .playing
                    status = isPlaying ? .streaming : .connected
                case let .controllerStateUpdated(controller):
                    volume = controller.volume
                    muted = controller.muted
                case let .staticDelayChanged(milliseconds):
                    UserDefaults.standard.set(
                        milliseconds,
                        forKey: "pilot.sendspin.staticDelayMs"
                    )
                case .disconnected:
                    isPlaying = false
                    status = .idle
                    client = nil
                    activeIdentity = nil
                    activeServerURL = nil
                default:
                    break
                }
            }
        }
        progressTask = Task { [weak self] in
            while !Task.isCancelled {
                guard let self else { return }
                if let progress = player.currentMetadata?.progress,
                   let now = await player.currentServerTimeMicroseconds() {
                    positionSeconds = Double(progress.currentPositionMs(at: now)) / 1_000
                    durationSeconds = Double(progress.trackDurationMs) / 1_000
                }
                try? await Task.sleep(for: .milliseconds(500))
            }
        }
    }

    private func updateProgress(_ progress: PlaybackProgress?) {
        guard let progress else {
            positionSeconds = 0
            durationSeconds = 0
            return
        }
        positionSeconds = Double(progress.trackProgressMs) / 1_000
        durationSeconds = Double(progress.trackDurationMs) / 1_000
        isPlaying = progress.playbackSpeedX1000 > 0
    }

    private func configureAudioSession() throws {
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.playback, mode: .default, policy: .longFormAudio)
        try session.setActive(true)
    }

    private func waitForRegistration() async -> Bool {
        for _ in 0..<100 {
            if isReady { return true }
            if case .failed = status { return false }
            try? await Task.sleep(for: .milliseconds(50))
        }
        return false
    }

    nonisolated static func normalizedSendspinURL(from value: String) throws -> URL {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        let candidate = trimmed.contains("://") ? trimmed : "ws://\(trimmed)"
        guard !trimmed.isEmpty, var components = URLComponents(string: candidate) else {
            throw URLError(.badURL)
        }
        switch components.scheme?.lowercased() {
        case "https", "wss": components.scheme = "wss"
        case "http", "ws": components.scheme = "ws"
        default: throw URLError(.unsupportedURL)
        }
        guard components.host?.isEmpty == false else { throw URLError(.badURL) }
        // Music Assistant's UI/API commonly runs on 8095 while native
        // Sendspin clients connect to 8927. Migrate the former automatically
        // so existing Pilot installs start working without manual repair.
        if components.port == nil || components.port == 8095 {
            components.port = 8927
        }
        let basePath = components.path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        components.path = basePath.isEmpty || basePath == "sendspin"
            ? "/sendspin" : "/\(basePath)/sendspin"
        components.query = nil
        components.fragment = nil
        guard let url = components.url else { throw URLError(.badURL) }
        return url
    }

    private static func message(_ error: Error) -> String {
        let text = error.localizedDescription.trimmingCharacters(in: .whitespacesAndNewlines)
        return text.isEmpty ? "This iPhone player is unavailable" : text
    }

    private enum ConnectionError: LocalizedError {
        case registrationTimedOut

        var errorDescription: String? {
            "Music Assistant did not register this iPhone. Check the Sendspin endpoint."
        }
    }
}
