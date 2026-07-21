import SwiftUI
import UIKit

enum PilotSection: String, CaseIterable, Identifiable {
    case home
    case music
    case meetings
    case assistant
    case settings

    var id: String { rawValue }

    var title: String {
        switch self {
        case .home: "Home"
        case .music: "Music"
        case .meetings: "Meetings"
        case .assistant: "Pilot"
        case .settings: "Settings"
        }
    }

    var symbol: String {
        switch self {
        case .home: "house.fill"
        case .music: "music.note"
        case .meetings: "waveform.badge.mic"
        case .assistant: "waveform.circle.fill"
        case .settings: "gearshape.fill"
        }
    }
}

enum PilotTheme {
    static let cyan = Color(red: 0.18, green: 0.84, blue: 0.92)
    static let blue = Color(red: 0.20, green: 0.46, blue: 0.98)
    static let violet = Color(red: 0.47, green: 0.30, blue: 0.96)
    static let mint = Color(red: 0.22, green: 0.86, blue: 0.66)
    static let amber = Color(red: 1.00, green: 0.70, blue: 0.24)
    static let card = Color.white.opacity(0.075)
    static let border = Color.white.opacity(0.10)
    static let background = LinearGradient(
        colors: [
            Color(red: 0.035, green: 0.055, blue: 0.11),
            Color(red: 0.055, green: 0.035, blue: 0.12),
            Color(red: 0.025, green: 0.075, blue: 0.10),
        ],
        startPoint: .topLeading,
        endPoint: .bottomTrailing
    )
}

struct RootView: View {
    @Environment(PilotModel.self) private var model
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass
    @Environment(\.scenePhase) private var scenePhase
    @State private var section: PilotSection? = .home
    @State private var showingNowPlaying = false

    var body: some View {
        Group {
            if model.isConfigured {
                configuredContent
            } else {
                OnboardingView()
            }
        }
        .preferredColorScheme(.dark)
        .tint(PilotTheme.cyan)
        .sheet(isPresented: $showingNowPlaying) {
            NowPlayingView()
                .presentationDetents([.large])
                .presentationDragIndicator(.visible)
        }
        .onChange(of: scenePhase) { _, phase in
            if phase == .active {
                Task { await model.refresh(silent: true) }
            }
        }
    }

    @ViewBuilder
    private var configuredContent: some View {
        if horizontalSizeClass == .regular {
            NavigationSplitView {
                TabletSidebar(selection: $section)
            } detail: {
                NavigationStack {
                    destination(section ?? .home)
                }
                .safeAreaInset(edge: .bottom) {
                    MiniPlayerBar(showingNowPlaying: $showingNowPlaying)
                        .padding(.horizontal)
                        .padding(.bottom, 8)
                }
            }
            .navigationSplitViewStyle(.balanced)
        } else {
            TabView(selection: Binding(
                get: { section ?? .home },
                set: { section = $0 }
            )) {
                ForEach(PilotSection.allCases) { item in
                    NavigationStack {
                        destination(item)
                    }
                    .tag(item)
                    .tabItem { Label(item.title, systemImage: item.symbol) }
                }
            }
            .safeAreaInset(edge: .bottom, spacing: 0) {
                MiniPlayerBar(showingNowPlaying: $showingNowPlaying)
                    .padding(.horizontal, 10)
                    .padding(.bottom, 4)
            }
        }
    }

    @ViewBuilder
    private func destination(_ item: PilotSection) -> some View {
        switch item {
        case .home: HomeView()
        case .music: MusicView()
        case .meetings: MeetingsView()
        case .assistant: AssistantView()
        case .settings: SettingsView()
        }
    }
}

private struct TabletSidebar: View {
    @Environment(PilotModel.self) private var model
    @Binding var selection: PilotSection?

    var body: some View {
        ZStack {
            PilotTheme.background.ignoresSafeArea()
            VStack(alignment: .leading, spacing: 20) {
                HStack(spacing: 12) {
                    PilotMark(size: 42)
                    VStack(alignment: .leading, spacing: 1) {
                        Text("PILOT")
                            .font(.system(.headline, design: .rounded, weight: .bold))
                            .tracking(2)
                        Text("Home intelligence")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
                .padding(.horizontal, 16)
                .padding(.top, 8)

                List(PilotSection.allCases, selection: $selection) { item in
                    Label(item.title, systemImage: item.symbol)
                        .font(.body.weight(.semibold))
                        .padding(.vertical, 5)
                        .tag(item)
                }
                .scrollContentBackground(.hidden)
                .listStyle(.sidebar)

                ConnectionPill()
                    .padding(16)
            }
        }
        .navigationSplitViewColumnWidth(min: 230, ideal: 270, max: 320)
    }
}

private struct HomeView: View {
    @Environment(PilotModel.self) private var model
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass

    private let columns = [
        GridItem(.adaptive(minimum: 260), spacing: 16),
    ]

    var body: some View {
        ZStack {
            PilotTheme.background.ignoresSafeArea()
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 22) {
                    HomeHeader()
                    if !model.connectionState.isConnected {
                        OfflineBanner()
                    }

                    if model.rooms.isEmpty && model.isRefreshing {
                        RoomSkeletonGrid()
                    } else if model.rooms.isEmpty {
                        EmptyRoomsView()
                    } else {
                        VStack(alignment: .leading, spacing: 12) {
                            SectionTitle(
                                eyebrow: "YOUR HOME",
                                title: "Rooms",
                                trailing: "\(model.rooms.count) connected"
                            )
                            LazyVGrid(columns: columns, spacing: 16) {
                                ForEach(model.rooms) { room in
                                    RoomCard(room: room)
                                }
                            }
                        }
                    }

                    EnergyOverviewCard(snapshot: model.energy)
                    HomeQuickActions()
                    HomeControlsPanel()
                }
                .frame(maxWidth: 1_100)
                .padding(horizontalSizeClass == .regular ? 28 : 18)
                .padding(.bottom, 100)
                .frame(maxWidth: .infinity)
            }
            .refreshable { await model.refresh() }
        }
        .navigationTitle("Home")
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                ConnectionPill(compact: true)
            }
        }
        .alert(
            model.pendingHomeAction?.description ?? "Confirm home action",
            isPresented: Binding(
                get: { model.pendingHomeAction != nil },
                set: { if !$0 { model.pendingHomeAction = nil } }
            )
        ) {
            Button("Cancel", role: .cancel) { model.pendingHomeAction = nil }
            Button("Confirm", role: .destructive) {
                Task { await model.confirmPendingHomeAction() }
            }
        } message: {
            Text("Pilot will perform this high-risk action once. The request expires automatically.")
        }
    }
}

private struct HomeHeader: View {
    @Environment(PilotModel.self) private var model

    private var greeting: String {
        switch Calendar.current.component(.hour, from: .now) {
        case 5..<12: "Good morning"
        case 12..<18: "Good afternoon"
        default: "Good evening"
        }
    }

    var body: some View {
        HStack(alignment: .center, spacing: 16) {
            VStack(alignment: .leading, spacing: 6) {
                Text(greeting)
                    .font(.system(.largeTitle, design: .rounded, weight: .bold))
                Text("Your home, clearly understood.")
                    .font(.title3)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            Menu {
                ForEach(model.rooms) { room in
                    Button {
                        model.selectRoom(room.id)
                        PilotHaptics.selection()
                    } label: {
                        if room.id == model.selectedRoomID {
                            Label(room.name, systemImage: "checkmark")
                        } else {
                            Text(room.name)
                        }
                    }
                }
            } label: {
                HStack(spacing: 8) {
                    Image(systemName: "location.fill")
                    Text(model.selectedRoom?.name ?? "Choose room")
                        .lineLimit(1)
                    Image(systemName: "chevron.up.chevron.down")
                        .font(.caption2)
                }
                .font(.subheadline.weight(.semibold))
                .padding(.horizontal, 14)
                .padding(.vertical, 11)
                .background(.ultraThinMaterial, in: Capsule())
            }
            .accessibilityLabel("Current room, \(model.selectedRoom?.name ?? "not selected")")
        }
    }
}

private struct RoomCard: View {
    @Environment(PilotModel.self) private var model
    let room: PilotRoom

    private var player: PilotPlayerState? {
        model.playerStates.first { $0.player.id == room.defaultMusicPlayerID }
    }

    private var isSelected: Bool { room.id == model.selectedRoomID }

    var body: some View {
        Button {
            model.selectRoom(room.id)
            PilotHaptics.selection()
        } label: {
            VStack(alignment: .leading, spacing: 16) {
                HStack {
                    ZStack {
                        Circle()
                            .fill(isSelected ? PilotTheme.cyan.opacity(0.20) : Color.white.opacity(0.06))
                        Image(systemName: roomSymbol)
                            .foregroundStyle(isSelected ? PilotTheme.cyan : .secondary)
                    }
                    .frame(width: 44, height: 44)
                    Spacer()
                    AvailabilityDot(available: player?.effective.available)
                }

                VStack(alignment: .leading, spacing: 4) {
                    Text(room.name)
                        .font(.title3.weight(.bold))
                        .foregroundStyle(.primary)
                    Text(player?.effective.media?.title ?? statusText)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }

                HStack {
                    Label(
                        player?.effective.playbackState?.capitalized ?? "Ready",
                        systemImage: player?.effective.playbackState == "playing"
                            ? "waveform" : "speaker.wave.2"
                    )
                    Spacer()
                    if let volume = player?.effective.volumePercent {
                        Text("\(volume)%")
                            .monospacedDigit()
                    }
                }
                .font(.caption.weight(.medium))
                .foregroundStyle(.secondary)
            }
            .padding(18)
            .frame(maxWidth: .infinity, minHeight: 178, alignment: .leading)
            .background(
                isSelected ? PilotTheme.blue.opacity(0.14) : PilotTheme.card,
                in: RoundedRectangle(cornerRadius: 24, style: .continuous)
            )
            .overlay {
                RoundedRectangle(cornerRadius: 24, style: .continuous)
                    .stroke(
                        isSelected ? PilotTheme.cyan.opacity(0.38) : PilotTheme.border,
                        lineWidth: 1
                    )
            }
        }
        .buttonStyle(.plain)
        .accessibilityLabel("\(room.name), \(statusText)")
        .accessibilityHint("Selects this room for music and Pilot")
    }

    private var statusText: String {
        if player?.effective.available == false { return "Player unavailable" }
        return player?.effective.media?.artist ?? "Ready for Pilot"
    }

    private var roomSymbol: String {
        let id = room.id.lowercased()
        if id.contains("bed") { return "bed.double.fill" }
        if id.contains("office") { return "desktopcomputer" }
        if id.contains("media") || id.contains("theatre") { return "tv.fill" }
        if id.contains("kitchen") { return "fork.knife" }
        return "door.left.hand.open"
    }
}

private struct EnergyOverviewCard: View {
    let snapshot: EnergySnapshot

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            SectionTitle(
                eyebrow: "LIVE ENERGY",
                title: "Power flow",
                trailing: snapshot.status == .live ? "Now" : "API ready"
            )
            if snapshot.isPopulated {
                energyContent
            } else {
                HStack(spacing: 16) {
                    ZStack {
                        Circle()
                            .fill(PilotTheme.amber.opacity(0.16))
                        Image(systemName: "bolt.horizontal.circle.fill")
                            .font(.title2)
                            .foregroundStyle(PilotTheme.amber)
                    }
                    .frame(width: 52, height: 52)
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Energy model is ready")
                            .font(.headline)
                        Text(snapshot.detail ?? "Waiting for Pilot Core energy data.")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    }
                }
                .padding(.vertical, 4)
            }
        }
        .pilotCard()
        .accessibilityElement(children: .contain)
    }

    private var energyContent: some View {
        VStack(spacing: 18) {
            HStack(spacing: 0) {
                EnergyMetric(
                    title: "Solar",
                    value: snapshot.solarWatts,
                    symbol: "sun.max.fill",
                    color: PilotTheme.amber
                )
                Divider().frame(height: 54)
                EnergyMetric(
                    title: "Home",
                    value: snapshot.homeLoadWatts,
                    symbol: "house.fill",
                    color: PilotTheme.cyan
                )
                Divider().frame(height: 54)
                EnergyMetric(
                    title: snapshot.gridWatts ?? 0 < 0 ? "Export" : "Grid",
                    value: abs(snapshot.gridWatts ?? 0),
                    symbol: "transmission",
                    color: PilotTheme.violet
                )
            }
            if let stateOfCharge = snapshot.batteryStateOfCharge {
                HStack(spacing: 12) {
                    Image(systemName: "battery.75percent")
                        .foregroundStyle(PilotTheme.mint)
                    ProgressView(value: stateOfCharge, total: 100)
                        .tint(PilotTheme.mint)
                    Text("\(Int(stateOfCharge))%")
                        .font(.subheadline.monospacedDigit().weight(.semibold))
                }
            }
        }
    }
}

private struct EnergyMetric: View {
    let title: String
    let value: Double?
    let symbol: String
    let color: Color

    var body: some View {
        VStack(spacing: 6) {
            Label(title, systemImage: symbol)
                .font(.caption.weight(.semibold))
                .foregroundStyle(color)
            Text(Self.power(value))
                .font(.system(.headline, design: .rounded, weight: .bold))
                .monospacedDigit()
        }
        .frame(maxWidth: .infinity)
    }

    private static func power(_ watts: Double?) -> String {
        guard let watts else { return "—" }
        if abs(watts) >= 1_000 {
            return String(format: "%.1f kW", abs(watts) / 1_000)
        }
        return String(format: "%.0f W", abs(watts))
    }
}

private struct HomeQuickActions: View {
    @Environment(PilotModel.self) private var model

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            SectionTitle(eyebrow: "QUICK ACTIONS", title: "At your fingertips")
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 12) {
                    QuickAction(title: "Pause music", symbol: "pause.fill", tint: PilotTheme.blue) {
                        Task { await model.command("pause") }
                    }
                    QuickAction(title: "Stop audio", symbol: "stop.fill", tint: PilotTheme.violet) {
                        Task { await model.command("stop") }
                    }
                    QuickAction(title: "Refresh home", symbol: "arrow.clockwise", tint: PilotTheme.mint) {
                        Task { await model.refresh() }
                    }
                }
            }
        }
    }
}

private struct HomeControlsPanel: View {
    @Environment(PilotModel.self) private var model

    private var grouped: [(String, [HomeEntity])] {
        Dictionary(grouping: model.home?.entities ?? [], by: \.domain)
            .map { ($0.key, $0.value.sorted { $0.name < $1.name }) }
            .sorted { $0.0 < $1.0 }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            SectionTitle(
                eyebrow: "ROOM CONTROL",
                title: model.home?.room.name ?? model.selectedRoom?.name ?? "Selected room",
                trailing: model.home.map { "\($0.entityCount) devices" }
            )
            if model.isLoadingHome && model.home == nil {
                ProgressView("Loading secure room controls…")
                    .frame(maxWidth: .infinity, alignment: .leading)
            } else if let error = model.homeError {
                Label(error, systemImage: "exclamationmark.triangle.fill")
                    .font(.subheadline)
                    .foregroundStyle(PilotTheme.amber)
            } else if grouped.isEmpty {
                ContentUnavailableView(
                    "No mapped controls",
                    systemImage: "house.lodge",
                    description: Text("Assign Home Assistant devices to this room to make them available here.")
                )
            } else {
                ForEach(grouped, id: \.0) { domain, entities in
                    VStack(alignment: .leading, spacing: 10) {
                        Label(domain.replacingOccurrences(of: "_", with: " ").capitalized,
                              systemImage: symbol(for: domain))
                            .font(.caption.weight(.bold))
                            .foregroundStyle(.secondary)
                        ForEach(entities) { entity in
                            HomeEntityRow(entity: entity)
                        }
                    }
                }
            }
        }
        .pilotCard()
        .task(id: model.selectedRoomID) {
            await model.refreshHome()
        }
    }

    private func symbol(for domain: String) -> String {
        switch domain {
        case "light": "lightbulb.fill"
        case "switch", "input_boolean": "switch.2"
        case "climate": "thermometer.medium"
        case "fan": "fan.fill"
        case "cover": "window.shade.open"
        case "scene": "sparkles"
        case "lock": "lock.fill"
        case "alarm_control_panel": "shield.fill"
        default: "square.grid.2x2.fill"
        }
    }
}

private struct HomeEntityRow: View {
    @Environment(PilotModel.self) private var model
    let entity: HomeEntity

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 12) {
                VStack(alignment: .leading, spacing: 3) {
                    Text(entity.name)
                        .font(.headline)
                    Text(entity.stale ? "Stale" : entity.state.replacingOccurrences(of: "_", with: " ").capitalized)
                        .font(.caption)
                        .foregroundStyle(entity.stale || entity.unavailable ? PilotTheme.amber : .secondary)
                }
                Spacer()
                if model.activeHomeEntityID == entity.id {
                    ProgressView()
                } else if entity.actions.contains("turn_on") {
                    Toggle(
                        "Power",
                        isOn: Binding(
                            get: { entity.isOn },
                            set: { value in
                                Task { await model.control(entity, action: value ? "turn_on" : "turn_off") }
                            }
                        )
                    )
                    .labelsHidden()
                    .disabled(entity.stale || entity.unavailable)
                } else {
                    actionButtons
                }
            }
            if entity.actions.contains("set_brightness"),
               let brightness = entity.brightnessPercent {
                HStack {
                    Image(systemName: "sun.min")
                    Slider(
                        value: Binding(
                            get: { brightness },
                            set: { value in
                                Task { await model.control(entity, action: "set_brightness", value: value) }
                            }
                        ),
                        in: 0...100,
                        step: 5
                    )
                    Image(systemName: "sun.max.fill")
                }
                .foregroundStyle(.secondary)
                .disabled(model.activeHomeEntityID == entity.id)
            }
        }
        .padding(14)
        .background(Color.white.opacity(0.045), in: RoundedRectangle(cornerRadius: 16))
    }

    @ViewBuilder
    private var actionButtons: some View {
        HStack(spacing: 8) {
            if entity.actions.contains("activate") {
                Button("Activate") { Task { await model.control(entity, action: "activate") } }
            }
            if entity.actions.contains("open") {
                Button("Open") { Task { await model.control(entity, action: "open") } }
                Button("Close") { Task { await model.control(entity, action: "close") } }
            }
            if entity.actions.contains("lock") {
                Button(entity.state == "locked" ? "Unlock" : "Lock") {
                    Task {
                        await model.control(
                            entity,
                            action: entity.state == "locked" ? "unlock" : "lock"
                        )
                    }
                }
            }
            if entity.actions.contains("arm_home") {
                Button(entity.state == "disarmed" ? "Arm home" : "Disarm") {
                    Task {
                        await model.control(
                            entity,
                            action: entity.state == "disarmed" ? "arm_home" : "disarm"
                        )
                    }
                }
            }
        }
        .buttonStyle(.bordered)
        .disabled(entity.stale || entity.unavailable)
    }
}

private struct QuickAction: View {
    let title: String
    let symbol: String
    let tint: Color
    let action: () -> Void

    var body: some View {
        Button {
            PilotHaptics.impact()
            action()
        } label: {
            Label(title, systemImage: symbol)
                .font(.subheadline.weight(.semibold))
                .padding(.horizontal, 16)
                .padding(.vertical, 14)
                .background(tint.opacity(0.13), in: Capsule())
                .overlay { Capsule().stroke(tint.opacity(0.24)) }
        }
        .buttonStyle(.plain)
    }
}

private struct MusicView: View {
    @Environment(PilotModel.self) private var model
    @State private var query = ""
    @State private var showingNowPlaying = false

    var body: some View {
        ZStack {
            PilotTheme.background.ignoresSafeArea()
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 22) {
                    RoomSelector()
                    NowPlayingHero {
                        showingNowPlaying = true
                    }
                    MusicSearchField(query: $query)
                    searchContent
                }
                .frame(maxWidth: 900)
                .padding(18)
                .padding(.bottom, 100)
                .frame(maxWidth: .infinity)
            }
        }
        .navigationTitle("Music")
        .sheet(isPresented: $showingNowPlaying) {
            NowPlayingView()
                .presentationDetents([.large])
                .presentationDragIndicator(.visible)
        }
        .refreshable { await model.refresh() }
    }

    @ViewBuilder
    private var searchContent: some View {
        if model.isSearching {
            VStack(spacing: 12) {
                ForEach(0..<4, id: \.self) { _ in SearchRowSkeleton() }
            }
            .accessibilityLabel("Searching Music Assistant")
        } else if !model.lastSearchQuery.isEmpty && model.searchResults.isEmpty {
            ContentUnavailableView.search(text: model.lastSearchQuery)
                .frame(maxWidth: .infinity)
                .pilotCard()
        } else {
            ForEach(model.groupedSearchResults, id: \.0) { kind, results in
                VStack(alignment: .leading, spacing: 10) {
                    SectionTitle(eyebrow: kind.title.uppercased(), title: "")
                    ForEach(results) { result in
                        SearchResultRow(result: result)
                    }
                }
            }
        }
    }
}

private struct RoomSelector: View {
    @Environment(PilotModel.self) private var model

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 10) {
                ForEach(model.rooms) { room in
                    Button {
                        model.selectRoom(room.id)
                        PilotHaptics.selection()
                    } label: {
                        Label(
                            room.name,
                            systemImage: room.id == model.selectedRoomID
                                ? "checkmark.circle.fill" : "circle"
                        )
                        .font(.subheadline.weight(.semibold))
                        .padding(.horizontal, 14)
                        .padding(.vertical, 10)
                        .background(
                            room.id == model.selectedRoomID
                                ? PilotTheme.cyan.opacity(0.18)
                                : PilotTheme.card,
                            in: Capsule()
                        )
                    }
                    .buttonStyle(.plain)
                }
            }
        }
        .accessibilityLabel("Music room")
    }
}

private struct NowPlayingHero: View {
    @Environment(PilotModel.self) private var model
    let open: () -> Void

    private var state: PilotPlayerState? { model.selectedPlayer }

    var body: some View {
        VStack(spacing: 22) {
            HStack(spacing: 18) {
                ArtworkTile(media: state?.effective.media, size: 92)
                VStack(alignment: .leading, spacing: 5) {
                    Text(state?.effective.media?.title ?? "Ready to play")
                        .font(.title2.weight(.bold))
                        .lineLimit(2)
                    Text(state?.effective.media?.artist ?? state?.player.name ?? "Choose music below")
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                    Text(model.selectedRoom?.name ?? "No room selected")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(PilotTheme.cyan)
                }
                Spacer(minLength: 0)
            }

            HStack(spacing: 26) {
                MediaButton(symbol: "stop.fill", label: "Stop", size: 42) {
                    Task { await model.command("stop") }
                }
                MediaButton(
                    symbol: state?.effective.playbackState == "playing" ? "pause.fill" : "play.fill",
                    label: state?.effective.playbackState == "playing" ? "Pause" : "Play",
                    size: 58,
                    prominent: true
                ) {
                    let action = state?.effective.playbackState == "playing" ? "pause" : "play"
                    Task { await model.command(action) }
                }
                Button(action: open) {
                    Image(systemName: "slider.horizontal.3")
                        .frame(width: 42, height: 42)
                        .background(Color.white.opacity(0.08), in: Circle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel("More playback controls")
            }
        }
        .pilotCard()
    }
}

private struct MusicSearchField: View {
    @Environment(PilotModel.self) private var model
    @Binding var query: String

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            SectionTitle(eyebrow: "MUSIC ASSISTANT", title: "Find something to play")
            HStack(spacing: 10) {
                Image(systemName: "magnifyingglass")
                    .foregroundStyle(.secondary)
                TextField("Artists, albums, songs or playlists", text: $query)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .submitLabel(.search)
                    .onSubmit { submit() }
                if !query.isEmpty {
                    Button {
                        query = ""
                        Task { await model.search("") }
                    } label: {
                        Image(systemName: "xmark.circle.fill")
                            .foregroundStyle(.secondary)
                    }
                    .accessibilityLabel("Clear search")
                }
            }
            .padding(15)
            .background(Color.white.opacity(0.07), in: RoundedRectangle(cornerRadius: 16))
            .overlay { RoundedRectangle(cornerRadius: 16).stroke(PilotTheme.border) }
        }
    }

    private func submit() {
        PilotHaptics.impact()
        Task { await model.search(query) }
    }
}

private struct SearchResultRow: View {
    @Environment(PilotModel.self) private var model
    let result: MusicSearchResult

    var body: some View {
        Button {
            PilotHaptics.impact()
            Task { await model.command("play_media", mediaURI: result.uri) }
        } label: {
            HStack(spacing: 13) {
                AsyncArtwork(url: result.artworkURL, symbol: result.kind.symbol)
                    .frame(width: 50, height: 50)
                VStack(alignment: .leading, spacing: 3) {
                    Text(result.title)
                        .font(.body.weight(.semibold))
                        .foregroundStyle(.primary)
                        .lineLimit(1)
                    Text(result.subtitle.isEmpty ? result.kind.title : result.subtitle)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
                Spacer()
                if model.activeMediaAction == "play_media" {
                    ProgressView().controlSize(.small)
                } else {
                    Image(systemName: "play.circle.fill")
                        .font(.title2)
                        .foregroundStyle(PilotTheme.cyan)
                }
            }
            .padding(12)
            .background(PilotTheme.card, in: RoundedRectangle(cornerRadius: 18))
        }
        .buttonStyle(.plain)
        .accessibilityLabel("Play \(result.title), \(result.subtitle)")
    }
}

private struct MeetingsView: View {
    @Environment(PilotModel.self) private var model
    @State private var title = ""

    var body: some View {
        ZStack {
            PilotTheme.background.ignoresSafeArea()
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 20) {
                    recordingCard
                    if let error = model.meetingError {
                        Label(error, systemImage: "exclamationmark.triangle.fill")
                            .font(.footnote)
                            .foregroundStyle(.orange)
                            .padding(14)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background(Color.orange.opacity(0.10), in: RoundedRectangle(cornerRadius: 16))
                    }
                    SectionTitle(
                        eyebrow: "PRIVATE MEETING MEMORY",
                        title: "Recent meetings",
                        trailing: "\(model.meetings.count)"
                    )
                    if model.meetings.isEmpty && model.isLoadingMeetings {
                        ProgressView("Loading meetings…")
                            .frame(maxWidth: .infinity)
                            .padding(32)
                    } else if model.meetings.isEmpty {
                        ContentUnavailableView(
                            "No meetings yet",
                            systemImage: "waveform.badge.mic",
                            description: Text("Start a recording above. Audio stays in your Pilot infrastructure.")
                        )
                        .padding(.vertical, 34)
                    } else {
                        ForEach(model.meetings) { meeting in
                            NavigationLink {
                                MeetingDetailView(meetingID: meeting.id)
                            } label: {
                                MeetingCard(meeting: meeting)
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }
                .frame(maxWidth: 900)
                .padding(18)
                .padding(.bottom, 100)
                .frame(maxWidth: .infinity)
            }
            .refreshable { await model.refreshMeetings() }
        }
        .navigationTitle("Meetings")
        .task { await model.refreshMeetings(silent: true) }
    }

    private var recordingCard: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(spacing: 13) {
                ZStack {
                    Circle().fill(Color.red.opacity(model.isRecordingMeeting ? 0.24 : 0.10))
                    Image(systemName: model.isRecordingMeeting ? "waveform" : "mic.fill")
                        .foregroundStyle(model.isRecordingMeeting ? .red : PilotTheme.cyan)
                }
                .frame(width: 48, height: 48)
                VStack(alignment: .leading, spacing: 2) {
                    Text(model.isRecordingMeeting ? "Recording in progress" : "Record a meeting")
                        .font(.headline)
                    if model.isRecordingMeeting, let started = model.meetingRecordingStartedAt {
                        Text(timerInterval: started ... .distantFuture, countsDown: false)
                            .font(.system(.subheadline, design: .monospaced, weight: .semibold))
                            .foregroundStyle(.red)
                    } else {
                        Text("Transcribed, summarised and indexed locally")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
                Spacer()
            }

            if !model.isRecordingMeeting {
                TextField("Meeting title", text: $title)
                    .textFieldStyle(.plain)
                    .padding(14)
                    .background(Color.black.opacity(0.20), in: RoundedRectangle(cornerRadius: 14))
                    .accessibilityLabel("Meeting title")
            }

            Button {
                if model.isRecordingMeeting {
                    Task { await model.stopAndProcessMeeting() }
                } else {
                    let meetingTitle = title
                    title = ""
                    Task { await model.startMeeting(title: meetingTitle) }
                }
                PilotHaptics.impact()
            } label: {
                Label(
                    model.isRecordingMeeting ? "Stop and process" : "Start recording",
                    systemImage: model.isRecordingMeeting ? "stop.fill" : "record.circle"
                )
                .font(.headline)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 13)
            }
            .buttonStyle(.plain)
            .foregroundStyle(.white)
            .background(
                model.isRecordingMeeting ? Color.red : PilotTheme.blue,
                in: RoundedRectangle(cornerRadius: 15)
            )
            .disabled(!model.isRecordingMeeting && title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
        }
        .padding(18)
        .background(PilotTheme.card, in: RoundedRectangle(cornerRadius: 24))
        .overlay { RoundedRectangle(cornerRadius: 24).stroke(PilotTheme.border) }
    }
}

private struct MeetingDetailView: View {
    @Environment(PilotModel.self) private var model
    let meetingID: String

    var body: some View {
        ZStack {
            PilotTheme.background.ignoresSafeArea()
            if model.isLoadingMeetingDetail && model.selectedMeeting?.id != meetingID {
                ProgressView("Loading private meeting record…")
            } else if let meeting = model.selectedMeeting, meeting.id == meetingID {
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 22) {
                        header(meeting)
                        if let summary = meeting.summary, !summary.isEmpty {
                            detailSection("Summary", symbol: "sparkles") {
                                Text(summary).foregroundStyle(.secondary)
                            }
                        }
                        if !meeting.actionItems.isEmpty {
                            detailSection("Action items", symbol: "checklist") {
                                ForEach(meeting.actionItems) { action in
                                    VStack(alignment: .leading, spacing: 7) {
                                        Text(action.task).font(.headline)
                                        HStack(spacing: 12) {
                                            if let owner = action.owner, !owner.isEmpty {
                                                Label(owner, systemImage: "person")
                                            }
                                            if let due = action.dueAt {
                                                Label(Self.date(due), systemImage: "calendar")
                                            }
                                            evidenceLabel(action.segmentIDs.count)
                                        }
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                    }
                                    .padding(.vertical, 5)
                                }
                            }
                        }
                        if !meeting.decisions.isEmpty {
                            detailSection("Decisions", symbol: "checkmark.seal") {
                                ForEach(meeting.decisions) { decision in
                                    VStack(alignment: .leading, spacing: 6) {
                                        Text(decision.summary)
                                        evidenceLabel(decision.segmentIDs.count)
                                            .font(.caption)
                                            .foregroundStyle(.secondary)
                                    }
                                    .padding(.vertical, 4)
                                }
                            }
                        }
                        detailSection("Transcript", symbol: "text.quote") {
                            if meeting.transcript.isEmpty {
                                Text("The timestamped transcript will appear after local processing.")
                                    .foregroundStyle(.secondary)
                            } else {
                                ForEach(meeting.transcript) { segment in
                                    HStack(alignment: .top, spacing: 12) {
                                        Text(Self.duration(segment.startMS))
                                            .font(.system(.caption, design: .monospaced))
                                            .foregroundStyle(PilotTheme.cyan)
                                            .frame(width: 48, alignment: .leading)
                                        VStack(alignment: .leading, spacing: 3) {
                                            Text(segment.speakerLabel)
                                                .font(.caption.weight(.semibold))
                                                .foregroundStyle(.secondary)
                                            Text(segment.text)
                                        }
                                    }
                                    .padding(.vertical, 5)
                                }
                            }
                        }
                    }
                    .frame(maxWidth: 900)
                    .padding(18)
                    .padding(.bottom, 60)
                    .frame(maxWidth: .infinity)
                }
                .refreshable { await model.loadMeeting(meetingID) }
            } else {
                ContentUnavailableView(
                    "Meeting unavailable",
                    systemImage: "exclamationmark.triangle",
                    description: Text(
                        model.meetingError ?? "Pilot Core could not load this meeting."
                    )
                )
            }
        }
        .navigationTitle("Meeting")
        .navigationBarTitleDisplayMode(.inline)
        .task { await model.loadMeeting(meetingID) }
    }

    private func header(_ meeting: PilotMeetingDetail) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(meeting.title).font(.largeTitle.bold())
            HStack(spacing: 14) {
                Label(Self.date(meeting.startedAt), systemImage: "calendar")
                Label(meeting.status.capitalized, systemImage: "lock.shield")
                if let recording = meeting.recording {
                    Label(
                        ByteCountFormatter.string(
                            fromByteCount: Int64(recording.sizeBytes),
                            countStyle: .file
                        ),
                        systemImage: "waveform"
                    )
                }
            }
            .font(.caption)
            .foregroundStyle(.secondary)
        }
    }

    private func detailSection<Content: View>(
        _ title: String,
        symbol: String,
        @ViewBuilder content: () -> Content
    ) -> some View {
        VStack(alignment: .leading, spacing: 13) {
            Label(title, systemImage: symbol)
                .font(.title3.bold())
                .foregroundStyle(PilotTheme.cyan)
            content()
        }
        .padding(18)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(PilotTheme.card, in: RoundedRectangle(cornerRadius: 22))
        .overlay { RoundedRectangle(cornerRadius: 22).stroke(PilotTheme.border) }
    }

    private func evidenceLabel(_ count: Int) -> some View {
        Label("\(count) source\(count == 1 ? "" : "s")", systemImage: "link")
    }

    private static func duration(_ milliseconds: Int) -> String {
        let seconds = max(0, milliseconds / 1000)
        return String(format: "%02d:%02d", seconds / 60, seconds % 60)
    }

    private static func date(_ value: String) -> String {
        let formatter = ISO8601DateFormatter()
        guard let date = formatter.date(from: value) else { return value }
        return date.formatted(date: .abbreviated, time: .shortened)
    }
}

private struct MeetingCard: View {
    let meeting: PilotMeeting

    var body: some View {
        VStack(alignment: .leading, spacing: 11) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 4) {
                    Text(meeting.title)
                        .font(.headline)
                    Text(Self.date(meeting.startedAt))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Label(meeting.statusLabel, systemImage: statusSymbol)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(statusColor)
            }
            if let summary = meeting.summary, !summary.isEmpty {
                Text(summary)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .lineLimit(4)
            }
            HStack(spacing: 18) {
                if let segments = meeting.transcriptSegmentCount {
                    Label("\(segments) segments", systemImage: "text.quote")
                }
                if let actions = meeting.actionItemCount {
                    Label("\(actions) actions", systemImage: "checklist")
                }
                if meeting.hasRecording == true {
                    Label("Audio", systemImage: "waveform")
                }
            }
            .font(.caption)
            .foregroundStyle(.tertiary)
        }
        .padding(17)
        .background(PilotTheme.card, in: RoundedRectangle(cornerRadius: 20))
        .overlay { RoundedRectangle(cornerRadius: 20).stroke(PilotTheme.border) }
    }

    private var statusColor: Color {
        switch meeting.status {
        case "ready": PilotTheme.mint
        case "failed": .orange
        case "processing", "transcribed": PilotTheme.cyan
        default: .secondary
        }
    }

    private var statusSymbol: String {
        switch meeting.status {
        case "ready": "checkmark.circle.fill"
        case "failed": "exclamationmark.triangle.fill"
        case "processing", "transcribed": "sparkles"
        default: "clock"
        }
    }

    private static func date(_ value: String) -> String {
        let formatter = ISO8601DateFormatter()
        guard let date = formatter.date(from: value) else { return value }
        return date.formatted(date: .abbreviated, time: .shortened)
    }
}

private struct AssistantView: View {
    @Environment(PilotModel.self) private var model
    @State private var prompt = ""
    @FocusState private var promptFocused: Bool

    private let suggestions = [
        "What's playing here?",
        "How much solar are we producing?",
        "Summarise the house",
    ]

    var body: some View {
        ZStack {
            PilotTheme.background.ignoresSafeArea()
            VStack(spacing: 0) {
                AssistantHeader()
                Divider().opacity(0.3)
                messages
                Composer(prompt: $prompt, isFocused: $promptFocused, send: send)
            }
            .frame(maxWidth: 900)
            .frame(maxWidth: .infinity)
        }
        .navigationTitle("Pilot")
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button {
                    model.startNewConversation()
                    PilotHaptics.impact()
                } label: {
                    Image(systemName: "square.and.pencil")
                }
                .accessibilityLabel("New conversation")
            }
        }
    }

    private var messages: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(spacing: 15) {
                    if model.messages.isEmpty {
                        AssistantWelcome()
                        suggestionChips
                    } else {
                        ForEach(model.messages) { message in
                            ChatBubble(message: message)
                                .id(message.id)
                        }
                    }
                    if model.isSendingMessage {
                        ThinkingBubble()
                            .id("thinking")
                    }
                }
                .padding(18)
            }
            .onChange(of: model.messages.count) {
                if let id = model.messages.last?.id {
                    withAnimation(.snappy) { proxy.scrollTo(id, anchor: .bottom) }
                }
            }
            .onChange(of: model.isSendingMessage) {
                if model.isSendingMessage {
                    withAnimation(.snappy) { proxy.scrollTo("thinking", anchor: .bottom) }
                }
            }
        }
    }

    private var suggestionChips: some View {
        VStack(spacing: 10) {
            ForEach(suggestions, id: \.self) { suggestion in
                Button {
                    prompt = suggestion
                    send()
                } label: {
                    HStack {
                        Text(suggestion)
                        Spacer()
                        Image(systemName: "arrow.up.right")
                            .foregroundStyle(PilotTheme.cyan)
                    }
                    .font(.subheadline.weight(.medium))
                    .padding(15)
                    .background(PilotTheme.card, in: RoundedRectangle(cornerRadius: 16))
                }
                .buttonStyle(.plain)
            }
        }
        .frame(maxWidth: 520)
    }

    private func send() {
        let value = prompt
        guard !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
        prompt = ""
        promptFocused = false
        PilotHaptics.impact()
        Task { await model.ask(value) }
    }
}

private struct AssistantHeader: View {
    @Environment(PilotModel.self) private var model

    var body: some View {
        HStack(spacing: 14) {
            ListeningOrb(isActive: model.isSendingMessage, size: 48)
            VStack(alignment: .leading, spacing: 2) {
                Text(model.isSendingMessage ? "Pilot is thinking" : "Pilot is ready")
                    .font(.headline)
                Text("Context: \(model.selectedRoom?.name ?? "choose a room")")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            Menu {
                ForEach(model.rooms) { room in
                    Button {
                        model.selectRoom(room.id)
                    } label: {
                        if room.id == model.selectedRoomID {
                            Label(room.name, systemImage: "checkmark")
                        } else {
                            Text(room.name)
                        }
                    }
                }
            } label: {
                Image(systemName: "location.circle.fill")
                    .font(.title2)
            }
            .accessibilityLabel("Change conversation room")
        }
        .padding(.horizontal, 18)
        .padding(.vertical, 12)
        .background(.ultraThinMaterial)
    }
}

private struct AssistantWelcome: View {
    var body: some View {
        VStack(spacing: 16) {
            ListeningOrb(isActive: false, size: 88)
            VStack(spacing: 6) {
                Text("What can I help with?")
                    .font(.system(.title2, design: .rounded, weight: .bold))
                Text("Ask about your home, energy, music, weather, or anything Pilot understands.")
                    .multilineTextAlignment(.center)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.vertical, 28)
        .frame(maxWidth: 520)
    }
}

private struct ChatBubble: View {
    let message: ChatMessage

    var body: some View {
        HStack(alignment: .bottom, spacing: 8) {
            if message.role == .user { Spacer(minLength: 54) }
            if message.role == .pilot {
                PilotMark(size: 28)
            }
            VStack(alignment: .leading, spacing: 5) {
                Text(message.text)
                    .textSelection(.enabled)
                Text(message.createdAt, format: .dateTime.hour().minute())
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            }
            .padding(.horizontal, 15)
            .padding(.vertical, 11)
            .background(
                bubbleColor,
                in: RoundedRectangle(cornerRadius: 19, style: .continuous)
            )
            if message.role == .pilot { Spacer(minLength: 54) }
        }
        .frame(maxWidth: .infinity)
        .accessibilityElement(children: .combine)
        .accessibilityLabel(
            "\(message.role == .user ? "You" : "Pilot"): \(message.text)"
        )
    }

    private var bubbleColor: Color {
        if message.isError { return Color.red.opacity(0.16) }
        return message.role == .user
            ? PilotTheme.blue.opacity(0.28)
            : Color.white.opacity(0.08)
    }
}

private struct ThinkingBubble: View {
    @State private var phase = false

    var body: some View {
        HStack(spacing: 10) {
            PilotMark(size: 28)
            HStack(spacing: 5) {
                ForEach(0..<3, id: \.self) { index in
                    Circle()
                        .fill(PilotTheme.cyan)
                        .frame(width: 7, height: 7)
                        .scaleEffect(phase ? 1 : 0.55)
                        .animation(
                            .easeInOut(duration: 0.65)
                                .repeatForever()
                                .delay(Double(index) * 0.14),
                            value: phase
                        )
                }
            }
            .padding(.horizontal, 15)
            .padding(.vertical, 14)
            .background(Color.white.opacity(0.08), in: Capsule())
            Spacer()
        }
        .onAppear { phase = true }
        .accessibilityLabel("Pilot is thinking")
    }
}

private struct Composer: View {
    @Environment(PilotModel.self) private var model
    @Binding var prompt: String
    var isFocused: FocusState<Bool>.Binding
    let send: () -> Void

    var body: some View {
        HStack(alignment: .bottom, spacing: 10) {
            TextField("Message Pilot", text: $prompt, axis: .vertical)
                .focused(isFocused)
                .lineLimit(1...5)
                .submitLabel(.send)
                .onSubmit(send)
                .padding(.horizontal, 15)
                .padding(.vertical, 12)
                .background(Color.white.opacity(0.08), in: RoundedRectangle(cornerRadius: 20))
            Button(action: send) {
                Image(systemName: "arrow.up")
                    .font(.headline.weight(.bold))
                    .frame(width: 44, height: 44)
                    .background(
                        prompt.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                            ? Color.secondary.opacity(0.25)
                            : PilotTheme.cyan,
                        in: Circle()
                    )
                    .foregroundStyle(.black)
            }
            .disabled(
                prompt.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                    || model.isSendingMessage
            )
            .accessibilityLabel("Send message")
        }
        .padding(12)
        .background(.ultraThinMaterial)
    }
}

private struct NowPlayingView: View {
    @Environment(PilotModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var volume = 30.0

    private var state: PilotPlayerState? { model.selectedPlayer }

    var body: some View {
        NavigationStack {
            ZStack {
                PilotTheme.background.ignoresSafeArea()
                ScrollView {
                    VStack(spacing: 24) {
                        ArtworkTile(media: state?.effective.media, size: 250)
                            .shadow(color: PilotTheme.cyan.opacity(0.15), radius: 35)
                        VStack(spacing: 7) {
                            Text(state?.effective.media?.title ?? "Nothing playing")
                                .font(.system(.title, design: .rounded, weight: .bold))
                                .multilineTextAlignment(.center)
                            Text(state?.effective.media?.artist ?? state?.player.name ?? "Pilot")
                                .font(.title3)
                                .foregroundStyle(.secondary)
                            if let album = state?.effective.media?.album {
                                Text(album)
                                    .font(.subheadline)
                                    .foregroundStyle(.tertiary)
                            }
                        }

                        HStack(spacing: 38) {
                            MediaButton(symbol: "stop.fill", label: "Stop", size: 48) {
                                Task { await model.command("stop") }
                            }
                            MediaButton(
                                symbol: state?.effective.playbackState == "playing"
                                    ? "pause.fill" : "play.fill",
                                label: state?.effective.playbackState == "playing"
                                    ? "Pause" : "Play",
                                size: 70,
                                prominent: true
                            ) {
                                let action = state?.effective.playbackState == "playing"
                                    ? "pause" : "play"
                                Task { await model.command(action) }
                            }
                            Menu {
                                ForEach(model.rooms.filter { $0.id != model.selectedRoomID }) { room in
                                    Button(room.name) {
                                        Task { await model.transfer(to: room.id) }
                                    }
                                }
                            } label: {
                                Image(systemName: "airplayaudio")
                                    .frame(width: 48, height: 48)
                                    .background(Color.white.opacity(0.08), in: Circle())
                            }
                            .accessibilityLabel("Move music to another room")
                        }

                        VStack(spacing: 12) {
                            HStack {
                                Image(systemName: "speaker.fill")
                                Slider(value: $volume, in: 0...100, step: 1) { editing in
                                    if !editing {
                                        PilotHaptics.selection()
                                        Task {
                                            await model.command("set_volume", volume: Int(volume))
                                        }
                                    }
                                }
                                Image(systemName: "speaker.wave.3.fill")
                            }
                            Text("\(Int(volume))% · \(model.selectedRoom?.name ?? "No room")")
                                .font(.caption.monospacedDigit())
                                .foregroundStyle(.secondary)
                        }
                        .pilotCard()
                    }
                    .frame(maxWidth: 560)
                    .padding(24)
                    .frame(maxWidth: .infinity)
                }
            }
            .navigationTitle("Now Playing")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                }
            }
            .onAppear {
                volume = Double(state?.effective.volumePercent ?? 30)
            }
            .onChange(of: model.selectedRoomID) {
                volume = Double(state?.effective.volumePercent ?? 30)
            }
        }
    }
}

private struct MiniPlayerBar: View {
    @Environment(PilotModel.self) private var model
    @Binding var showingNowPlaying: Bool

    private var state: PilotPlayerState? { model.activePlayer }

    var body: some View {
        if let state {
            HStack(spacing: 12) {
                Button {
                    showingNowPlaying = true
                } label: {
                    HStack(spacing: 11) {
                        ArtworkTile(media: state.effective.media, size: 42)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(state.effective.media?.title ?? state.player.name)
                                .font(.subheadline.weight(.semibold))
                                .lineLimit(1)
                            Text(state.effective.media?.artist ?? state.player.name)
                                .font(.caption)
                                .foregroundStyle(.secondary)
                                .lineLimit(1)
                        }
                    }
                }
                .buttonStyle(.plain)
                Spacer(minLength: 6)
                Button {
                    let action = state.effective.playbackState == "playing" ? "pause" : "play"
                    if state.player.roomID != model.selectedRoomID {
                        model.selectRoom(state.player.roomID)
                    }
                    Task { await model.command(action) }
                } label: {
                    Image(
                        systemName: state.effective.playbackState == "playing"
                            ? "pause.fill" : "play.fill"
                    )
                    .frame(width: 38, height: 38)
                }
                .buttonStyle(.plain)
                .accessibilityLabel(
                    state.effective.playbackState == "playing" ? "Pause" : "Play"
                )
            }
            .padding(8)
            .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 17))
            .overlay { RoundedRectangle(cornerRadius: 17).stroke(PilotTheme.border) }
            .shadow(color: .black.opacity(0.22), radius: 15, y: 6)
        }
    }
}

private struct SettingsView: View {
    @Environment(PilotModel.self) private var model
    var isInitialSetup = false
    @State private var validationResult: Bool?

    var body: some View {
        @Bindable var model = model
        ZStack {
            PilotTheme.background.ignoresSafeArea()
            Form {
                Section {
                    HStack(spacing: 14) {
                        PilotMark(size: 50)
                        VStack(alignment: .leading, spacing: 3) {
                            Text("Pilot Core")
                                .font(.headline)
                            Text(model.status)
                                .font(.subheadline)
                                .foregroundStyle(
                                    model.connectionState.isConnected
                                        ? PilotTheme.mint : .secondary
                                )
                        }
                    }
                    .padding(.vertical, 4)
                }
                .listRowBackground(Color.white.opacity(0.06))

                Section("Connection") {
                    TextField("Core URL", text: $model.coreURL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .keyboardType(.URL)
                        .accessibilityLabel("Pilot Core URL")
                    TextField("Device ID", text: $model.deviceID)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    SecureField("Device token", text: $model.token)
                        .textContentType(.password)
                }
                .listRowBackground(Color.white.opacity(0.06))

                Section {
                    Button {
                        validationResult = nil
                        Task {
                            validationResult = await model.connect()
                            validationResult == true
                                ? PilotHaptics.success()
                                : PilotHaptics.error()
                        }
                    } label: {
                        HStack {
                            Text(isInitialSetup ? "Connect to Pilot" : "Save and test connection")
                                .fontWeight(.semibold)
                            Spacer()
                            if model.isRefreshing {
                                ProgressView().controlSize(.small)
                            } else if let validationResult {
                                Image(
                                    systemName: validationResult
                                        ? "checkmark.circle.fill"
                                        : "exclamationmark.circle.fill"
                                )
                                .foregroundStyle(validationResult ? PilotTheme.mint : .red)
                            }
                        }
                    }
                    .disabled(!model.isConfigured || model.isRefreshing)
                }
                .listRowBackground(PilotTheme.cyan.opacity(0.13))

                if !isInitialSetup {
                    Section("Room context") {
                        Picker(
                            "Default room",
                            selection: Binding(
                                get: { model.selectedRoomID },
                                set: { model.selectRoom($0) }
                            )
                        ) {
                            ForEach(model.rooms) { room in
                                Text(room.name).tag(room.id)
                            }
                        }
                    }
                    .listRowBackground(Color.white.opacity(0.06))

                    Section("About") {
                        LabeledContent("Client", value: "iOS / iPadOS")
                        LabeledContent("Authority", value: "Pilot Core")
                        if let lastRefresh = model.lastSuccessfulRefresh {
                            LabeledContent(
                                "Last update",
                                value: lastRefresh.formatted(
                                    date: .omitted,
                                    time: .shortened
                                )
                            )
                        }
                    }
                    .listRowBackground(Color.white.opacity(0.06))

                    Section {
                        Text("This client never connects directly to Home Assistant, Music Assistant, Ollama, receivers, or room endpoints.")
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    }
                    .listRowBackground(Color.clear)
                }
            }
            .scrollContentBackground(.hidden)
        }
        .navigationTitle(isInitialSetup ? "Set up Pilot" : "Settings")
    }
}

private struct OnboardingView: View {
    @Environment(PilotModel.self) private var model

    var body: some View {
        NavigationStack {
            ZStack {
                PilotTheme.background.ignoresSafeArea()
                ScrollView {
                    VStack(spacing: 28) {
                        VStack(spacing: 18) {
                            PilotMark(size: 92)
                            VStack(spacing: 8) {
                                Text("Welcome to Pilot")
                                    .font(.system(.largeTitle, design: .rounded, weight: .bold))
                                Text("Your private interface for home intelligence, media, energy and voice.")
                                    .font(.title3)
                                    .foregroundStyle(.secondary)
                                    .multilineTextAlignment(.center)
                            }
                        }
                        .padding(.top, 28)

                        HStack(spacing: 10) {
                            OnboardingFeature(symbol: "lock.shield.fill", title: "Private")
                            OnboardingFeature(symbol: "house.lodge.fill", title: "Room-aware")
                            OnboardingFeature(symbol: "waveform", title: "Contextual")
                        }

                        SettingsView(isInitialSetup: true)
                            .frame(minHeight: 430)
                            .background(Color.clear)
                    }
                    .frame(maxWidth: 680)
                    .padding(20)
                    .frame(maxWidth: .infinity)
                }
            }
        }
    }
}

private struct OnboardingFeature: View {
    let symbol: String
    let title: String

    var body: some View {
        VStack(spacing: 8) {
            Image(systemName: symbol)
                .font(.title2)
                .foregroundStyle(PilotTheme.cyan)
            Text(title)
                .font(.caption.weight(.semibold))
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 16)
        .background(PilotTheme.card, in: RoundedRectangle(cornerRadius: 18))
    }
}

private struct ConnectionPill: View {
    @Environment(PilotModel.self) private var model
    var compact = false

    var body: some View {
        HStack(spacing: 7) {
            Circle()
                .fill(color)
                .frame(width: 8, height: 8)
                .shadow(color: color.opacity(0.7), radius: 4)
            if !compact {
                Text(model.status)
                    .lineLimit(1)
            }
        }
        .font(.caption.weight(.semibold))
        .padding(.horizontal, compact ? 9 : 12)
        .padding(.vertical, 8)
        .background(.ultraThinMaterial, in: Capsule())
        .accessibilityLabel("Pilot Core \(model.status)")
    }

    private var color: Color {
        switch model.connectionState {
        case .connected: PilotTheme.mint
        case .connecting: PilotTheme.amber
        case .notConfigured, .offline: .red
        }
    }
}

private struct OfflineBanner: View {
    @Environment(PilotModel.self) private var model

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: "wifi.exclamationmark")
                .font(.title3)
                .foregroundStyle(PilotTheme.amber)
            VStack(alignment: .leading, spacing: 3) {
                Text(model.lastSuccessfulRefresh == nil ? "Pilot Core is unavailable" : "Showing last known state")
                    .font(.headline)
                Text(model.status)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            Button("Retry") { Task { await model.refresh() } }
                .buttonStyle(.bordered)
        }
        .pilotCard()
    }
}

private struct EmptyRoomsView: View {
    var body: some View {
        ContentUnavailableView(
            "No rooms available",
            systemImage: "house.slash",
            description: Text("Connect to Pilot Core or ask an administrator to register a room.")
        )
        .frame(maxWidth: .infinity)
        .pilotCard()
    }
}

private struct RoomSkeletonGrid: View {
    var body: some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 260), spacing: 16)], spacing: 16) {
            ForEach(0..<2, id: \.self) { _ in
                RoundedRectangle(cornerRadius: 24)
                    .fill(Color.white.opacity(0.07))
                    .frame(height: 178)
                    .overlay { ProgressView() }
            }
        }
    }
}

private struct SearchRowSkeleton: View {
    var body: some View {
        HStack(spacing: 12) {
            RoundedRectangle(cornerRadius: 12)
                .fill(Color.white.opacity(0.08))
                .frame(width: 50, height: 50)
            VStack(alignment: .leading, spacing: 8) {
                RoundedRectangle(cornerRadius: 4)
                    .fill(Color.white.opacity(0.10))
                    .frame(width: 170, height: 12)
                RoundedRectangle(cornerRadius: 4)
                    .fill(Color.white.opacity(0.06))
                    .frame(width: 110, height: 10)
            }
            Spacer()
        }
        .padding(12)
        .background(PilotTheme.card, in: RoundedRectangle(cornerRadius: 18))
    }
}

private struct SectionTitle: View {
    let eyebrow: String
    let title: String
    var trailing: String? = nil

    var body: some View {
        HStack(alignment: .lastTextBaseline) {
            VStack(alignment: .leading, spacing: 3) {
                Text(eyebrow)
                    .font(.caption2.weight(.bold))
                    .tracking(1.4)
                    .foregroundStyle(PilotTheme.cyan)
                if !title.isEmpty {
                    Text(title)
                        .font(.title2.weight(.bold))
                }
            }
            Spacer()
            if let trailing {
                Text(trailing)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
    }
}

private struct PilotMark: View {
    let size: CGFloat

    var body: some View {
        ZStack {
            Circle()
                .fill(
                    AngularGradient(
                        colors: [PilotTheme.cyan, PilotTheme.blue, PilotTheme.violet, PilotTheme.cyan],
                        center: .center
                    )
                )
            Image(systemName: "waveform")
                .font(.system(size: size * 0.38, weight: .bold))
                .foregroundStyle(.white)
        }
        .frame(width: size, height: size)
        .shadow(color: PilotTheme.cyan.opacity(0.25), radius: size * 0.18)
        .accessibilityHidden(true)
    }
}

private struct ListeningOrb: View {
    let isActive: Bool
    let size: CGFloat
    @State private var animate = false

    var body: some View {
        ZStack {
            ForEach(0..<3, id: \.self) { ring in
                Circle()
                    .stroke(
                        [PilotTheme.cyan, PilotTheme.blue, PilotTheme.violet][ring]
                            .opacity(0.42),
                        lineWidth: max(2, size * 0.045)
                    )
                    .scaleEffect(animate && isActive ? 1.0 + CGFloat(ring) * 0.09 : 0.76)
                    .rotationEffect(.degrees(animate ? Double(120 * (ring + 1)) : 0))
            }
            PilotMark(size: size * 0.66)
        }
        .frame(width: size, height: size)
        .animation(
            isActive
                ? .easeInOut(duration: 1.0).repeatForever(autoreverses: true)
                : .easeOut(duration: 0.3),
            value: animate
        )
        .onAppear { animate = true }
        .accessibilityLabel(isActive ? "Pilot is thinking" : "Pilot is ready")
    }
}

private struct ArtworkTile: View {
    let media: CurrentMedia?
    let size: CGFloat

    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: size * 0.20, style: .continuous)
                .fill(
                    LinearGradient(
                        colors: [
                            PilotTheme.violet.opacity(0.85),
                            PilotTheme.blue.opacity(0.82),
                            PilotTheme.cyan.opacity(0.72),
                        ],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    )
                )
            Circle()
                .stroke(Color.white.opacity(0.16), lineWidth: max(1, size * 0.015))
                .frame(width: size * 0.58, height: size * 0.58)
            Image(systemName: media == nil ? "music.note" : "waveform")
                .font(.system(size: size * 0.26, weight: .bold))
                .foregroundStyle(.white.opacity(0.92))
        }
        .frame(width: size, height: size)
        .accessibilityHidden(true)
    }
}

private struct AsyncArtwork: View {
    let url: URL?
    let symbol: String

    var body: some View {
        AsyncImage(url: url) { phase in
            switch phase {
            case let .success(image):
                image.resizable().scaledToFill()
            default:
                ZStack {
                    LinearGradient(
                        colors: [PilotTheme.violet.opacity(0.7), PilotTheme.blue.opacity(0.7)],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    )
                    Image(systemName: symbol).foregroundStyle(.white)
                }
            }
        }
        .clipShape(RoundedRectangle(cornerRadius: 12))
    }
}

private struct MediaButton: View {
    let symbol: String
    let label: String
    let size: CGFloat
    var prominent = false
    let action: () -> Void

    var body: some View {
        Button {
            PilotHaptics.impact()
            action()
        } label: {
            Image(systemName: symbol)
                .font(.system(size: size * 0.34, weight: .bold))
                .frame(width: size, height: size)
                .background(
                    prominent ? PilotTheme.cyan : Color.white.opacity(0.08),
                    in: Circle()
                )
                .foregroundStyle(prominent ? .black : .white)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(label)
    }
}

private struct AvailabilityDot: View {
    let available: Bool?

    var body: some View {
        HStack(spacing: 6) {
            Circle()
                .fill(available == false ? Color.red : PilotTheme.mint)
                .frame(width: 7, height: 7)
            Text(available == false ? "Offline" : "Online")
        }
        .font(.caption2.weight(.semibold))
        .foregroundStyle(.secondary)
    }
}

private extension View {
    func pilotCard() -> some View {
        self
            .padding(18)
            .background(
                PilotTheme.card,
                in: RoundedRectangle(cornerRadius: 24, style: .continuous)
            )
            .overlay {
                RoundedRectangle(cornerRadius: 24, style: .continuous)
                    .stroke(PilotTheme.border, lineWidth: 1)
            }
    }
}

@MainActor
enum PilotHaptics {
    static func selection() {
        UISelectionFeedbackGenerator().selectionChanged()
    }

    static func impact() {
        UIImpactFeedbackGenerator(style: .soft).impactOccurred()
    }

    static func success() {
        UINotificationFeedbackGenerator().notificationOccurred(.success)
    }

    static func error() {
        UINotificationFeedbackGenerator().notificationOccurred(.error)
    }
}

#Preview("iPhone") {
    RootView()
        .environment(PilotModel.preview())
}

#Preview("iPad", traits: .fixedLayout(width: 1_024, height: 768)) {
    RootView()
        .environment(PilotModel.preview())
}
