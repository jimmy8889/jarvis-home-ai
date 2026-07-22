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
    var activeMediaResultID: String?
    var mediaError: String?
    var energy = EnergySnapshot.awaitingBackend
    var energyError: String?
    var dashboard = DashboardSnapshot.unavailable
    var dashboardError: String?
    var dashboardActionInFlight = false
    var musicBrowsePage: MusicBrowsePage?
    var isBrowsingMusic = false
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
    var isSubmittingMeeting = false
    var activeMeetingID: String?
    var meetingRecordingStartedAt: Date?
    var pendingMeetingRecordings: [PendingMeetingRecording] = []
    var clientManifest: PilotClientManifest?
    var liveUpdatesConnected = false
    var lastEventAt: Date?
    var assistantStatus = "ready"
    private(set) var hasActiveConfiguration = false
    @ObservationIgnored private var activeCoreURL = ""
    @ObservationIgnored private var activeDeviceID = ""
    @ObservationIgnored private var activeToken = ""
    @ObservationIgnored private var eventCursor: String?
    @ObservationIgnored private var meetingRecorder: AVAudioRecorder?
    @ObservationIgnored private var meetingRecordingURL: URL?
    @ObservationIgnored private var activeMeetingTitle: String?

    private enum StorageKey {
        static let mediaCache = "pilot.cache.media.v1"
        static let homeCache = "pilot.cache.home.v1"
        static let energyCache = "pilot.cache.energy.v1"
        static let dashboardCache = "pilot.cache.dashboard.v1"
        static let meetingsCache = "pilot.cache.meetings.v1"
        static let cacheDate = "pilot.cache.date.v1"
        static let pendingMeetings = "pilot.pendingMeetings.v1"
        static let eventCursor = "pilot.events.cursor.v1"
    }

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
        activeCoreURL = coreURL
        activeDeviceID = deviceID
        activeToken = token
        hasActiveConfiguration = Self.configurationIsValid(
            coreURL: activeCoreURL,
            deviceID: activeDeviceID,
            token: activeToken
        )
        eventCursor = UserDefaults.standard.string(forKey: StorageKey.eventCursor)
        restoreDurableState()
    }

    var isConfigured: Bool {
        Self.configurationIsValid(coreURL: coreURL, deviceID: deviceID, token: token)
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

    private func saveActiveSettings() {
        UserDefaults.standard.set(activeCoreURL, forKey: "pilot.coreURL")
        UserDefaults.standard.set(activeDeviceID, forKey: "pilot.deviceID")
        UserDefaults.standard.set(selectedRoomID, forKey: "pilot.roomID")
        try? KeychainStore.save(activeToken, account: "device-token")
    }

    func selectRoom(_ roomID: String) {
        selectedRoomID = roomID
        UserDefaults.standard.set(roomID, forKey: "pilot.roomID")
        home = nil
        Task { await refreshHome() }
    }

    func api() throws -> PilotAPI {
        guard hasActiveConfiguration else { throw PilotAPIError.notConfigured }
        guard let url = URL(string: activeCoreURL), ["http", "https"].contains(url.scheme) else {
            throw PilotAPIError.invalidURL
        }
        return PilotAPI(coreURL: url, deviceID: activeDeviceID, token: activeToken)
    }

    @discardableResult
    func connect() async -> Bool {
        let candidateURL = Self.normalizedCoreURL(coreURL)
        let candidateDeviceID = deviceID.trimmingCharacters(in: .whitespacesAndNewlines)
        let candidateToken = token.trimmingCharacters(in: .whitespacesAndNewlines)
        guard
            Self.configurationIsValid(
                coreURL: candidateURL,
                deviceID: candidateDeviceID,
                token: candidateToken
            ),
            let url = URL(string: candidateURL)
        else {
            connectionState = .offline("Enter a valid Pilot Core URL, device ID, and token.")
            return false
        }

        connectionState = .connecting
        isRefreshing = true
        defer { isRefreshing = false }
        do {
            let candidate = PilotAPI(
                coreURL: url,
                deviceID: candidateDeviceID,
                token: candidateToken
            )
            let manifest = try? await candidate.manifest()
            let media: DeviceMediaEnvelope?
            if manifest?.features["media"] == false {
                media = nil
            } else {
                // Media remains the compatibility authentication probe for a
                // Core release that predates the client manifest.
                media = try await candidate.media()
            }
            activeCoreURL = candidateURL
            activeDeviceID = candidateDeviceID
            activeToken = candidateToken
            coreURL = candidateURL
            deviceID = candidateDeviceID
            token = candidateToken
            hasActiveConfiguration = true
            if let media {
                apply(media)
                cache(media: media)
            }
            saveActiveSettings()
            lastSuccessfulRefresh = .now
            connectionState = .connected
            clientManifest = manifest
            await refreshHome(silent: true)
            await refreshEnergy(silent: true)
            await refreshDashboard(silent: true)
            await refreshMeetings(silent: true)
            return true
        } catch {
            connectionState = .offline(Self.friendlyMessage(for: error))
            return false
        }
    }

    @discardableResult
    func refresh(silent: Bool = false) async -> Bool {
        guard hasActiveConfiguration else {
            connectionState = .notConfigured
            return false
        }
        if !silent {
            connectionState = .connecting
        }
        isRefreshing = true
        defer { isRefreshing = false }
        do {
            let service = try api()
            let value = try await service.media()
            apply(value)
            cache(media: value)
            if !rooms.contains(where: { $0.id == selectedRoomID }) {
                selectRoom(value.roomID)
            }
            lastSuccessfulRefresh = .now
            connectionState = .connected
            mediaError = nil
            if clientManifest == nil { clientManifest = try? await service.manifest() }
            await refreshHome(silent: true)
            await refreshEnergy(silent: true)
            await refreshDashboard(silent: true)
            await refreshMeetings(silent: true)
            return true
        } catch {
            let message = Self.friendlyMessage(for: error)
            mediaError = message
            connectionState = .offline(message)
            return false
        }
    }

    func refreshEnergy(silent: Bool = false) async {
        guard hasActiveConfiguration else { return }
        do {
            let service = try api()
            do {
                energy = try await service.energy()
            } catch {
                // Compatibility with deployed Core versions while the portable
                // energy contract rolls out. This only succeeds for clients
                // already granted the display capability.
                energy = try await service.surfaceEnergy()
            }
            energyError = energy.detail
            cache(energy: energy)
        } catch {
            energyError = Self.friendlyMessage(for: error)
            if !energy.isPopulated {
                energy = EnergySnapshot(
                    status: .unavailable,
                    solarWatts: nil,
                    gridWatts: nil,
                    batteryWatts: nil,
                    batteryStateOfCharge: nil,
                    homeLoadWatts: nil,
                    observedAt: nil,
                    detail: energyError
                )
            }
        }
    }

    func refreshDashboard(silent: Bool = false) async {
        guard hasActiveConfiguration else { return }
        do {
            dashboard = try await api().dashboard()
            dashboardError = dashboard.status == "unavailable"
                ? "Live dashboard data is unavailable." : nil
            cache(dashboard: dashboard)
        } catch {
            dashboardError = Self.friendlyMessage(for: error)
        }
    }

    func runUpdateLoop() async {
        _ = await refresh()
        while !Task.isCancelled {
            guard hasActiveConfiguration else {
                try? await Task.sleep(for: .seconds(2))
                continue
            }
            do {
                let service = try api()
                if clientManifest == nil { clientManifest = try? await service.manifest() }
                if let snapshot = try? await service.eventSnapshot(after: eventCursor) {
                    for event in snapshot.events { await handle(event) }
                    updateEventCursor(snapshot.cursor)
                }
                liveUpdatesConnected = true
                while !Task.isCancelled {
                    let batch = try await service.pollEvents(after: eventCursor)
                    if batch.resetRequired == true || batch.resyncRequired == true {
                        let recovery = try await service.eventSnapshot(after: nil)
                        for event in recovery.events { await handle(event) }
                        updateEventCursor(recovery.cursor)
                    } else {
                        for event in batch.events { await handle(event) }
                        updateEventCursor(batch.cursor)
                    }
                    liveUpdatesConnected = true
                }
            } catch is CancellationError {
                liveUpdatesConnected = false
                return
            } catch {
                liveUpdatesConnected = false
                // Older Core releases do not yet expose device event streams.
                // Polling remains a bounded compatibility path, not a second
                // source of truth.
                _ = await refresh(silent: true)
                try? await Task.sleep(for: .seconds(15))
            }
        }
    }

    func pair(using pairingCode: String) async -> Bool {
        guard let payload = Self.parsePairingCode(pairingCode, defaultCoreURL: coreURL) else {
            connectionState = .offline("That pairing code is not valid.")
            return false
        }
        connectionState = .connecting
        isRefreshing = true
        defer { isRefreshing = false }
        do {
            let credentials = try await PilotAPI.redeemBootstrap(
                token: payload.token,
                coreURL: payload.coreURL
            )
            coreURL = Self.normalizedCoreURL(payload.coreURL.absoluteString)
            deviceID = credentials.deviceID
            token = credentials.deviceToken
            // Authentication and capabilities are tested before any credential
            // is activated or persisted.
            return await connect()
        } catch {
            connectionState = .offline(Self.friendlyMessage(for: error))
            return false
        }
    }

    static func parsePairingCode(
        _ rawValue: String,
        defaultCoreURL: String
    ) -> (coreURL: URL, token: String)? {
        let value = rawValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !value.isEmpty else { return nil }

        if
            let data = value.data(using: .utf8),
            let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
            let core = (object["core_url"] ?? object["core"]) as? String,
            let token = (object["bootstrap_token"] ?? object["token"]) as? String,
            let url = URL(string: Self.normalizedCoreURL(core))
        {
            return (url, token)
        }

        if let components = URLComponents(string: value), components.scheme == "pilot" {
            let values = Dictionary(
                uniqueKeysWithValues: (components.queryItems ?? []).map { ($0.name, $0.value ?? "") }
            )
            let core = values["core_url"] ?? values["core"]
            let grant = values["bootstrap_token"] ?? values["token"] ?? values["code"]
            if
                let core,
                let grant,
                let url = URL(string: Self.normalizedCoreURL(core)),
                !grant.isEmpty
            {
                return (url, grant)
            }
        }

        guard
            let url = URL(string: Self.normalizedCoreURL(defaultCoreURL)),
            !value.contains(where: \.isWhitespace)
        else { return nil }
        return (url, value)
    }

    private func handle(_ event: PilotClientEvent) async {
        lastEventAt = .now
        if let revision = event.revision { updateEventCursor(String(revision)) }
        let normalized = event.type.lowercased()
        if normalized.contains("assistant") {
            assistantStatus = normalized
        }
        if normalized.contains("media") || normalized.contains("player")
            || normalized.contains("audio") || normalized.contains("source") {
            _ = await refresh(silent: true)
        } else if normalized.contains("home") || normalized.contains("entity") {
            await refreshHome(silent: true)
            await refreshDashboard(silent: true)
            if normalized.contains("energy") { await refreshEnergy(silent: true) }
        } else if normalized.contains("meeting") {
            await refreshMeetings(silent: true)
        } else if normalized.contains("energy") {
            await refreshEnergy(silent: true)
            await refreshDashboard(silent: true)
        }
    }

    private func updateEventCursor(_ cursor: String?) {
        guard let cursor, !cursor.isEmpty else { return }
        eventCursor = cursor
        UserDefaults.standard.set(cursor, forKey: StorageKey.eventCursor)
    }

    func refreshHome(silent: Bool = false) async {
        guard hasActiveConfiguration else { return }
        if !silent { isLoadingHome = true }
        defer { isLoadingHome = false }
        do {
            let projection = try await api().home(roomID: selectedRoomID)
            home = projection
            cache(home: projection)
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
        mediaURI: String? = nil,
        positionSeconds: Double? = nil,
        muted: Bool? = nil,
        operationID: String? = nil
    ) async {
        guard let player = selectedPlayer else { return }
        activeMediaAction = action
        activeMediaResultID = operationID
        defer {
            activeMediaAction = nil
            activeMediaResultID = nil
        }
        do {
            try await api().send(
                MediaCommand(
                    action: action,
                    playerID: player.player.id,
                    mediaURI: mediaURI,
                    volume: volume,
                    positionSeconds: positionSeconds,
                    muted: muted
                )
            )
            _ = await refresh(silent: true)
            mediaError = nil
        } catch {
            mediaError = Self.friendlyMessage(for: error)
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
            mediaError = Self.friendlyMessage(for: error)
        }
    }

    func search(_ query: String) async {
        let normalized = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !normalized.isEmpty else {
            searchResults = []
            lastSearchQuery = ""
            musicBrowsePage = nil
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
            mediaError = Self.friendlyMessage(for: error)
        }
    }

    func browse(_ result: MusicSearchResult) async {
        guard [.artist, .album, .playlist].contains(result.kind) else {
            await command("play_media", mediaURI: result.uri, operationID: result.id)
            return
        }
        isBrowsingMusic = true
        defer { isBrowsingMusic = false }
        do {
            musicBrowsePage = try await api().browse(result)
            mediaError = nil
        } catch {
            musicBrowsePage = nil
            mediaError = Self.friendlyMessage(for: error)
        }
    }

    func dismissMusicBrowse() {
        musicBrowsePage = nil
    }

    func dashboardAction(_ action: String, value: String) async {
        dashboardActionInFlight = true
        defer { dashboardActionInFlight = false }
        do {
            try await api().dashboardAction(action, value: value)
            await refreshDashboard(silent: true)
            dashboardError = nil
        } catch {
            dashboardError = Self.friendlyMessage(for: error)
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
            messages.append(
                ChatMessage(
                    role: .pilot,
                    text: reply.responseText,
                    provider: reply.provider,
                    cards: reply.cards ?? [],
                    sources: reply.sources ?? [],
                    actions: reply.actions ?? [],
                    toolCalls: reply.toolCalls ?? []
                )
            )
            assistantStatus = reply.status ?? "ready"
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
        guard hasActiveConfiguration else { return }
        if !silent { isLoadingMeetings = true }
        defer { isLoadingMeetings = false }
        do {
            meetings = try await api().meetings()
            cache(meetings: meetings)
            meetingError = nil
        } catch {
            meetingError = Self.friendlyMessage(for: error)
        }
    }

    func loadMeeting(_ meetingID: String) async {
        guard hasActiveConfiguration else { return }
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
#if compiler(>=6.2)
            let categoryOptions: AVAudioSession.CategoryOptions = [
                .defaultToSpeaker,
                .allowBluetoothHFP,
            ]
#else
            let categoryOptions: AVAudioSession.CategoryOptions = [
                .defaultToSpeaker,
                .allowBluetooth,
            ]
#endif
            try audioSession.setCategory(
                .playAndRecord,
                mode: .spokenAudio,
                options: categoryOptions
            )
            try audioSession.setActive(true)
            let directory = try Self.meetingRecordingDirectory()
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
            activeMeetingTitle = normalized
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
        let title = activeMeetingTitle ?? "Meeting recording"
        let pending = PendingMeetingRecording(
            id: meetingID,
            meetingID: meetingID,
            title: title,
            recordingPath: recordingURL.path,
            state: .ready,
            uploadComplete: false,
            failureMessage: nil,
            updatedAt: .now
        )
        upsertPendingRecording(pending)
        activeMeetingID = nil
        activeMeetingTitle = nil
        meetingRecordingURL = nil
        defer {
            try? AVAudioSession.sharedInstance().setActive(
                false,
                options: .notifyOthersOnDeactivation
            )
        }
        await submitPendingRecording(meetingID)
    }

    func retryPendingMeeting(_ meetingID: String) async {
        await submitPendingRecording(meetingID)
    }

    private func submitPendingRecording(_ meetingID: String) async {
        guard
            let initialIndex = pendingMeetingRecordings.firstIndex(where: { $0.meetingID == meetingID })
        else { return }
        let recordingURL = pendingMeetingRecordings[initialIndex].recordingURL
        guard FileManager.default.fileExists(atPath: recordingURL.path) else {
            updatePendingRecording(
                meetingID,
                state: .failed,
                failure: "The retained recording file is no longer available."
            )
            return
        }
        isSubmittingMeeting = true
        defer { isSubmittingMeeting = false }
        do {
            let service = try api()
            if !pendingMeetingRecordings[initialIndex].uploadComplete {
                updatePendingRecording(meetingID, state: .uploading, failure: nil)
                try await service.uploadMeetingRecording(
                    meetingID: meetingID,
                    recordingURL: recordingURL
                )
                markPendingUploadComplete(meetingID)
            }
            updatePendingRecording(meetingID, state: .processing, failure: nil)
            _ = try await service.processMeeting(meetingID)
            // The local source is removed only after Core has both accepted the
            // upload and queued processing. Every failure path above retains it.
            try? FileManager.default.removeItem(at: recordingURL)
            pendingMeetingRecordings.removeAll { $0.meetingID == meetingID }
            persistPendingRecordings()
            await refreshMeetings(silent: true)
            meetingError = nil
        } catch {
            let message = Self.friendlyMessage(for: error)
            updatePendingRecording(meetingID, state: .failed, failure: message)
            meetingError = "Recording retained on this device. \(message)"
            await refreshMeetings(silent: true)
        }
    }

    private func apply(_ envelope: DeviceMediaEnvelope) {
        rooms = envelope.rooms
        playerStates = envelope.media.players.values.sorted {
            $0.player.name.localizedCaseInsensitiveCompare($1.player.name)
                == .orderedAscending
        }
    }

    private func restoreDurableState() {
        let defaults = UserDefaults.standard
        let decoder = JSONDecoder()
        if
            hasActiveConfiguration,
            let data = defaults.data(forKey: StorageKey.mediaCache),
            let cached = try? decoder.decode(DeviceMediaEnvelope.self, from: data)
        {
            apply(cached)
        }
        if
            let data = defaults.data(forKey: StorageKey.homeCache),
            let cached = try? decoder.decode(HomeProjection.self, from: data),
            cached.selectedRoomID == selectedRoomID
        {
            home = cached
        }
        if
            let data = defaults.data(forKey: StorageKey.energyCache),
            let cached = try? decoder.decode(EnergySnapshot.self, from: data)
        {
            energy = cached
        }
        if
            let data = defaults.data(forKey: StorageKey.dashboardCache),
            let cached = try? decoder.decode(DashboardSnapshot.self, from: data)
        {
            dashboard = cached
        }
        if
            let data = defaults.data(forKey: StorageKey.meetingsCache),
            let cached = try? decoder.decode([PilotMeeting].self, from: data)
        {
            meetings = cached
        }
        if let date = defaults.object(forKey: StorageKey.cacheDate) as? Date {
            lastSuccessfulRefresh = date
        }
        if
            let data = defaults.data(forKey: StorageKey.pendingMeetings),
            let cached = try? decoder.decode([PendingMeetingRecording].self, from: data)
        {
            pendingMeetingRecordings = cached.map { value in
                guard FileManager.default.fileExists(atPath: value.recordingPath) else {
                    var missing = value
                    missing.state = .failed
                    missing.failureMessage = "The retained recording file is missing."
                    return missing
                }
                return value
            }
        }
    }

    private func cache(media: DeviceMediaEnvelope) {
        if let data = try? JSONEncoder().encode(media) {
            UserDefaults.standard.set(data, forKey: StorageKey.mediaCache)
        }
        markCacheUpdated()
    }

    private func cache(home: HomeProjection) {
        if let data = try? JSONEncoder().encode(home) {
            UserDefaults.standard.set(data, forKey: StorageKey.homeCache)
        }
        markCacheUpdated()
    }

    private func cache(energy: EnergySnapshot) {
        if let data = try? JSONEncoder().encode(energy) {
            UserDefaults.standard.set(data, forKey: StorageKey.energyCache)
        }
        markCacheUpdated()
    }

    private func cache(dashboard: DashboardSnapshot) {
        if let data = try? JSONEncoder().encode(dashboard) {
            UserDefaults.standard.set(data, forKey: StorageKey.dashboardCache)
        }
        markCacheUpdated()
    }

    private func cache(meetings: [PilotMeeting]) {
        if let data = try? JSONEncoder().encode(meetings) {
            UserDefaults.standard.set(data, forKey: StorageKey.meetingsCache)
        }
        markCacheUpdated()
    }

    private func markCacheUpdated() {
        let date = Date.now
        UserDefaults.standard.set(date, forKey: StorageKey.cacheDate)
        lastSuccessfulRefresh = date
    }

    private func upsertPendingRecording(_ recording: PendingMeetingRecording) {
        pendingMeetingRecordings.removeAll { $0.meetingID == recording.meetingID }
        pendingMeetingRecordings.insert(recording, at: 0)
        persistPendingRecordings()
    }

    private func updatePendingRecording(
        _ meetingID: String,
        state: PendingMeetingRecording.State,
        failure: String?
    ) {
        guard let index = pendingMeetingRecordings.firstIndex(where: { $0.meetingID == meetingID }) else {
            return
        }
        pendingMeetingRecordings[index].state = state
        pendingMeetingRecordings[index].failureMessage = failure
        pendingMeetingRecordings[index].updatedAt = .now
        persistPendingRecordings()
    }

    private func markPendingUploadComplete(_ meetingID: String) {
        guard let index = pendingMeetingRecordings.firstIndex(where: { $0.meetingID == meetingID }) else {
            return
        }
        pendingMeetingRecordings[index].uploadComplete = true
        pendingMeetingRecordings[index].updatedAt = .now
        persistPendingRecordings()
    }

    private func persistPendingRecordings() {
        if let data = try? JSONEncoder().encode(pendingMeetingRecordings) {
            UserDefaults.standard.set(data, forKey: StorageKey.pendingMeetings)
        }
    }

    private static func meetingRecordingDirectory() throws -> URL {
        let applicationSupport = try FileManager.default.url(
            for: .applicationSupportDirectory,
            in: .userDomainMask,
            appropriateFor: nil,
            create: true
        )
        let directory = applicationSupport
            .appending(path: "Pilot", directoryHint: .isDirectory)
            .appending(path: "MeetingRecordings", directoryHint: .isDirectory)
        try FileManager.default.createDirectory(
            at: directory,
            withIntermediateDirectories: true
        )
        return directory
    }

    private static func normalizedCoreURL(_ value: String) -> String {
        value.trimmingCharacters(in: .whitespacesAndNewlines)
            .trimmingCharacters(in: CharacterSet(charactersIn: "/"))
    }

    private static func configurationIsValid(
        coreURL: String,
        deviceID: String,
        token: String
    ) -> Bool {
        guard
            let url = URL(string: normalizedCoreURL(coreURL)),
            ["http", "https"].contains(url.scheme)
        else { return false }
        return !deviceID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && !token.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
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
                musicEnabled: true,
                players: [officePlayer]
            ),
            PilotRoom(
                id: "media-room",
                name: "Media Room",
                responsePlayerID: mediaPlayer.id,
                defaultMusicPlayerID: mediaPlayer.id,
                musicEnabled: true,
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
                ),
                capabilities: nil
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
                ),
                capabilities: nil
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
        model.dashboard = DashboardSnapshot(
            schemaVersion: "pilot.dashboard.v1",
            generatedAt: ISO8601DateFormatter().string(from: .now),
            status: "ok",
            power: DashboardPower(
                solarWatts: 8_820, gridWatts: -15, batteryWatts: -3_110,
                batteryStateOfCharge: 77, homeLoadWatts: 5_610,
                serverRackWatts: 640, vehicleWatts: 4_540,
                directions: ["grid": "idle", "battery": "charging"],
                flowActive: ["solar": true, "grid": false, "battery": true,
                             "home": true, "server_rack": true, "vehicle": true]
            ),
            daily: DashboardDaily(
                solarGeneratedKWh: 66.3, homeUsedKWh: 32.9, gridExportedKWh: 5.5
            ),
            vehicle: DashboardVehicle(
                name: "Jarvis", connected: true, charging: true,
                powerWatts: 4_540, stateOfCharge: 63
            ),
            tariff: DashboardTariff(
                importCentsPerKWh: 17.4, feedInCentsPerKWh: 8.2,
                feedInForecast: []
            ),
            temperatures: [
                DashboardTemperature(id: "office", label: "Office", temperatureCelsius: 22.4),
                DashboardTemperature(id: "outdoor", label: "Outdoor", temperatureCelsius: 24.1),
                DashboardTemperature(id: "bedroom", label: "Bedroom", temperatureCelsius: 21.8),
            ],
            history: .empty,
            weather: DashboardWeather(
                status: "ok", condition: "partlycloudy", temperatureCelsius: 24.1,
                apparentTemperatureCelsius: 23.6, humidityPercent: 58,
                windSpeed: 13, windSpeedUnit: "km/h", forecast: []
            ),
            controls: DashboardControls(
                chargingMode: DashboardChargingMode(
                    value: "Solar", options: ["Grid", "Solar"], available: true
                ),
                mediaRoomMode: DashboardMediaRoomMode(available: true)
            )
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
