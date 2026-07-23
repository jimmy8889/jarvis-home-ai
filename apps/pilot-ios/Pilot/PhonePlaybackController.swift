import AVFoundation
import Foundation
import MediaPlayer
import Observation
import SendspinKit
import UIKit

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
    private(set) var albumArtist: String?
    private(set) var trackNumber: Int?
    private(set) var artworkURL: URL?
    private(set) var isPlaying = false
    private(set) var volume = 100
    private(set) var muted = false
    private(set) var positionSeconds = 0.0
    private(set) var durationSeconds = 0.0

    @ObservationIgnored private var client: SendspinClient?
    @ObservationIgnored private var eventsTask: Task<Void, Never>?
    @ObservationIgnored private var progressTask: Task<Void, Never>?
    @ObservationIgnored private var artworkTask: Task<Void, Never>?
    @ObservationIgnored private var activeIdentity: String?
    @ObservationIgnored private var activeServerURL: URL?
    @ObservationIgnored private var nowPlayingArtwork: MPMediaItemArtwork?
    @ObservationIgnored private var nowPlayingArtworkURL: URL?
    @ObservationIgnored private var remoteCommandTokens: [Any] = []
    @ObservationIgnored private var mediaIntegrationConfigured = false
    @ObservationIgnored private var supportedControllerCommands:
        Set<ControllerCommandType> = []
    @ObservationIgnored private var remoteCommandHandler:
        (@MainActor @Sendable (String, Double?) async -> Void)?

    var hasMedia: Bool { title != nil || isPlaying }
    var isReady: Bool {
        switch status {
        case .connected, .streaming: true
        default: false
        }
    }

    func setRemoteCommandHandler(
        _ handler: @escaping @MainActor @Sendable (String, Double?) async -> Void
    ) {
        remoteCommandHandler = handler
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
            configureSystemMediaIntegration()
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
        artworkTask?.cancel()
        eventsTask = nil
        progressTask = nil
        artworkTask = nil
        if let client { await client.disconnect() }
        client = nil
        activeIdentity = nil
        activeServerURL = nil
        isPlaying = false
        supportedControllerCommands = []
        if clearPlayback {
            title = nil
            artist = nil
            album = nil
            albumArtist = nil
            trackNumber = nil
            artworkURL = nil
            nowPlayingArtwork = nil
            nowPlayingArtworkURL = nil
            positionSeconds = 0
            durationSeconds = 0
            clearSystemNowPlaying()
        } else {
            publishSystemNowPlaying()
        }
        updateRemoteCommandAvailability()
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
                    publishSystemNowPlaying()
                    updateRemoteCommandAvailability()
                case .streamEnded:
                    isPlaying = false
                    status = .connected
                    publishSystemNowPlaying()
                    updateRemoteCommandAvailability()
                case .streamCleared:
                    positionSeconds = 0
                    publishSystemNowPlaying()
                case let .metadataReceived(metadata):
                    title = metadata.title
                    artist = metadata.artist
                    album = metadata.album
                    albumArtist = metadata.albumArtist
                    trackNumber = metadata.track
                    let nextArtworkURL = metadata.artworkURL.flatMap(URL.init(string:))
                    artworkURL = nextArtworkURL
                    updateProgress(metadata.progress)
                    refreshSystemArtwork(from: nextArtworkURL)
                    publishSystemNowPlaying()
                    updateRemoteCommandAvailability()
                case let .groupUpdated(group):
                    isPlaying = group.playbackState == .playing
                    status = isPlaying ? .streaming : .connected
                    publishSystemNowPlaying()
                    updateRemoteCommandAvailability()
                case let .controllerStateUpdated(controller):
                    volume = controller.volume
                    muted = controller.muted
                    supportedControllerCommands = controller.supportedCommands
                    updateRemoteCommandAvailability()
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
                    supportedControllerCommands = []
                    clearSystemNowPlaying()
                    updateRemoteCommandAvailability()
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

    private func configureSystemMediaIntegration() {
        guard !mediaIntegrationConfigured else { return }
        mediaIntegrationConfigured = true
        UIApplication.shared.beginReceivingRemoteControlEvents()

        let commands = MPRemoteCommandCenter.shared()
        remoteCommandTokens = [
            commands.playCommand.addTarget { [weak self] _ in
                Self.dispatchRemoteCommand("play", controller: self)
            },
            commands.pauseCommand.addTarget { [weak self] _ in
                Self.dispatchRemoteCommand("pause", controller: self)
            },
            commands.togglePlayPauseCommand.addTarget { [weak self] _ in
                Task { @MainActor [weak self] in
                    guard let self else { return }
                    await remoteCommandHandler?(
                        isPlaying ? "pause" : "play",
                        nil
                    )
                }
                return .success
            },
            commands.stopCommand.addTarget { [weak self] _ in
                Self.dispatchRemoteCommand("stop", controller: self)
            },
            commands.nextTrackCommand.addTarget { [weak self] _ in
                Self.dispatchRemoteCommand("next", controller: self)
            },
            commands.previousTrackCommand.addTarget { [weak self] _ in
                Self.dispatchRemoteCommand("previous", controller: self)
            },
            commands.changePlaybackPositionCommand.addTarget { [weak self] event in
                guard let event = event as? MPChangePlaybackPositionCommandEvent else {
                    return .commandFailed
                }
                Task { @MainActor [weak self] in
                    await self?.remoteCommandHandler?("seek", event.positionTime)
                }
                return .success
            },
        ]
        commands.skipForwardCommand.isEnabled = false
        commands.skipBackwardCommand.isEnabled = false
        commands.changePlaybackRateCommand.isEnabled = false
        commands.ratingCommand.isEnabled = false
        commands.likeCommand.isEnabled = false
        commands.dislikeCommand.isEnabled = false
        commands.bookmarkCommand.isEnabled = false
        updateRemoteCommandAvailability()
    }

    nonisolated private static func dispatchRemoteCommand(
        _ action: String,
        controller: PhonePlaybackController?
    ) -> MPRemoteCommandHandlerStatus {
        guard controller != nil else { return .commandFailed }
        Task { @MainActor [weak controller] in
            await controller?.remoteCommandHandler?(action, nil)
        }
        return .success
    }

    private func updateRemoteCommandAvailability() {
        guard mediaIntegrationConfigured else { return }
        let commands = MPRemoteCommandCenter.shared()
        let active = hasMedia && client != nil
        let permits: (ControllerCommandType) -> Bool = { [supportedControllerCommands] action in
            supportedControllerCommands.isEmpty
                || supportedControllerCommands.contains(action)
        }
        commands.playCommand.isEnabled = active && !isPlaying && permits(.play)
        commands.pauseCommand.isEnabled = active && isPlaying && permits(.pause)
        commands.togglePlayPauseCommand.isEnabled = active
            && permits(isPlaying ? .pause : .play)
        commands.stopCommand.isEnabled = active && permits(.stop)
        commands.nextTrackCommand.isEnabled = active && permits(.next)
        commands.previousTrackCommand.isEnabled = active && permits(.previous)
        commands.changePlaybackPositionCommand.isEnabled = active
            && durationSeconds > 0
            && remoteCommandHandler != nil
    }

    private func publishSystemNowPlaying() {
        guard mediaIntegrationConfigured, hasMedia, client != nil else { return }
        let center = MPNowPlayingInfoCenter.default()
        center.nowPlayingInfo = Self.makeNowPlayingInfo(
            title: title,
            artist: artist,
            album: album,
            albumArtist: albumArtist,
            trackNumber: trackNumber,
            durationSeconds: durationSeconds,
            positionSeconds: positionSeconds,
            isPlaying: isPlaying,
            artwork: nowPlayingArtwork
        )
        center.playbackState = isPlaying ? .playing : .paused
    }

    private func clearSystemNowPlaying() {
        guard mediaIntegrationConfigured else { return }
        let center = MPNowPlayingInfoCenter.default()
        center.nowPlayingInfo = nil
        center.playbackState = .stopped
    }

    private func refreshSystemArtwork(from url: URL?) {
        guard nowPlayingArtworkURL != url else { return }
        artworkTask?.cancel()
        artworkTask = nil
        nowPlayingArtworkURL = url
        nowPlayingArtwork = nil
        guard let url else { return }

        artworkTask = Task { [weak self] in
            var request = URLRequest(url: url)
            request.timeoutInterval = 12
            request.cachePolicy = .returnCacheDataElseLoad
            do {
                let (data, response) = try await URLSession.shared.data(for: request)
                guard
                    !Task.isCancelled,
                    data.count <= 12 * 1_024 * 1_024,
                    let response = response as? HTTPURLResponse,
                    (200..<300).contains(response.statusCode),
                    let image = UIImage(data: data)
                else { return }
                guard let self, artworkURL == url else { return }
                nowPlayingArtwork = MPMediaItemArtwork(
                    boundsSize: image.size
                ) { _ in image }
                publishSystemNowPlaying()
            } catch {
                // Metadata remains useful without artwork; a later track update
                // retries with the next URL without disturbing audio playback.
            }
        }
    }

    static func makeNowPlayingInfo(
        title: String?,
        artist: String?,
        album: String?,
        albumArtist: String?,
        trackNumber: Int?,
        durationSeconds: Double,
        positionSeconds: Double,
        isPlaying: Bool,
        artwork: MPMediaItemArtwork? = nil
    ) -> [String: Any] {
        let duration = max(0, durationSeconds)
        let elapsed = duration > 0
            ? min(max(0, positionSeconds), duration)
            : max(0, positionSeconds)
        var info: [String: Any] = [
            MPMediaItemPropertyTitle: title?.nilIfBlank ?? "Pilot Audio",
            MPMediaItemPropertyMediaType: MPMediaType.music.rawValue,
            MPNowPlayingInfoPropertyElapsedPlaybackTime: elapsed,
            MPNowPlayingInfoPropertyPlaybackRate: isPlaying ? 1.0 : 0.0,
            MPNowPlayingInfoPropertyDefaultPlaybackRate: 1.0,
            MPNowPlayingInfoPropertyServiceIdentifier: "Pilot",
        ]
        if let artist = artist?.nilIfBlank {
            info[MPMediaItemPropertyArtist] = artist
        }
        if let album = album?.nilIfBlank {
            info[MPMediaItemPropertyAlbumTitle] = album
        }
        if let albumArtist = albumArtist?.nilIfBlank {
            info[MPMediaItemPropertyAlbumArtist] = albumArtist
        }
        if let trackNumber, trackNumber > 0 {
            info[MPMediaItemPropertyAlbumTrackNumber] = trackNumber
        }
        if duration > 0 {
            info[MPMediaItemPropertyPlaybackDuration] = duration
            info[MPNowPlayingInfoPropertyIsLiveStream] = false
        }
        if let artwork {
            info[MPMediaItemPropertyArtwork] = artwork
        }
        return info
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

private extension String {
    var nilIfBlank: String? {
        let value = trimmingCharacters(in: .whitespacesAndNewlines)
        return value.isEmpty ? nil : value
    }
}
