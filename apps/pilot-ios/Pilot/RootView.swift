import SwiftUI

struct RootView: View {
    @Environment(PilotModel.self) private var model

    var body: some View {
        Group {
            if model.isConfigured {
                TabView {
                    HomeView()
                        .tabItem { Label("Home", systemImage: "house.fill") }
                    MusicView()
                        .tabItem { Label("Music", systemImage: "music.note") }
                    AssistantView()
                        .tabItem { Label("Pilot", systemImage: "waveform.circle.fill") }
                    SettingsView()
                        .tabItem { Label("Settings", systemImage: "gearshape.fill") }
                }
                .tint(.cyan)
            } else {
                SettingsView(isInitialSetup: true)
            }
        }
    }
}

private struct HomeView: View {
    @Environment(PilotModel.self) private var model

    var body: some View {
        NavigationStack {
            List {
                Section("Connection") {
                    LabeledContent("Pilot Core", value: model.status)
                    Picker("Current room", selection: Bindable(model).selectedRoomID) {
                        ForEach(model.rooms) { room in
                            Text(room.name).tag(room.id)
                        }
                    }
                }
                Section("Rooms") {
                    ForEach(model.rooms) { room in
                        let state = model.playerStates.first {
                            $0.player.id == room.defaultMusicPlayerID
                        }
                        VStack(alignment: .leading, spacing: 5) {
                            Text(room.name).font(.headline)
                            Text(state?.effective.media?.title ?? "Nothing playing")
                            Text(state?.effective.playbackState ?? "Unavailable")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                }
            }
            .navigationTitle("Pilot")
            .refreshable { await model.refresh() }
        }
    }
}

private struct MusicView: View {
    @Environment(PilotModel.self) private var model
    @State private var query = ""
    @State private var volume = 30.0

    var body: some View {
        NavigationStack {
            List {
                Section("Output") {
                    Picker("Room", selection: Bindable(model).selectedRoomID) {
                        ForEach(model.rooms) { room in
                            Text(room.name).tag(room.id)
                        }
                    }
                    if let state = model.selectedPlayer {
                        VStack(alignment: .leading, spacing: 4) {
                            Text(state.effective.media?.title ?? state.player.name)
                                .font(.headline)
                            Text(state.effective.media?.artist ?? state.effective.playbackState ?? "Idle")
                                .foregroundStyle(.secondary)
                        }
                        HStack {
                            Button { Task { await model.command("play") } } label: {
                                Image(systemName: "play.fill")
                            }
                            Spacer()
                            Button { Task { await model.command("pause") } } label: {
                                Image(systemName: "pause.fill")
                            }
                            Spacer()
                            Button { Task { await model.command("stop") } } label: {
                                Image(systemName: "stop.fill")
                            }
                        }
                        .buttonStyle(.borderedProminent)
                        Slider(value: $volume, in: 0...100, step: 1) { editing in
                            if !editing {
                                Task { await model.command("set_volume", volume: Int(volume)) }
                            }
                        }
                    }
                }
                Section("Search Music Assistant") {
                    HStack {
                        TextField("Artist, album or track", text: $query)
                            .textInputAutocapitalization(.never)
                            .submitLabel(.search)
                            .onSubmit { Task { await model.search(query) } }
                        Button("Search") { Task { await model.search(query) } }
                    }
                    ForEach(model.searchResults) { result in
                        Button {
                            Task { await model.command("play_media", mediaURI: result.uri) }
                        } label: {
                            VStack(alignment: .leading) {
                                Text(result.title)
                                Text(result.subtitle)
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                        }
                    }
                }
            }
            .navigationTitle("Music")
            .overlay { if model.isBusy { ProgressView() } }
            .task {
                await model.refresh()
                volume = Double(model.selectedPlayer?.effective.volumePercent ?? 30)
            }
        }
    }
}

private struct AssistantView: View {
    @Environment(PilotModel.self) private var model
    @State private var prompt = ""

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                Picker("Room", selection: Bindable(model).selectedRoomID) {
                    ForEach(model.rooms) { room in
                        Text(room.name).tag(room.id)
                    }
                }
                .pickerStyle(.segmented)
                .padding()
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 12) {
                        ForEach(model.messages) { message in
                            Text(message.text)
                                .padding(12)
                                .background(
                                    message.role == .user
                                        ? Color.blue.opacity(0.22)
                                        : Color.secondary.opacity(0.14),
                                    in: RoundedRectangle(cornerRadius: 15)
                                )
                                .frame(
                                    maxWidth: .infinity,
                                    alignment: message.role == .user ? .trailing : .leading
                                )
                        }
                    }
                    .padding()
                }
                HStack {
                    TextField("Ask Pilot", text: $prompt)
                        .textFieldStyle(.roundedBorder)
                        .submitLabel(.send)
                        .onSubmit { send() }
                    Button("Send") { send() }
                        .buttonStyle(.borderedProminent)
                }
                .padding()
            }
            .navigationTitle("Pilot Assistant")
        }
    }

    private func send() {
        let value = prompt
        prompt = ""
        Task { await model.ask(value) }
    }
}

private struct SettingsView: View {
    @Environment(PilotModel.self) private var model
    var isInitialSetup = false

    var body: some View {
        @Bindable var model = model
        NavigationStack {
            Form {
                Section("Pilot Core") {
                    TextField("Core URL", text: $model.coreURL)
                        .textInputAutocapitalization(.never)
                        .keyboardType(.URL)
                    TextField("Device ID", text: $model.deviceID)
                        .textInputAutocapitalization(.never)
                    SecureField("Device token", text: $model.token)
                }
                Section {
                    Button(isInitialSetup ? "Connect" : "Save and reconnect") {
                        model.saveSettings()
                        Task { await model.refresh() }
                    }
                    .disabled(model.coreURL.isEmpty || model.deviceID.isEmpty || model.token.isEmpty)
                }
                if !isInitialSetup {
                    Section("Status") {
                        Text(model.status)
                    }
                }
            }
            .navigationTitle(isInitialSetup ? "Set up Pilot" : "Settings")
        }
    }
}
