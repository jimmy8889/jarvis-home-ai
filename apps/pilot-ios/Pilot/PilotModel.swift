import Foundation
import Observation

@MainActor
@Observable
final class PilotModel {
    var coreURL = UserDefaults.standard.string(forKey: "pilot.coreURL") ?? "http://10.0.1.64:8770"
    var deviceID = UserDefaults.standard.string(forKey: "pilot.deviceID") ?? "pilot-ios-james"
    var token = KeychainStore.read(account: "device-token")
    var rooms: [PilotRoom] = []
    var playerStates: [PilotPlayerState] = []
    var selectedRoomID = UserDefaults.standard.string(forKey: "pilot.roomID") ?? "office"
    var searchResults: [MusicSearchResult] = []
    var messages: [ChatMessage] = []
    var conversationID: String?
    var status = "Not connected"
    var isBusy = false

    var isConfigured: Bool {
        !coreURL.isEmpty && !deviceID.isEmpty && !token.isEmpty
    }

    var selectedPlayer: PilotPlayerState? {
        guard let room = rooms.first(where: { $0.id == selectedRoomID }) else { return nil }
        return playerStates.first(where: { $0.player.id == room.defaultMusicPlayerID })
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

    func api() throws -> PilotAPI {
        guard isConfigured else { throw PilotAPIError.notConfigured }
        guard let url = URL(string: coreURL), ["http", "https"].contains(url.scheme) else {
            throw PilotAPIError.invalidURL
        }
        return PilotAPI(coreURL: url, deviceID: deviceID, token: token)
    }

    func refresh() async {
        guard isConfigured else { return }
        do {
            let value = try await api().media()
            rooms = value.rooms
            playerStates = value.media.players.values.sorted {
                $0.player.name.localizedCaseInsensitiveCompare($1.player.name) == .orderedAscending
            }
            if !rooms.contains(where: { $0.id == selectedRoomID }) {
                selectedRoomID = value.roomID
            }
            status = "Connected"
        } catch {
            status = error.localizedDescription
        }
    }

    func command(_ action: String, volume: Int? = nil, mediaURI: String? = nil) async {
        guard let player = selectedPlayer else { return }
        isBusy = true
        defer { isBusy = false }
        do {
            try await api().send(
                MediaCommand(
                    action: action,
                    playerID: player.player.id,
                    mediaURI: mediaURI,
                    volume: volume
                )
            )
            await refresh()
        } catch {
            status = error.localizedDescription
        }
    }

    func search(_ query: String) async {
        guard !query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
        isBusy = true
        defer { isBusy = false }
        do {
            searchResults = try await api().search(query)
        } catch {
            status = error.localizedDescription
        }
    }

    func ask(_ text: String) async {
        let prompt = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !prompt.isEmpty else { return }
        messages.append(ChatMessage(role: .user, text: prompt))
        isBusy = true
        defer { isBusy = false }
        do {
            let reply = try await api().ask(
                prompt,
                roomID: selectedRoomID,
                conversationID: conversationID
            )
            conversationID = reply.conversationID
            messages.append(ChatMessage(role: .pilot, text: reply.responseText))
            status = "Connected · \(reply.provider)"
        } catch {
            messages.append(ChatMessage(role: .pilot, text: error.localizedDescription))
            status = error.localizedDescription
        }
    }
}
