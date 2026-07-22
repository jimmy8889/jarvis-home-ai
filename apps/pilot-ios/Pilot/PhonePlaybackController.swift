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

    var hasMedia: Bool { title != nil || isPlaying }

    func connect(baseURL: String, deviceID: String) async {
        let identity = "pilot-native-\(deviceID)"
        guard activeIdentity != identity || client == nil else { return }
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
            observe(player)
            try await player.connect(to: try Self.sendspinURL(from: baseURL))
        } catch {
            status = .failed(Self.message(error))
            client = nil
            activeIdentity = nil
        }
    }

    func disconnect() async {
        eventsTask?.cancel()
        progressTask?.cancel()
        eventsTask = nil
        progressTask = nil
        if let client { await client.disconnect() }
        client = nil
        activeIdentity = nil
        status = .idle
        isPlaying = false
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

    private static func sendspinURL(from value: String) throws -> URL {
        guard var components = URLComponents(string: value) else {
            throw URLError(.badURL)
        }
        components.scheme = components.scheme == "https" ? "wss" : "ws"
        let basePath = components.path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        components.path = basePath.isEmpty ? "/sendspin" : "/\(basePath)/sendspin"
        guard let url = components.url else { throw URLError(.badURL) }
        return url
    }

    private static func message(_ error: Error) -> String {
        let text = error.localizedDescription.trimmingCharacters(in: .whitespacesAndNewlines)
        return text.isEmpty ? "This iPhone player is unavailable" : text
    }
}
