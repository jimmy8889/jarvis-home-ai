import SwiftUI
import UIKit
import VisionKit
import Charts
import WebKit

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

enum EnergyScenePolicy {
    static let vehicleFlowDeadbandWatts = 100.0

    static func vehicleIsDrawingPower(_ watts: Double?) -> Bool {
        abs(watts ?? 0) > vehicleFlowDeadbandWatts
    }

    static func houseAsset(solarWatts: Double?, vehicleConnected: Bool) -> String {
        let daytime = (solarWatts ?? 0) > 100
        switch (daytime, vehicleConnected) {
        case (true, true): return "SolarHouseTeslaDay"
        case (true, false): return "SolarHouseDay"
        case (false, true): return "SolarHouseTesla"
        case (false, false): return "SolarHouse"
        }
    }
}

struct RootView: View {
    @Environment(PilotModel.self) private var model
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass
    @Environment(\.scenePhase) private var scenePhase
    @State private var section: PilotSection? = .home
    @State private var showingNowPlaying = false

    var body: some View {
        Group {
            if model.hasActiveConfiguration {
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
                    .safeAreaInset(edge: .bottom, spacing: 8) {
                        MiniPlayerBar(showingNowPlaying: $showingNowPlaying)
                            .padding(.horizontal, 10)
                    }
                    .tag(item)
                    .tabItem { Label(item.title, systemImage: item.symbol) }
                }
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

                    PilotEnergyDashboardCard()
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
                trailing: statusLabel
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
            if let battery = snapshot.batteryWatts {
                Label(
                    "Battery \(battery >= 25 ? "supplying" : battery <= -25 ? "charging" : "idle") · \(Self.power(battery))",
                    systemImage: battery >= 25 ? "battery.75percent" : "bolt.fill"
                )
                .font(.caption.weight(.semibold))
                .foregroundStyle(PilotTheme.mint)
            }
        }
    }

    private var statusLabel: String {
        if let observed = snapshot.observedAt {
            return snapshot.status == .live
                ? observed.formatted(date: .omitted, time: .shortened)
                : "Last update \(observed.formatted(date: .omitted, time: .shortened))"
        }
        return switch snapshot.status {
        case .live: "Live"
        case .stale: "Partial"
        case .unavailable: "Unavailable"
        }
    }

    private static func power(_ watts: Double) -> String {
        if abs(watts) >= 1_000 { return String(format: "%.1f kW", abs(watts) / 1_000) }
        return String(format: "%.0f W", abs(watts))
    }
}

private struct PilotEnergyDashboardCard: View {
    @Environment(PilotModel.self) private var model
    @State private var page = DashboardPage.flow

    private enum DashboardPage: String, CaseIterable, Identifiable {
        case flow = "Flow"
        case history = "History"
        case daily = "Daily"
        case climate = "Climate"
        var id: String { rawValue }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack {
                SectionTitle(
                    eyebrow: "JAMES HOUSE",
                    title: "Energy & climate",
                    trailing: model.dashboard.status == "ok" ? "Live" : "Last known"
                )
                Spacer(minLength: 0)
                Circle()
                    .fill(model.dashboard.status == "ok" ? PilotTheme.mint : PilotTheme.amber)
                    .frame(width: 9, height: 9)
            }
            Picker("Dashboard page", selection: $page) {
                ForEach(DashboardPage.allCases) { Text($0.rawValue).tag($0) }
            }
            .pickerStyle(.segmented)

            Group {
                switch page {
                case .flow: EnergyFlowPage(snapshot: model.dashboard)
                case .history: EnergyHistoryPage(snapshot: model.dashboard)
                case .daily: DailyEnergyPage(snapshot: model.dashboard)
                case .climate: ClimatePage(snapshot: model.dashboard)
                }
            }
            .animation(.smooth(duration: 0.32), value: page)

            if let error = model.dashboardError {
                Label(error, systemImage: "exclamationmark.triangle.fill")
                    .font(.caption)
                    .foregroundStyle(PilotTheme.amber)
            }
        }
        .pilotCard()
        .task { await model.refreshDashboard(silent: true) }
    }
}

private struct EnergyFlowPage: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    let snapshot: DashboardSnapshot

    private var houseAsset: String {
        EnergyScenePolicy.houseAsset(
            solarWatts: snapshot.power.solarWatts,
            vehicleConnected: snapshot.vehicle.connected == true
        )
    }

    private var vehiclePower: Double? {
        snapshot.vehicle.powerWatts ?? snapshot.power.vehicleWatts
    }

    private var vehicleDrawingPower: Bool {
        EnergyScenePolicy.vehicleIsDrawingPower(vehiclePower)
    }

    private var gridExporting: Bool {
        snapshot.power.directions["grid"] == "exporting" || (snapshot.power.gridWatts ?? 0) < -100
    }

    private var batteryStatus: String {
        guard abs(snapshot.power.batteryWatts ?? 0) > 25 else { return "Idle" }
        return snapshot.power.directions["battery"] == "charging" || (snapshot.power.batteryWatts ?? 0) < -25
            ? "Charging"
            : "Supplying"
    }

    var body: some View {
        VStack(spacing: 15) {
            HStack(spacing: 0) {
                DailySummaryMetric("Generated", snapshot.daily.solarGeneratedKWh, PilotTheme.amber)
                Divider().frame(height: 48)
                DailySummaryMetric("Home used", snapshot.daily.homeUsedKWh, PilotTheme.mint)
                Divider().frame(height: 48)
                DailySummaryMetric("Exported", snapshot.daily.gridExportedKWh, PilotTheme.cyan)
            }
            .padding(.vertical, 10)
            .background(Color.black.opacity(0.16), in: RoundedRectangle(cornerRadius: 16))

            GeometryReader { proxy in
                ZStack {
                    RoundedRectangle(cornerRadius: 20)
                        .fill(Color.black.opacity(0.20))

                    Image(houseAsset)
                        .interpolation(.high)
                        .resizable()
                        .scaledToFit()
                        .frame(width: proxy.size.width * 1.04)
                        .position(x: proxy.size.width * 0.50, y: proxy.size.height * 0.46)
                        .id(houseAsset)
                        .transition(.opacity)
                        .accessibilityHidden(true)

                    LinearGradient(
                        colors: [.black.opacity(0.10), .clear, .black.opacity(0.24)],
                        startPoint: .top,
                        endPoint: .bottom
                    )

                    EnergyFlowLines(power: snapshot.power, vehiclePower: vehiclePower)
                    EnergySceneMetric(
                        title: "PV",
                        value: Self.power(snapshot.power.solarWatts),
                        detail: abs(snapshot.power.solarWatts ?? 0) > 25 ? "Producing" : "Idle",
                        color: PilotTheme.amber,
                        symbol: "sun.max.fill"
                    )
                        .position(x: proxy.size.width * 0.52, y: proxy.size.height * 0.08)
                    EnergySceneMetric(
                        title: "GRID",
                        value: Self.power(snapshot.power.gridWatts.map(abs)),
                        detail: gridExporting ? "Export" : "Import",
                        color: PilotTheme.cyan,
                        symbol: "transmission"
                    )
                    .position(x: proxy.size.width * 0.88, y: proxy.size.height * 0.18)
                    EnergySceneMetric(
                        title: "HOME",
                        value: Self.power(snapshot.power.homeLoadWatts),
                        detail: "Consuming",
                        color: PilotTheme.mint,
                        symbol: "house.fill"
                    )
                        .position(x: proxy.size.width * 0.56, y: proxy.size.height * 0.82)
                    AnimatedHomeBatteryNode(
                        stateOfCharge: snapshot.power.batteryStateOfCharge,
                        powerWatts: snapshot.power.batteryWatts,
                        direction: snapshot.power.directions["battery"]
                    )
                    .position(x: proxy.size.width * 0.76, y: proxy.size.height * 0.65)
                    if snapshot.vehicle.connected == true {
                        EnergySceneMetric(
                            title: "TESLA",
                            value: vehicleDrawingPower ? Self.power(vehiclePower) : "Plugged in",
                            detail: vehicleDrawingPower ? "Charging" : nil,
                            color: .red,
                            symbol: "car.fill"
                        )
                            .position(x: proxy.size.width * 0.18, y: proxy.size.height * 0.72)
                    }
                    AnimatedServerRackNode(powerWatts: snapshot.power.serverRackWatts)
                        .position(x: proxy.size.width * 0.91, y: proxy.size.height * 0.76)
                }
                .clipShape(RoundedRectangle(cornerRadius: 20))
                .overlay { RoundedRectangle(cornerRadius: 20).stroke(.white.opacity(0.08)) }
                .animation(reduceMotion ? nil : .easeInOut(duration: 0.45), value: houseAsset)
            }
            .frame(height: 360)

            HStack(spacing: 14) {
                VStack(alignment: .leading, spacing: 4) {
                    Label("Jarvis", systemImage: snapshot.vehicle.connected == true ? "bolt.car.fill" : "car.fill")
                        .font(.caption.weight(.bold))
                        .foregroundStyle(snapshot.vehicle.connected == true ? PilotTheme.mint : .secondary)
                    Text(snapshot.vehicle.stateOfCharge.map { "\(Int($0))%" } ?? "—")
                        .font(.title2.monospacedDigit().bold())
                    Text(snapshot.vehicle.connected == true
                         ? (vehicleDrawingPower ? "Plugged in · charging" : "Plugged in")
                         : "Not plugged in")
                        .font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                if let soc = snapshot.power.batteryStateOfCharge {
                    VStack(alignment: .trailing, spacing: 4) {
                        Label("Home battery", systemImage: "battery.75percent")
                            .font(.caption.weight(.bold)).foregroundStyle(PilotTheme.mint)
                        Text("\(Int(soc))%")
                            .font(.title2.monospacedDigit().bold())
                        Text(batteryStatus)
                            .font(.caption).foregroundStyle(.secondary)
                    }
                }
            }
        }
    }

    private static func power(_ watts: Double?) -> String {
        guard let watts else { return "—" }
        return abs(watts) >= 1_000
            ? String(format: "%.2f kW", abs(watts) / 1_000)
            : String(format: "%.0f W", abs(watts))
    }
}

private struct EnergyFlowLines: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    let power: DashboardPower
    let vehiclePower: Double?

    @ViewBuilder
    var body: some View {
        Group {
            if reduceMotion {
                Canvas { context, size in
                    render(context: &context, size: size, date: nil)
                }
            } else {
                TimelineView(.animation(minimumInterval: 1 / 30)) { timeline in
                    Canvas { context, size in
                        render(context: &context, size: size, date: timeline.date)
                    }
                }
            }
        }
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }

    private func render(context: inout GraphicsContext, size: CGSize, date: Date?) {
        let hub = (0.59, 0.68)
        drawFlow(
            context: &context,
            points: route([(0.52, 0.17), (0.59, 0.17), hub], size: size),
            color: PilotTheme.amber,
            watts: power.solarWatts,
            threshold: 25,
            active: flowIsActive("solar", watts: power.solarWatts, threshold: 25),
            forward: true,
            date: date
        )
        drawFlow(
            context: &context,
            points: route([hub, (0.86, 0.68), (0.86, 0.27)], size: size),
            color: PilotTheme.cyan,
            watts: power.gridWatts,
            threshold: 100,
            active: flowIsActive("grid", watts: power.gridWatts, threshold: 100),
            forward: power.directions["grid"] == "exporting" || (power.gridWatts ?? 0) < -100,
            date: date
        )
        drawFlow(
            context: &context,
            points: route([hub, (0.56, 0.76)], size: size),
            color: PilotTheme.mint,
            watts: power.homeLoadWatts,
            threshold: 25,
            active: flowIsActive("home", watts: power.homeLoadWatts, threshold: 25),
            forward: true,
            date: date
        )
        drawFlow(
            context: &context,
            points: route([hub, (0.75, 0.68), (0.75, 0.57)], size: size),
            color: PilotTheme.mint,
            watts: power.batteryWatts,
            threshold: 25,
            active: flowIsActive("battery", watts: power.batteryWatts, threshold: 25),
            forward: power.directions["battery"] == "charging" || (power.batteryWatts ?? 0) < -25,
            date: date
        )
        drawFlow(
            context: &context,
            points: route([hub, (0.22, 0.68)], size: size),
            color: .red,
            watts: vehiclePower,
            threshold: EnergyScenePolicy.vehicleFlowDeadbandWatts,
            active: flowIsActive(
                "vehicle",
                watts: vehiclePower,
                threshold: EnergyScenePolicy.vehicleFlowDeadbandWatts
            ),
            forward: true,
            date: date
        )
        drawFlow(
            context: &context,
            points: route([hub, (0.88, 0.68)], size: size),
            color: PilotTheme.violet,
            watts: power.serverRackWatts,
            threshold: 25,
            active: flowIsActive("server_rack", watts: power.serverRackWatts, threshold: 25),
            forward: true,
            date: date
        )
    }

    private func flowIsActive(_ key: String, watts: Double?, threshold: Double) -> Bool {
        let aboveDeadband = abs(watts ?? 0) > threshold
        return aboveDeadband && (power.flowActive[key] ?? aboveDeadband)
    }

    private func route(_ coordinates: [(Double, Double)], size: CGSize) -> [CGPoint] {
        let anchors = coordinates.map { CGPoint(x: size.width * $0.0, y: size.height * $0.1) }
        guard anchors.count > 2 else { return anchors }
        var result = [anchors[0]]
        for index in 1..<(anchors.count - 1) {
            let previous = anchors[index - 1]
            let corner = anchors[index]
            let next = anchors[index + 1]
            let incoming = hypot(corner.x - previous.x, corner.y - previous.y)
            let outgoing = hypot(next.x - corner.x, next.y - corner.y)
            guard incoming > 0, outgoing > 0 else { continue }
            let radius = min(12, incoming * 0.35, outgoing * 0.35)
            let before = CGPoint(
                x: corner.x - (corner.x - previous.x) / incoming * radius,
                y: corner.y - (corner.y - previous.y) / incoming * radius
            )
            let after = CGPoint(
                x: corner.x + (next.x - corner.x) / outgoing * radius,
                y: corner.y + (next.y - corner.y) / outgoing * radius
            )
            result.append(before)
            for step in 1...6 {
                let t = Double(step) / 6
                let mt = 1 - t
                result.append(CGPoint(
                    x: mt * mt * before.x + 2 * mt * t * corner.x + t * t * after.x,
                    y: mt * mt * before.y + 2 * mt * t * corner.y + t * t * after.y
                ))
            }
        }
        if let last = anchors.last { result.append(last) }
        return result
    }

    private func drawFlow(
        context: inout GraphicsContext,
        points: [CGPoint],
        color: Color,
        watts: Double?,
        threshold: Double,
        active: Bool,
        forward: Bool,
        date: Date?
    ) {
        guard let first = points.first else { return }
        var path = Path()
        path.move(to: first)
        for point in points.dropFirst() { path.addLine(to: point) }
        let magnitude = abs(watts ?? 0)
        let strength = min(1, max(0.16, magnitude / 7_500))
        context.stroke(
            path,
            with: .color(color.opacity(active ? 0.25 + strength * 0.28 : 0.10)),
            style: StrokeStyle(
                lineWidth: active ? 2.1 + strength * 1.8 : 1.4,
                lineCap: .round,
                lineJoin: .round
            )
        )
        guard active, magnitude > threshold, let date else { return }
        let speed = min(1.25, max(0.22, magnitude / 5_000))
        let period = 3.2 / speed
        let phase = date.timeIntervalSinceReferenceDate.truncatingRemainder(dividingBy: period) / period
        for offset in [0.0, 0.5] {
            let start = (phase + offset).truncatingRemainder(dividingBy: 1)
            let end = start + 0.09
            drawGlow(context: &context, points: points, color: color, from: start, to: min(1, end), forward: forward)
            if end > 1 {
                drawGlow(context: &context, points: points, color: color, from: 0, to: end - 1, forward: forward)
            }
        }
    }

    private func drawGlow(
        context: inout GraphicsContext,
        points: [CGPoint],
        color: Color,
        from start: Double,
        to end: Double,
        forward: Bool
    ) {
        guard end > start else { return }
        let samples = (0...8).map { step -> CGPoint in
            let progress = start + (end - start) * Double(step) / 8
            return point(on: points, progress: forward ? progress : 1 - progress)
        }
        guard let first = samples.first else { return }
        var glow = Path()
        glow.move(to: first)
        for sample in samples.dropFirst() { glow.addLine(to: sample) }
        context.stroke(glow, with: .color(color.opacity(0.14)), style: StrokeStyle(lineWidth: 12, lineCap: .round, lineJoin: .round))
        context.stroke(glow, with: .color(color.opacity(0.52)), style: StrokeStyle(lineWidth: 6, lineCap: .round, lineJoin: .round))
        context.stroke(glow, with: .color(.white.opacity(0.92)), style: StrokeStyle(lineWidth: 2, lineCap: .round, lineJoin: .round))
    }

    private func point(on points: [CGPoint], progress: Double) -> CGPoint {
        let lengths = zip(points, points.dropFirst()).map { hypot($1.x - $0.x, $1.y - $0.y) }
        let total = lengths.reduce(0, +)
        guard total > 0 else { return points.first ?? .zero }
        var distance = min(1, max(0, progress)) * total
        for (index, length) in lengths.enumerated() {
            if distance <= length {
                let ratio = length == 0 ? 0 : distance / length
                return CGPoint(
                    x: points[index].x + (points[index + 1].x - points[index].x) * ratio,
                    y: points[index].y + (points[index + 1].y - points[index].y) * ratio
                )
            }
            distance -= length
        }
        return points.last ?? .zero
    }
}

private struct EnergySceneMetric: View {
    let title: String
    let value: String
    let detail: String?
    let color: Color
    let symbol: String

    init(title: String, value: String, detail: String?, color: Color, symbol: String) {
        self.title = title
        self.value = value
        self.detail = detail
        self.color = color
        self.symbol = symbol
    }

    var body: some View {
        VStack(spacing: 2) {
            Label(title, systemImage: symbol)
                .font(.caption2.weight(.bold)).foregroundStyle(color)
            Text(value)
                .font(.caption.monospacedDigit().weight(.heavy))
                .lineLimit(1)
                .minimumScaleFactor(0.72)
            if let detail {
                Text(detail)
                    .font(.system(size: 8, weight: .semibold))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
        }
        .padding(.horizontal, 9).padding(.vertical, 6)
        .background(Color.black.opacity(0.68), in: RoundedRectangle(cornerRadius: 11))
        .overlay { RoundedRectangle(cornerRadius: 11).stroke(color.opacity(0.35)) }
        .accessibilityElement(children: .combine)
    }
}

private struct AnimatedHomeBatteryNode: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    let stateOfCharge: Double?
    let powerWatts: Double?
    let direction: String?

    private var magnitude: Double { abs(powerWatts ?? 0) }
    private var active: Bool { magnitude > 25 }
    private var charging: Bool {
        active && (direction == "charging" || (powerWatts ?? 0) < -25)
    }
    private var discharging: Bool {
        active && !charging
    }
    private var status: String {
        if charging { return "Charging" }
        if discharging { return "Supplying" }
        return "Idle"
    }

    @ViewBuilder
    var body: some View {
        if reduceMotion || !active {
            content(phase: 0.5)
        } else {
            TimelineView(.animation(minimumInterval: 1 / 24)) { timeline in
                content(phase: timeline.date.timeIntervalSinceReferenceDate.truncatingRemainder(dividingBy: 1.6) / 1.6)
            }
        }
    }

    private func content(phase: Double) -> some View {
        let soc = max(0, min(100, stateOfCharge ?? 0))
        let pulse = active ? 0.52 + (sin(phase * .pi * 2) + 1) * 0.16 : 0.30
        return VStack(spacing: 3) {
            Capsule()
                .fill(.white.opacity(0.34))
                .frame(width: 19, height: 4)
            ZStack(alignment: .bottom) {
                RoundedRectangle(cornerRadius: 9)
                    .fill(Color.black.opacity(0.78))
                GeometryReader { geometry in
                    ZStack(alignment: .bottom) {
                        LinearGradient(
                            colors: charging
                                ? [PilotTheme.mint, PilotTheme.cyan]
                                : [PilotTheme.mint.opacity(0.65), PilotTheme.mint],
                            startPoint: .bottom,
                            endPoint: .top
                        )
                        .frame(height: geometry.size.height * soc / 100)

                        if active {
                            Image(systemName: charging ? "chevron.up.2" : "chevron.down.2")
                                .font(.system(size: 11, weight: .black))
                                .foregroundStyle(.white.opacity(0.88))
                                .offset(y: charging ? 22 - phase * 44 : -22 + phase * 44)
                        }
                    }
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottom)
                    .clipShape(RoundedRectangle(cornerRadius: 7))
                    .padding(4)
                }
                Text(stateOfCharge.map { "\(Int($0.rounded()))%" } ?? "—")
                    .font(.caption2.monospacedDigit().weight(.black))
                    .foregroundStyle(.white)
                    .padding(.bottom, 6)
                    .shadow(color: .black, radius: 2)
            }
            .frame(width: 45, height: 68)
            .overlay {
                RoundedRectangle(cornerRadius: 9)
                    .stroke(PilotTheme.mint.opacity(pulse), lineWidth: active ? 2 : 1)
            }
            .shadow(color: PilotTheme.mint.opacity(active ? pulse * 0.55 : 0), radius: 9)

            Text(Self.power(powerWatts))
                .font(.system(size: 10, weight: .heavy, design: .monospaced))
            Text(status)
                .font(.system(size: 8, weight: .semibold))
                .foregroundStyle(charging ? PilotTheme.cyan : discharging ? PilotTheme.mint : .secondary)
        }
        .padding(5)
        .background(Color.black.opacity(0.62), in: RoundedRectangle(cornerRadius: 11))
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Home battery, \(Int(soc.rounded())) percent, \(status), \(Self.power(powerWatts))")
    }

    private static func power(_ watts: Double?) -> String {
        guard let watts else { return "—" }
        return abs(watts) >= 1_000
            ? String(format: "%.2f kW", abs(watts) / 1_000)
            : String(format: "%.0f W", abs(watts))
    }
}

private struct AnimatedServerRackNode: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    let powerWatts: Double?

    @ViewBuilder
    var body: some View {
        if reduceMotion {
            content(phase: 0.35)
        } else {
            TimelineView(.animation(minimumInterval: 1 / 12)) { timeline in
                content(phase: timeline.date.timeIntervalSinceReferenceDate)
            }
        }
    }

    private func content(phase: Double) -> some View {
        VStack(spacing: 0) {
            ZStack {
                Image("PilotServerRack")
                    .interpolation(.high)
                    .resizable()
                    .scaledToFit()
                    .frame(width: 69, height: 69)
                VStack(spacing: 3) {
                    rackLED(.green, phase: phase, offset: 0.0)
                    rackLED(PilotTheme.cyan, phase: phase, offset: 1.6)
                    rackLED(PilotTheme.amber, phase: phase, offset: 3.1)
                }
                .offset(x: 12, y: 4)
            }
            Text(Self.power(powerWatts))
                .font(.system(size: 9, weight: .heavy, design: .monospaced))
            Text("SERVER RACK")
                .font(.system(size: 7, weight: .bold))
                .foregroundStyle(PilotTheme.violet)
        }
        .padding(3)
        .background(Color.black.opacity(0.55), in: RoundedRectangle(cornerRadius: 10))
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Server rack using \(Self.power(powerWatts))")
    }

    private func rackLED(_ color: Color, phase: Double, offset: Double) -> some View {
        let brightness = reduceMotion ? 0.75 : 0.24 + (sin(phase * 3.8 + offset) + 1) * 0.34
        return Circle()
            .fill(color.opacity(brightness))
            .frame(width: 3.5, height: 3.5)
            .shadow(color: color.opacity(brightness), radius: 3)
    }

    private static func power(_ watts: Double?) -> String {
        guard let watts else { return "—" }
        return abs(watts) >= 1_000
            ? String(format: "%.2f kW", abs(watts) / 1_000)
            : String(format: "%.0f W", abs(watts))
    }
}

private struct DailySummaryMetric: View {
    let label: String
    let value: Double?
    let color: Color
    init(_ label: String, _ value: Double?, _ color: Color) {
        self.label = label; self.value = value; self.color = color
    }
    var body: some View {
        VStack(spacing: 4) {
            Text(label).font(.caption).foregroundStyle(.secondary)
            Text(value.map { String(format: "%.1f kWh", $0) } ?? "—")
                .font(.subheadline.monospacedDigit().bold()).foregroundStyle(color)
        }.frame(maxWidth: .infinity)
    }
}

private struct EnergyHistoryPage: View {
    let snapshot: DashboardSnapshot

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Last \(snapshot.history.periodHours) hours")
                .font(.headline)
            if snapshot.history.series.allSatisfy({ $0.points.isEmpty }) {
                ContentUnavailableView("No history yet", systemImage: "chart.xyaxis.line")
                    .frame(height: 250)
            } else {
                Chart(snapshot.history.series) { series in
                    ForEach(series.points) { point in
                        LineMark(
                            x: .value("Time", point.date),
                            y: .value("Power", point.value / 1_000),
                            series: .value("Series", series.label)
                        )
                        .foregroundStyle(Self.color(series.color))
                        .interpolationMethod(.catmullRom)
                    }
                }
                .chartYAxisLabel("kW")
                .frame(height: 280)
                HStack(spacing: 16) {
                    ForEach(snapshot.history.series) { series in
                        Label(series.label, systemImage: "circle.fill")
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(Self.color(series.color))
                    }
                }
            }
        }
    }

    private static func color(_ hex: String) -> Color {
        let value = UInt64(hex.trimmingCharacters(in: CharacterSet.alphanumerics.inverted), radix: 16) ?? 0
        return Color(red: Double((value >> 16) & 0xff) / 255,
                     green: Double((value >> 8) & 0xff) / 255,
                     blue: Double(value & 0xff) / 255)
    }
}

private struct DailyEnergyPage: View {
    @Environment(PilotModel.self) private var model
    let snapshot: DashboardSnapshot

    var body: some View {
        VStack(spacing: 14) {
            HStack(spacing: 12) {
                DailyTile("Solar generated", snapshot.daily.solarGeneratedKWh, PilotTheme.amber, "sun.max.fill")
                DailyTile("Home used", snapshot.daily.homeUsedKWh, PilotTheme.mint, "house.fill")
                DailyTile("Grid exported", snapshot.daily.gridExportedKWh, PilotTheme.cyan, "transmission")
            }
            VStack(alignment: .leading, spacing: 14) {
                HStack {
                    Label("Jarvis", systemImage: "bolt.car.fill")
                        .font(.headline).foregroundStyle(.red)
                    Spacer()
                    Text(snapshot.vehicle.stateOfCharge.map { "\(Int($0))%" } ?? "—")
                        .font(.title2.monospacedDigit().bold())
                }
                Text(snapshot.vehicle.connected == true
                     ? (snapshot.vehicle.charging ? "Plugged in and charging" : "Plugged in")
                     : "Not plugged in")
                    .foregroundStyle(.secondary)
                HStack {
                    ForEach(snapshot.controls.chargingMode.options.filter { ["Grid", "Solar"].contains($0) }, id: \.self) { mode in
                        if mode == snapshot.controls.chargingMode.value {
                            Button(mode) {}
                                .buttonStyle(.borderedProminent)
                                .disabled(true)
                        } else {
                            Button(mode) {
                                Task { await model.dashboardAction("set_tesla_charging_mode", value: mode) }
                            }
                            .buttonStyle(.bordered)
                            .disabled(model.dashboardActionInFlight)
                        }
                    }
                }
            }
            .pilotCard()

            HStack(spacing: 12) {
                PriceTile("Buy now", snapshot.tariff.importCentsPerKWh, PilotTheme.amber)
                PriceTile("Feed-in now", snapshot.tariff.feedInCentsPerKWh, PilotTheme.mint)
            }

            if snapshot.controls.mediaRoomMode.available {
                VStack(alignment: .leading, spacing: 10) {
                    Text("MEDIA ROOM MODE").font(.caption.weight(.bold)).foregroundStyle(PilotTheme.violet)
                    HStack {
                        Button("Movie Mode On") {
                            Task { await model.dashboardAction("set_media_room_mode", value: "on") }
                        }.buttonStyle(.borderedProminent)
                        Button("Movie Mode Off") {
                            Task { await model.dashboardAction("set_media_room_mode", value: "off") }
                        }.buttonStyle(.bordered)
                    }
                }.frame(maxWidth: .infinity, alignment: .leading).pilotCard()
            }
        }
    }
}

private struct DailyTile: View {
    let title: String; let value: Double?; let color: Color; let symbol: String
    init(_ title: String, _ value: Double?, _ color: Color, _ symbol: String) {
        self.title = title; self.value = value; self.color = color; self.symbol = symbol
    }
    var body: some View {
        VStack(spacing: 8) {
            Image(systemName: symbol).foregroundStyle(color)
            Text(value.map { String(format: "%.1f", $0) } ?? "—")
                .font(.title3.monospacedDigit().bold())
            Text(title).font(.caption2).foregroundStyle(.secondary).multilineTextAlignment(.center)
        }.frame(maxWidth: .infinity).padding(.vertical, 16)
         .background(color.opacity(0.08), in: RoundedRectangle(cornerRadius: 16))
    }
}

private struct PriceTile: View {
    let title: String; let value: Double?; let color: Color
    init(_ title: String, _ value: Double?, _ color: Color) {
        self.title = title; self.value = value; self.color = color
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(title).font(.caption).foregroundStyle(.secondary)
            Text(value.map { String(format: "%.2f c/kWh", $0) } ?? "—")
                .font(.title3.monospacedDigit().bold()).foregroundStyle(color)
        }.frame(maxWidth: .infinity, alignment: .leading).pilotCard()
    }
}

private struct ClimatePage: View {
    let snapshot: DashboardSnapshot
    var body: some View {
        VStack(alignment: .leading, spacing: 15) {
            HStack(spacing: 16) {
                Image(systemName: Self.symbol(snapshot.weather.condition))
                    .font(.system(size: 44)).foregroundStyle(PilotTheme.cyan)
                VStack(alignment: .leading) {
                    Text(snapshot.weather.temperatureCelsius.map { String(format: "%.1f°", $0) } ?? "—")
                        .font(.system(.largeTitle, design: .rounded, weight: .bold))
                    Text(snapshot.weather.condition?.replacingOccurrences(of: "_", with: " ").capitalized ?? "Weather unavailable")
                        .foregroundStyle(.secondary)
                }
                Spacer()
                VStack(alignment: .trailing) {
                    Text(snapshot.weather.humidityPercent.map { "Humidity \(Int($0))%" } ?? "")
                    Text(snapshot.weather.windSpeed.map { "Wind \(Int($0)) \(snapshot.weather.windSpeedUnit ?? "")" } ?? "")
                }.font(.caption).foregroundStyle(.secondary)
            }
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 110), spacing: 10)], spacing: 10) {
                ForEach(snapshot.temperatures) { reading in
                    VStack(alignment: .leading, spacing: 4) {
                        Text(reading.label).font(.caption).foregroundStyle(.secondary)
                        Text(reading.temperatureCelsius.map { String(format: "%.1f°", $0) } ?? "—")
                            .font(.title3.monospacedDigit().bold())
                    }.frame(maxWidth: .infinity, alignment: .leading)
                     .padding(13).background(PilotTheme.cyan.opacity(0.07), in: RoundedRectangle(cornerRadius: 14))
                }
            }
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 10) {
                    ForEach(snapshot.weather.forecast) { day in
                        VStack(spacing: 6) {
                            Text(day.dateLabel).font(.caption.weight(.semibold))
                            Image(systemName: Self.symbol(day.condition)).foregroundStyle(PilotTheme.cyan)
                            Text("\(Self.temp(day.lowTemperatureCelsius)) / \(Self.temp(day.highTemperatureCelsius))")
                                .font(.caption.monospacedDigit())
                            if let rain = day.precipitationProbability {
                                Label("\(Int(rain))%", systemImage: "drop.fill")
                                    .font(.caption2).foregroundStyle(PilotTheme.cyan)
                            }
                        }.padding(12).background(Color.white.opacity(0.05), in: RoundedRectangle(cornerRadius: 14))
                    }
                }
            }
        }
    }

    private static func symbol(_ condition: String?) -> String {
        let value = condition?.lowercased() ?? ""
        if value.contains("rain") { return "cloud.rain.fill" }
        if value.contains("cloud") { return "cloud.sun.fill" }
        if value.contains("storm") { return "cloud.bolt.rain.fill" }
        return "sun.max.fill"
    }
    private static func temp(_ value: Double?) -> String { value.map { "\(Int($0))°" } ?? "—" }
}

private extension DashboardHistoryPoint {
    var date: Date { ISO8601DateFormatter().date(from: at) ?? .distantPast }
}

private extension DashboardForecast {
    var dateLabel: String {
        guard let at, let date = ISO8601DateFormatter().date(from: at) else { return "—" }
        return date.formatted(.dateTime.weekday(.abbreviated))
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
        Dictionary(
            grouping: (model.home?.entities ?? []).filter(\.shouldDisplay),
            by: \.displaySection
        )
        .map {
            (
                $0.key,
                $0.value.sorted {
                    ($0.displayPriority, $0.displayName) < ($1.displayPriority, $1.displayName)
                }
            )
        }
        .sorted { left, right in
            (left.1.first?.displayPriority ?? 100, left.0)
                < (right.1.first?.displayPriority ?? 100, right.0)
        }
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
                    Text(entity.displayName)
                        .font(.headline)
                    Text(entity.stale ? "Stale" : entity.state.replacingOccurrences(of: "_", with: " ").capitalized)
                        .font(.caption)
                        .foregroundStyle(entity.stale || entity.unavailable ? PilotTheme.amber : .secondary)
                }
                Spacer()
                if model.activeHomeEntityID == entity.id {
                    ProgressView()
                } else if entity.displayActions.contains("turn_on") {
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
            if entity.displayActions.contains("set_brightness"),
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
            if entity.displayActions.contains("activate") {
                Button("Activate") { Task { await model.control(entity, action: "activate") } }
            }
            if entity.displayActions.contains("open") {
                Button("Open") { Task { await model.control(entity, action: "open") } }
                Button("Close") { Task { await model.control(entity, action: "close") } }
            }
            if entity.displayActions.contains("lock") {
                Button(entity.state == "locked" ? "Unlock" : "Lock") {
                    Task {
                        await model.control(
                            entity,
                            action: entity.state == "locked" ? "unlock" : "lock"
                        )
                    }
                }
            }
            if entity.displayActions.contains("arm_home") {
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
    @AppStorage("pilot.musicAssistantURL") private var musicAssistantURL = "http://10.0.2.72:8095"
    @State private var query = ""
    @State private var showingNowPlaying = false
    @State private var showingPhonePlayer = false

    var body: some View {
        ZStack {
            PilotTheme.background.ignoresSafeArea()
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 22) {
                    HStack {
                        RoomSelector()
                        Spacer(minLength: 8)
                        Button {
                            showingPhonePlayer = true
                        } label: {
                            Label("This iPhone", systemImage: "iphone.gen3.radiowaves.left.and.right")
                        }
                        .buttonStyle(.bordered)
                    }
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
        .fullScreenCover(isPresented: $showingPhonePlayer) {
            MusicAssistantPhonePlayer(
                url: URL(string: musicAssistantURL),
                dismiss: { showingPhonePlayer = false }
            )
        }
        .refreshable { await model.refresh() }
    }

    @ViewBuilder
    private var searchContent: some View {
        if model.isBrowsingMusic {
            ProgressView("Opening Music Assistant…")
                .frame(maxWidth: .infinity).padding(40)
        } else if let page = model.musicBrowsePage {
            MusicBrowseDetail(page: page)
        } else if model.isSearching {
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
                    if kind == .track {
                        ForEach(results) { result in SearchResultRow(result: result) }
                    } else {
                        ScrollView(.horizontal, showsIndicators: false) {
                            LazyHStack(spacing: 14) {
                                ForEach(results) { result in MusicResultCard(result: result) }
                            }
                        }
                    }
                }
            }
        }
    }
}

private struct MusicAssistantPhonePlayer: View {
    let url: URL?
    let dismiss: () -> Void

    var body: some View {
        NavigationStack {
            Group {
                if let url {
                    MusicAssistantWebView(url: url)
                        .ignoresSafeArea(edges: .bottom)
                } else {
                    ContentUnavailableView(
                        "Music Assistant URL is invalid",
                        systemImage: "exclamationmark.triangle",
                        description: Text("Update it in Pilot settings.")
                    )
                }
            }
            .navigationTitle("Play on this iPhone")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done", action: dismiss)
                }
            }
        }
    }
}

private struct MusicAssistantWebView: UIViewRepresentable {
    let url: URL

    func makeUIView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.allowsInlineMediaPlayback = true
        configuration.mediaTypesRequiringUserActionForPlayback = []
        let view = WKWebView(frame: .zero, configuration: configuration)
        view.allowsBackForwardNavigationGestures = true
        view.load(URLRequest(url: url))
        return view
    }

    func updateUIView(_ webView: WKWebView, context: Context) {
        guard webView.url == nil else { return }
        webView.load(URLRequest(url: url))
    }
}

private struct RoomSelector: View {
    @Environment(PilotModel.self) private var model

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 10) {
                ForEach(model.rooms.filter { $0.musicEnabled != false }) { room in
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
                ArtworkTile(
                    media: state?.effective.media,
                    size: 92,
                    artworkURL: state?.effective.artworkURL.flatMap(URL.init(string:))
                )
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

            if let duration = state?.effective.durationSeconds, duration > 0 {
                VStack(spacing: 5) {
                    ProgressView(
                        value: min(state?.effective.positionSeconds ?? 0, duration),
                        total: duration
                    )
                    .tint(PilotTheme.cyan)
                    HStack {
                        Text(Self.duration(state?.effective.positionSeconds ?? 0))
                        Spacer()
                        Text(Self.duration(duration))
                    }
                    .font(.caption2.monospacedDigit())
                    .foregroundStyle(.secondary)
                }
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

    private static func duration(_ seconds: Double) -> String {
        let value = max(0, Int(seconds))
        return String(format: "%d:%02d", value / 60, value % 60)
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
            Task { await model.browse(result) }
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
                if model.activeMediaResultID == result.id {
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

private struct MusicResultCard: View {
    @Environment(PilotModel.self) private var model
    let result: MusicSearchResult

    var body: some View {
        Button {
            PilotHaptics.impact()
            Task { await model.browse(result) }
        } label: {
            VStack(alignment: .leading, spacing: 8) {
                AsyncArtwork(url: result.artworkURL, symbol: result.kind.symbol)
                    .frame(width: 152, height: 152)
                    .clipShape(RoundedRectangle(cornerRadius: result.kind == .artist ? 76 : 16))
                Text(result.title)
                    .font(.subheadline.weight(.bold)).foregroundStyle(.primary)
                    .lineLimit(1)
                Text(result.subtitle.isEmpty ? result.kind.title : result.subtitle)
                    .font(.caption).foregroundStyle(.secondary).lineLimit(1)
            }
            .frame(width: 152, alignment: .leading)
        }
        .buttonStyle(.plain)
        .accessibilityLabel("Open \(result.title)")
    }
}

private struct MusicBrowseDetail: View {
    @Environment(PilotModel.self) private var model
    let page: MusicBrowsePage

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            Button {
                model.dismissMusicBrowse()
            } label: {
                Label("Back to results", systemImage: "chevron.left")
            }
            .buttonStyle(.plain)
            .foregroundStyle(PilotTheme.cyan)

            HStack(spacing: 18) {
                AsyncArtwork(url: page.item.artworkURL, symbol: page.item.kind.symbol)
                    .frame(width: 116, height: 116)
                    .clipShape(RoundedRectangle(cornerRadius: page.item.kind == .artist ? 58 : 18))
                VStack(alignment: .leading, spacing: 5) {
                    Text(page.item.kind.rawValue.uppercased())
                        .font(.caption.weight(.bold)).tracking(1.8).foregroundStyle(PilotTheme.cyan)
                    Text(page.item.title).font(.largeTitle.bold()).lineLimit(2)
                    Text(page.item.subtitle).foregroundStyle(.secondary)
                    Button {
                        Task {
                            await model.command(
                                "play_media", mediaURI: page.item.uri, operationID: page.item.id
                            )
                        }
                    } label: {
                        Label("Play", systemImage: "play.fill")
                    }
                    .buttonStyle(.borderedProminent)
                }
            }

            ForEach(page.sections) { section in
                VStack(alignment: .leading, spacing: 12) {
                    Text(section.title).font(.title2.bold())
                    if section.id == "albums" {
                        ScrollView(.horizontal, showsIndicators: false) {
                            LazyHStack(spacing: 14) {
                                ForEach(section.items) { MusicResultCard(result: $0) }
                            }
                        }
                    } else {
                        ForEach(section.items) { SearchResultRow(result: $0) }
                    }
                }
            }
        }
        .transition(.opacity.combined(with: .move(edge: .trailing)))
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
                    if !model.pendingMeetingRecordings.isEmpty {
                        pendingRecordings
                    }
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

    private var pendingRecordings: some View {
        VStack(alignment: .leading, spacing: 12) {
            SectionTitle(
                eyebrow: "SAFE ON THIS DEVICE",
                title: "Pending recordings",
                trailing: "\(model.pendingMeetingRecordings.count) retained"
            )
            ForEach(model.pendingMeetingRecordings) { pending in
                HStack(spacing: 13) {
                    Image(systemName: pending.state == .failed
                          ? "exclamationmark.arrow.triangle.2.circlepath"
                          : "arrow.up.circle.fill")
                        .font(.title2)
                        .foregroundStyle(pending.state == .failed ? PilotTheme.amber : PilotTheme.cyan)
                    VStack(alignment: .leading, spacing: 3) {
                        Text(pending.title)
                            .font(.headline)
                        Text(pending.failureMessage ?? pendingState(pending))
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .lineLimit(2)
                    }
                    Spacer()
                    if [.ready, .failed].contains(pending.state) {
                        Button("Retry") {
                            Task { await model.retryPendingMeeting(pending.meetingID) }
                        }
                        .buttonStyle(.borderedProminent)
                        .disabled(model.isSubmittingMeeting)
                    } else {
                        ProgressView()
                    }
                }
                .padding(14)
                .background(Color.white.opacity(0.045), in: RoundedRectangle(cornerRadius: 16))
            }
            Label(
                "Pilot never removes local audio until Core accepts both its upload and processing job.",
                systemImage: "lock.shield.fill"
            )
            .font(.caption)
            .foregroundStyle(.secondary)
        }
        .pilotCard()
    }

    private func pendingState(_ pending: PendingMeetingRecording) -> String {
        switch pending.state {
        case .ready: "Ready to upload"
        case .uploading: "Uploading securely to Pilot Core"
        case .processing: "Core accepted the audio; starting local processing"
        case .failed: "Retry when Pilot Core is reachable"
        }
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
                ScrollViewReader { proxy in
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
                                            evidenceButton(action.segmentIDs) { segmentID in
                                                withAnimation(.snappy) {
                                                    proxy.scrollTo(segmentID, anchor: .center)
                                                }
                                            }
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
                                        evidenceButton(decision.segmentIDs) { segmentID in
                                            withAnimation(.snappy) {
                                                proxy.scrollTo(segmentID, anchor: .center)
                                            }
                                        }
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
                                    .id(segment.id)
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
                }
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

    private func evidenceButton(
        _ segmentIDs: [String],
        open: @escaping (String) -> Void
    ) -> some View {
        Button {
            if let first = segmentIDs.first { open(first) }
        } label: {
            Label(
                "\(segmentIDs.count) source\(segmentIDs.count == 1 ? "" : "s")",
                systemImage: "link"
            )
        }
        .buttonStyle(.plain)
        .font(.caption)
        .foregroundStyle(PilotTheme.cyan)
        .disabled(segmentIDs.isEmpty)
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
                Text(statusTitle)
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

    private var statusTitle: String {
        if model.isSendingMessage { return "Pilot is reasoning" }
        let status = model.assistantStatus.lowercased()
        if status.contains("listen") { return "Pilot is listening" }
        if status.contains("act") || status.contains("tool") { return "Pilot is acting" }
        if status.contains("speak") { return "Pilot is speaking" }
        return "Pilot is ready"
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
                if !message.cards.isEmpty {
                    VStack(spacing: 8) {
                        ForEach(message.cards) { card in
                            AssistantResultCard(card: card)
                        }
                    }
                    .padding(.top, 5)
                }
                if !message.toolCalls.isEmpty {
                    VStack(alignment: .leading, spacing: 5) {
                        ForEach(message.toolCalls, id: \.stableID) { tool in
                            Label(
                                tool.name.replacingOccurrences(of: "_", with: " ").capitalized,
                                systemImage: tool.status == "failed"
                                    ? "exclamationmark.circle" : "checkmark.circle.fill"
                            )
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(tool.status == "failed" ? .orange : PilotTheme.mint)
                        }
                    }
                    .padding(.top, 4)
                }
                if !message.sources.isEmpty {
                    VStack(alignment: .leading, spacing: 4) {
                        ForEach(message.sources) { source in
                            if let value = source.url, let url = URL(string: value) {
                                Link(destination: url) {
                                    Label(source.title, systemImage: "link")
                                }
                            } else {
                                Label(source.title, systemImage: "doc.text")
                            }
                        }
                    }
                    .font(.caption)
                    .padding(.top, 4)
                }
                if !message.actions.isEmpty {
                    HStack(spacing: 8) {
                        ForEach(message.actions) { action in
                            Label(action.title, systemImage: action.status == "failed"
                                  ? "xmark.circle" : "checkmark.circle")
                                .font(.caption.weight(.semibold))
                        }
                    }
                    .padding(.top, 4)
                }
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

private struct AssistantResultCard: View {
    let card: AssistantCard

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: card.symbol ?? symbol)
                .foregroundStyle(PilotTheme.cyan)
                .frame(width: 26)
            VStack(alignment: .leading, spacing: 2) {
                Text(card.title)
                    .font(.subheadline.weight(.semibold))
                if let subtitle = card.subtitle {
                    Text(subtitle)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            Spacer(minLength: 0)
        }
        .padding(10)
        .background(Color.black.opacity(0.16), in: RoundedRectangle(cornerRadius: 13))
        .accessibilityElement(children: .combine)
    }

    private var symbol: String {
        switch card.kind {
        case "energy": "bolt.fill"
        case "media": "music.note"
        case "home": "house.fill"
        case "weather": "cloud.sun.fill"
        default: "sparkles"
        }
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
    @State private var position = 0.0

    private var state: PilotPlayerState? { model.selectedPlayer }

    var body: some View {
        NavigationStack {
            ZStack {
                PilotTheme.background.ignoresSafeArea()
                ScrollView {
                    VStack(spacing: 24) {
                        ArtworkTile(
                            media: state?.effective.media,
                            size: 250,
                            artworkURL: state?.effective.artworkURL.flatMap(URL.init(string:))
                        )
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


                        if let duration = state?.effective.durationSeconds, duration > 0 {
                            VStack(spacing: 7) {
                                Slider(value: $position, in: 0...duration, step: 1) { editing in
                                    if !editing {
                                        Task {
                                            await model.command(
                                                "seek",
                                                positionSeconds: position
                                            )
                                        }
                                    }
                                }
                                HStack {
                                    Text(Self.duration(position))
                                    Spacer()
                                    Text("-\(Self.duration(max(0, duration - position)))")
                                }
                                .font(.caption.monospacedDigit())
                                .foregroundStyle(.secondary)
                            }
                        }

                        HStack(spacing: 38) {
                            MediaButton(symbol: "backward.fill", label: "Previous", size: 48) {
                                Task { await model.command("previous") }
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
                            MediaButton(symbol: "forward.fill", label: "Next", size: 48) {
                                Task { await model.command("next") }
                            }
                        }

                        VStack(spacing: 12) {
                            HStack {
                                Button {
                                    Task {
                                        await model.command(
                                            "set_mute",
                                            muted: !(state?.effective.muted ?? false)
                                        )
                                    }
                                } label: {
                                    Image(systemName: state?.effective.muted == true
                                          ? "speaker.slash.fill" : "speaker.fill")
                                }
                                .accessibilityLabel(state?.effective.muted == true ? "Unmute" : "Mute")
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

                        Menu {
                            ForEach(model.rooms.filter {
                                $0.id != model.selectedRoomID && $0.musicEnabled != false
                            }) { room in
                                Button("Move to \(room.name)") {
                                    Task { await model.transfer(to: room.id) }
                                }
                            }
                        } label: {
                            Label("Choose room or group", systemImage: "airplayaudio")
                                .frame(maxWidth: .infinity)
                                .padding(.vertical, 12)
                                .background(Color.white.opacity(0.08), in: RoundedRectangle(cornerRadius: 15))
                        }
                        .accessibilityLabel("Move music to another room")

                        if let queue = state?.effective.queue, !queue.items.isEmpty {
                            VStack(alignment: .leading, spacing: 10) {
                                SectionTitle(eyebrow: "UP NEXT", title: "Queue", trailing: "\(queue.items.count)")
                                ForEach(queue.items.prefix(20)) { item in
                                    HStack(spacing: 12) {
                                        AsyncArtwork(
                                            url: item.resolvedArtworkURL,
                                            symbol: item.isCurrent == true ? "waveform" : "music.note"
                                        )
                                        .frame(width: 44, height: 44)
                                        VStack(alignment: .leading, spacing: 2) {
                                            Text(item.title).font(.subheadline.weight(.semibold))
                                            Text(item.artist ?? item.album ?? "")
                                                .font(.caption)
                                                .foregroundStyle(.secondary)
                                        }
                                        Spacer()
                                        if item.isCurrent == true {
                                            Image(systemName: "speaker.wave.2.fill")
                                                .foregroundStyle(PilotTheme.cyan)
                                        }
                                    }
                                }
                            }
                            .pilotCard()
                        }
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
                position = state?.effective.positionSeconds ?? 0
            }
            .onChange(of: model.selectedRoomID) {
                volume = Double(state?.effective.volumePercent ?? 30)
                position = state?.effective.positionSeconds ?? 0
            }
            .onChange(of: state?.effective.positionSeconds) { _, value in
                position = value ?? 0
            }
        }
    }

    private static func duration(_ seconds: Double) -> String {
        let value = max(0, Int(seconds))
        return String(format: "%d:%02d", value / 60, value % 60)
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
                        ArtworkTile(
                            media: state.effective.media,
                            size: 42,
                            artworkURL: state.effective.artworkURL.flatMap(URL.init(string:))
                        )
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
    @AppStorage("pilot.musicAssistantURL") private var musicAssistantURL = "http://10.0.2.72:8095"
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

                    Section("Phone music output") {
                        TextField("Music Assistant URL", text: $musicAssistantURL)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                            .keyboardType(.URL)
                        Text("Used only by the embedded Music Assistant player when you choose This iPhone. Pilot controls continue to use Pilot Core.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
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
                        Text("Pilot actions remain device-scoped through Pilot Core. The optional This iPhone player opens your local Music Assistant web player without storing its credentials in Pilot.")
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
    @State private var pairingCode = ""
    @State private var showingScanner = false
    @State private var pairingFailed = false

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

                        VStack(alignment: .leading, spacing: 14) {
                            SectionTitle(
                                eyebrow: "RECOMMENDED",
                                title: "Pair this device",
                                trailing: "Single-use and revocable"
                            )
                            Text("Scan the QR code from Pilot Core, or paste its one-time pairing code. Your device credential is only saved after Core authenticates it.")
                                .font(.subheadline)
                                .foregroundStyle(.secondary)
                            TextField("Pairing code", text: $pairingCode)
                                .textInputAutocapitalization(.never)
                                .autocorrectionDisabled()
                                .textContentType(.oneTimeCode)
                                .padding(14)
                                .background(Color.black.opacity(0.20), in: RoundedRectangle(cornerRadius: 14))
                            HStack(spacing: 10) {
                                Button {
                                    showingScanner = true
                                } label: {
                                    Label("Scan QR code", systemImage: "qrcode.viewfinder")
                                        .frame(maxWidth: .infinity)
                                }
                                .buttonStyle(.bordered)
                                .disabled(!DataScannerViewController.isSupported)

                                Button {
                                    Task {
                                        pairingFailed = !(await model.pair(using: pairingCode))
                                    }
                                } label: {
                                    HStack {
                                        if model.isRefreshing { ProgressView().controlSize(.small) }
                                        Text("Pair securely")
                                    }
                                    .frame(maxWidth: .infinity)
                                }
                                .buttonStyle(.borderedProminent)
                                .disabled(pairingCode.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || model.isRefreshing)
                            }
                            if pairingFailed {
                                Label(model.status, systemImage: "exclamationmark.triangle.fill")
                                    .font(.caption)
                                    .foregroundStyle(PilotTheme.amber)
                            }
                        }
                        .pilotCard()

                        HStack {
                            Rectangle().fill(PilotTheme.border).frame(height: 1)
                            Text("OR ENTER EXISTING CREDENTIALS")
                                .font(.caption2.weight(.bold))
                                .foregroundStyle(.secondary)
                            Rectangle().fill(PilotTheme.border).frame(height: 1)
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
        .sheet(isPresented: $showingScanner) {
            NavigationStack {
                PairingScanner { code in
                    pairingCode = code
                    showingScanner = false
                    Task {
                        pairingFailed = !(await model.pair(using: code))
                    }
                }
                .ignoresSafeArea(edges: .bottom)
                .navigationTitle("Scan Pilot pairing code")
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .topBarTrailing) {
                        Button("Cancel") { showingScanner = false }
                    }
                }
            }
        }
    }
}

private struct PairingScanner: UIViewControllerRepresentable {
    let onCode: (String) -> Void

    func makeCoordinator() -> Coordinator { Coordinator(onCode: onCode) }

    func makeUIViewController(context: Context) -> DataScannerViewController {
        let scanner = DataScannerViewController(
            recognizedDataTypes: [.barcode(symbologies: [.qr])],
            qualityLevel: .balanced,
            recognizesMultipleItems: false,
            isHighFrameRateTrackingEnabled: false,
            isPinchToZoomEnabled: true,
            isGuidanceEnabled: true,
            isHighlightingEnabled: true
        )
        scanner.delegate = context.coordinator
        return scanner
    }

    func updateUIViewController(_ scanner: DataScannerViewController, context: Context) {
        guard !scanner.isScanning else { return }
        try? scanner.startScanning()
    }

    static func dismantleUIViewController(
        _ scanner: DataScannerViewController,
        coordinator: Coordinator
    ) {
        scanner.stopScanning()
    }

    final class Coordinator: NSObject, DataScannerViewControllerDelegate {
        let onCode: (String) -> Void
        private var accepted = false

        init(onCode: @escaping (String) -> Void) {
            self.onCode = onCode
        }

        func dataScanner(
            _ dataScanner: DataScannerViewController,
            didAdd addedItems: [RecognizedItem],
            allItems: [RecognizedItem]
        ) {
            guard !accepted else { return }
            for item in addedItems {
                guard case let .barcode(code) = item, let value = code.payloadStringValue else {
                    continue
                }
                accepted = true
                onCode(value)
                return
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
    var artworkURL: URL? = nil

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
            if let url = artworkURL ?? media?.artworkURL.flatMap(URL.init(string:)) {
                AsyncImage(url: url) { phase in
                    if case let .success(image) = phase {
                        image.resizable().scaledToFill()
                    }
                }
                .clipShape(RoundedRectangle(cornerRadius: size * 0.20, style: .continuous))
            }
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
