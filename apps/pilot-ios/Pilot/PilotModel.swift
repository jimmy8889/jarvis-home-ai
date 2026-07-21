import Foundation
import Observation
import AVFoundation

@MainActor
@Observable
final class PilotModel {
    var coreURL: String
    var deviceID: String
    var token: String
    var rooms: [PilotRoom] = []
    var playerStates: [PilotPlayerState] = []
    var selectedRoomID: String
    var searchResults: [MusicSearchResult] = []
    var lastSearchQuery = ""
    var messages: [ChatMessage] = []
    var conversationID: String?
    var connectionState: PilotConnectionState
    var lastSuccessfulRefresh: Date?
    var isRefreshing = false
    var isSearching = false
    var isSendingMessage = false
    var activeMediaAction: String?
    var energy = EnergySnapshot.awaitingBackend
    var home: HomeProjection?
    var pendingHomeAction: HomeAction?
    var isLoadingHome = false
    var activeHomeEntityID: String?
    var homeError: String?
    var meetings: [PilotMeeting] = []
    var meetingError: String?
    var isLoadingMeetings = false
    var selectedMeeting: PilotMeetingDetail?
    var isLoadingMeetingDetail = false
    var isRecordingMeeting = false
    var activeMeetingID: String?
    var meetingRecordingStartedAt: Date?
    @ObservationIgnored private var meetingRecorder: AVAudioRecorder?
    @ObservationIgnored private var meetingRecordingURL: URL?

    init(loadStoredSettings: Bool = true) {
        if loadStoredSettings {
            coreURL = UserDefaults.standard.string(forKey: "pilot.coreURL")
                ?? "http://10.0.1.64:8770"
            deviceID = UserDefaults.standard.string(forKey: "pilot.deviceID")
                ?? "pilot-ios-james"
            token = KeychainStore.read(account: "device-token")
            selectedRoomID = UserDefaults.standard.string(forKey: "pilot.roomID")
                ?? "office"
        } else {
            coreURL = ""
            deviceID = ""
            token = ""
            selectedRoomID = "office"
        }
        connectionState = .notConfigured
    }

    var isConfigured: Bool {
        !coreURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && !deviceID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && !token.isEmpty
    }

    var status: String {
        connectionState.label
    }

    var selectedRoom: PilotRoom? {
        rooms.first(where: { $0.id == selectedRoomID })
    }

    var selectedPlayer: PilotPlayerState? {
        guard let selectedRoom else { return nil }
        return playerStates.first(where: {
            $0.player.id == selectedRoom.defaultMusicPlayerID
        })
    }

    var activePlayer: PilotPlayerState? {
        playerStates.first(where: {
            ["playing", "buffering"].contains(
                $0.effective.playbackState?.lowercased() ?? ""
            )
        }) ?? selectedPlayer
    }

    var groupedSearchResults: [(MusicResultKind, [MusicSearchResult])] {
        MusicResultKind.allCases.compactMap { kind in
            let values = searchResults.filter { $0.kind == kind }
            return values.isEmpty ? nil : (kind, values)
        }
    }

    func saveSettings() {
        coreURL = coreURL.trimmingCharacters(in: .whitespacesAndNewlines)
            .trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        deviceID = deviceID.trimmingCharacters(in: .whitespacesAndNewlines)
        UserDefaults.standard.set(coreURL, forKey: "pilot.coreURL")
        UserDefaults.standard.set(deviceID, forKey: "pilot.deviceID")
        UserDefaults.standard.set(selectedRoomID, forKey: "pilot.roomID")
        try? KeychainStore.save(token, account: "device-token")
    }

    func selectRoom(_ roomID: String) {
        selectedRoomID = roomID
        UserDefaults.standard.set(roomID, forKey: "pilot.roomID")
        home = nil
        Task { await refreshHome() }
    }

    func api() throws -> PilotAPI {
        guard isConfigured else { throw PilotAPIError.notConfigured }
        guard let url = URL(string: coreURL), ["http", "https"].contains(url.scheme) else {
            throw PilotAPIError.invalidURL
        }
        return PilotAPI(coreURL: url, deviceID: deviceID, token: token)
    }

    @discardableResult
    func connect() async -> Bool {
        saveSettings()
        return await refresh()
    }

    @discardableResult
    func refresh(silent: Bool = false) async -> Bool {
        guard isConfigured else {
            connectionState = .notConfigured
            return false
        }
        if !silent {
            connectionState = .connecting
        }
        isRefreshing = true
        defer { isRefreshing = false }
        do {
            let value = try await api().media()
            rooms = value.rooms
            playerStates = value.media.players.values.sorted {
                $0.player.name.localizedCaseInsensitiveCompare($1.player.name)
                    == .orderedAscending
            }
            if !rooms.contains(where: { $0.id == selectedRoomID }) {
                selectRoom(value.roomID)
            }
            lastSuccessfulRefresh = .now
            connectionState = .connected
            await refreshHome(silent: true)
            await refreshMeetings(silent: true)
            return true
        } catch {
            connectionState = .offline(Self.friendlyMessage(for: error))
            return false
        }
    }

    func refreshHome(silent: Bool = false) async {
        guard isConfigured else { return }
        if !silent { isLoadingHome = true }
        defer { isLoadingHome = false }
        do {
            home = try await api().home(roomID: selectedRoomID)
            homeError = nil
        } catch {
            homeError = Self.friendlyMessage(for: error)
        }
    }

    func control(
        _ entity: HomeEntity,
        action: String,
        value: Double? = nil
    ) async {
        activeHomeEntityID = entity.id
        defer { activeHomeEntityID = nil }
        do {
            let parameters: [String: JSONValue] = value.map {
                ["value": .number($0)]
            } ?? [:]
            let response = try await api().homeAction(
                HomeActionRequest(
                    roomID: selectedRoomID,
                    entityID: entity.entityID,
                    action: action,
                    parameters: parameters
                )
            )
            if response.action.confirmationRequired && response.action.status == "pending" {
                pendingHomeAction = response.action
            } else {
                pendingHomeAction = nil
                await refreshHome(silent: true)
            }
            homeError = nil
        } catch {
            homeError = Self.friendlyMessage(for: error)
        }
    }

    func confirmPendingHomeAction() async {
        guard let pendingHomeAction else { return }
        activeHomeEntityID = pendingHomeAction.entityID
        defer { activeHomeEntityID = nil }
        do {
            _ = try await api().confirmHomeAction(pendingHomeAction.id)
            self.pendingHomeAction = nil
            await refreshHome(silent: true)
            homeError = nil
        } catch {
            homeError = Self.friendlyMessage(for: error)
        }
    }

    func command(
        _ action: String,
        volume: Int? = nil,
        mediaURI: String? = nil
    ) async {
        guard let player = selectedPlayer else { return }
        activeMediaAction = action
        defer { activeMediaAction = nil }
        do {
            try await api().send(
                MediaCommand(
                    action: action,
                    playerID: player.player.id,
                    mediaURI: mediaURI,
                    volume: volume
                )
            )
            _ = await refresh(silent: true)
        } catch {
            connectionState = .offline(Self.friendlyMessage(for: error))
        }
    }

    func transfer(to roomID: String) async {
        guard let player = selectedPlayer, roomID != selectedRoomID else { return }
        activeMediaAction = "transfer"
        defer { activeMediaAction = nil }
        do {
            try await api().send(
                MediaCommand(
                    action: "transfer",
                    playerID: player.player.id,
                    targetRoomID: roomID
                )
            )
            selectRoom(roomID)
            _ = await refresh(silent: true)
        } catch {
            connectionState = .offline(Self.friendlyMessage(for: error))
        }
    }

    func search(_ query: String) async {
        let normalized = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !normalized.isEmpty else {
            searchResults = []
            lastSearchQuery = ""
            return
        }
        lastSearchQuery = normalized
        isSearching = true
        defer { isSearching = false }
        do {
            searchResults = try await api().search(normalized)
            connectionState = .connected
        } catch {
            searchResults = []
            connectionState = .offline(Self.friendlyMessage(for: error))
        }
    }

    func ask(_ text: String) async {
        let prompt = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !prompt.isEmpty else { return }
        messages.append(ChatMessage(role: .user, text: prompt))
        isSendingMessage = true
        defer { isSendingMessage = false }
        do {
            let reply = try await api().ask(
                prompt,
                roomID: selectedRoomID,
                conversationID: conversationID
            )
            conversationID = reply.conversationID
            messages.append(ChatMessage(role: .pilot, text: reply.responseText))
            connectionState = .connected
        } catch {
            let message = Self.friendlyMessage(for: error)
            messages.append(
                ChatMessage(role: .pilot, text: message, isError: true)
            )
            connectionState = .offline(message)
        }
    }

    func startNewConversation() {
        conversationID = nil
        messages = []
    }

    func refreshMeetings(silent: Bool = false) async {
        guard isConfigured else { return }
        if !silent { isLoadingMeetings = true }
        defer { isLoadingMeetings = false }
        do {
            meetings = try await api().meetings()
            meetingError = nil
        } catch {
            meetingError = Self.friendlyMessage(for: error)
        }
    }

    func loadMeeting(_ meetingID: String) async {
        guard isConfigured else { return }
        isLoadingMeetingDetail = true
        defer { isLoadingMeetingDetail = false }
        do {
            selectedMeeting = try await api().meeting(meetingID)
            meetingError = nil
        } catch {
            selectedMeeting = nil
            meetingError = Self.friendlyMessage(for: error)
        }
    }

    func startMeeting(title: String) async {
        let normalized = title.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !normalized.isEmpty, !isRecordingMeeting else { return }
        do {
            guard await AVAudioApplication.requestRecordPermission() else {
                meetingError = "Microphone permission is required to record a meeting."
                return
            }
            let meeting = try await api().createMeeting(title: normalized)
            let audioSession = AVAudioSession.sharedInstance()
            try audioSession.setCategory(
                .playAndRecord,
                mode: .spokenAudio,
                options: [.defaultToSpeaker, .allowBluetooth]
            )
            try audioSession.setActive(true)
            let directory = FileManager.default.temporaryDirectory
                .appending(path: "PilotMeetings", directoryHint: .isDirectory)
            try FileManager.default.createDirectory(
                at: directory,
                withIntermediateDirectories: true
            )
            let recordingURL = directory.appending(path: "\(meeting.id).m4a")
            let recorder = try AVAudioRecorder(
                url: recordingURL,
                settings: [
                    AVFormatIDKey: Int(kAudioFormatMPEG4AAC),
                    AVSampleRateKey: 24_000,
                    AVNumberOfChannelsKey: 1,
                    AVEncoderAudioQualityKey: AVAudioQuality.high.rawValue,
                ]
            )
            recorder.prepareToRecord()
            guard recorder.record() else {
                throw PilotAPIError.server("The microphone could not start recording.")
            }
            meetingRecorder = recorder
            meetingRecordingURL = recordingURL
            activeMeetingID = meeting.id
            meetingRecordingStartedAt = .now
            isRecordingMeeting = true
            meetings.insert(meeting, at: 0)
            meetingError = nil
        } catch {
            meetingError = Self.friendlyMessage(for: error)
        }
    }

    func stopAndProcessMeeting() async {
        guard
            isRecordingMeeting,
            let meetingID = activeMeetingID,
            let recordingURL = meetingRecordingURL
        else { return }
        meetingRecorder?.stop()
        meetingRecorder = nil
        isRecordingMeeting = false
        meetingRecordingStartedAt = nil
        defer {
            activeMeetingID = nil
            meetingRecordingURL = nil
            try? FileManager.default.removeItem(at: recordingURL)
            try? AVAudioSession.sharedInstance().setActive(
                false,
                options: .notifyOthersOnDeactivation
            )
        }
        do {
            let service = try api()
            try await service.uploadMeetingRecording(
                meetingID: meetingID,
                recordingURL: recordingURL
            )
            _ = try await service.processMeeting(meetingID)
            await refreshMeetings(silent: true)
            meetingError = nil
        } catch {
            meetingError = Self.friendlyMessage(for: error)
            await refreshMeetings(silent: true)
        }
    }

    static func friendlyMessage(for error: Error) -> String {
        if let urlError = error as? URLError {
            switch urlError.code {
            case .notConnectedToInternet, .networkConnectionLost:
                return "Pilot Core is offline. Check your local network."
            case .timedOut:
                return "Pilot Core took too long to respond."
            case .cannotConnectToHost, .cannotFindHost:
                return "Pilot Core could not be reached."
            default:
                break
            }
        }
        return error.localizedDescription
    }

    static func preview() -> PilotModel {
        let model = PilotModel(loadStoredSettings: false)
        model.coreURL = "http://pilot.local:8770"
        model.deviceID = "pilot-ios-preview"
        model.token = "preview"
        let officePlayer = PilotPlayer(
            id: "office-n150",
            roomID: "office",
            name: "Office Audio",
            kind: "audio",
            protocolName: "sendspin",
            enabled: true,
            controlEnabled: true
        )
        let mediaPlayer = PilotPlayer(
            id: "media-room-heos",
            roomID: "media-room",
            name: "Media Room",
            kind: "receiver",
            protocolName: "heos",
            enabled: true,
            controlEnabled: true
        )
        model.rooms = [
            PilotRoom(
                id: "office",
                name: "Office",
                responsePlayerID: officePlayer.id,
                defaultMusicPlayerID: officePlayer.id,
                players: [officePlayer]
            ),
            PilotRoom(
                id: "media-room",
                name: "Media Room",
                responsePlayerID: mediaPlayer.id,
                defaultMusicPlayerID: mediaPlayer.id,
                players: [mediaPlayer]
            ),
        ]
        model.playerStates = [
            PilotPlayerState(
                player: officePlayer,
                status: "available",
                effective: EffectiveMediaState(
                    available: true,
                    powered: true,
                    playbackState: "playing",
                    volumePercent: 34,
                    muted: false,
                    source: "Music Assistant",
                    media: CurrentMedia(
                        title: "Teardrop",
                        artist: "Massive Attack",
                        album: "Mezzanine"
                    )
                )
            ),
            PilotPlayerState(
                player: mediaPlayer,
                status: "available",
                effective: EffectiveMediaState(
                    available: true,
                    powered: true,
                    playbackState: "idle",
                    volumePercent: 26,
                    muted: false,
                    source: "HEOS",
                    media: nil
                )
            ),
        ]
        model.energy = EnergySnapshot(
            status: .live,
            solarWatts: 8_420,
            gridWatts: -4_910,
            batteryWatts: 2_080,
            batteryStateOfCharge: 76,
            homeLoadWatts: 3_510,
            observedAt: .now,
            detail: nil
        )
        model.messages = [
            ChatMessage(
                role: .pilot,
                text: "Good evening. The office is playing Teardrop and the house is exporting 4.9 kW."
            ),
            ChatMessage(role: .user, text: "What about the battery?"),
            ChatMessage(
                role: .pilot,
                text: "The battery is at 76% and charging at roughly 2.1 kW."
            ),
        ]
        model.connectionState = .connected
        model.lastSuccessfulRefresh = .now
        return model
    }
}
