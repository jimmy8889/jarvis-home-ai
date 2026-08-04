import PilotClientKit
import SwiftUI

struct CarView: View {
    @Bindable var model: DriveModel
    @State private var showingSettings = false
    @State private var showingDestinationEditor = false
    @State private var editingDestination: SavedDestination?
    @State private var temperature = 22.0
    @State private var chargeLimit = 80.0

    private let columns = [GridItem(.adaptive(minimum: 150), spacing: 12)]

    var body: some View {
        NavigationStack {
            ScrollView {
                if let car = model.overview {
                    LazyVStack(spacing: 18) {
                        vehicleHeader(car)
                        quickDestinations
                        conditionGrid(car)
                        chargingCard(car)
                        tyreCard(car)
                        if model.canControl { controls(car) }
                        providerCard(car)
                    }
                    .padding()
                } else if model.isLoading {
                    ProgressView("Loading Jarvis…")
                        .padding(.top, 120)
                } else {
                    EmptyState(
                        symbol: "car.side",
                        title: "Vehicle unavailable",
                        detail: "Pull to refresh when Pilot Core is reachable."
                    )
                }
            }
            .refreshable { await model.refreshAll() }
            .navigationTitle("Car")
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button { showingSettings = true } label: {
                        Image(systemName: "gearshape")
                    }
                    .accessibilityLabel("Pilot Drive settings")
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button { Task { await model.refreshAll() } } label: {
                        if model.isLoading { ProgressView() }
                        else { Image(systemName: "arrow.clockwise") }
                    }
                    .disabled(model.isLoading)
                    .accessibilityLabel("Refresh vehicle")
                }
            }
            .sheet(isPresented: $showingDestinationEditor) {
                DestinationEditor(model: model)
            }
            .sheet(isPresented: $showingSettings) {
                SettingsView(model: model)
            }
            .sheet(item: $editingDestination) { destination in
                DestinationEditor(model: model, destination: destination)
            }
            .sheet(item: $model.activeAction) { action in
                ActionProgressView(model: model, action: action)
            }
            .onChange(of: model.selectedVehicle?.defaultClimateTargetC) { _, value in
                if let value { temperature = value }
            }
            .onChange(of: model.overview?.number("charge_limit_percent")) { _, value in
                if let value { chargeLimit = value }
            }
        }
    }

    @ViewBuilder
    private func vehicleHeader(_ car: VehicleOverview) -> some View {
        VStack(spacing: 14) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 5) {
                    Text(car.name)
                        .font(.largeTitle.bold())
                    HStack {
                        StatusPill(
                            text: car.text("state") ?? "Unknown",
                            tint: car.text("state") == "asleep" ? .secondary : DriveTheme.accent
                        )
                        StatusPill(
                            text: car.freshness,
                            tint: car.freshness == "fresh" ? DriveTheme.accent : .orange
                        )
                    }
                }
                Spacer()
                Image(systemName: "car.side.fill")
                    .font(.system(size: 52))
                    .foregroundStyle(DriveTheme.accent)
                    .accessibilityHidden(true)
            }
            HStack(alignment: .firstTextBaseline) {
                Text(car.number("battery_percent").map { "\(Int($0))%" } ?? "—")
                    .font(.system(size: 48, weight: .bold, design: .rounded))
                Spacer()
                VStack(alignment: .trailing) {
                    Text(car.number("rated_range_km").map { "\(Int($0)) km" } ?? "—")
                        .font(.title2.bold())
                    Text("rated range")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            ProgressView(value: car.number("battery_percent") ?? 0, total: 100)
                .tint(DriveTheme.accent)
                .accessibilityLabel("Battery")
                .accessibilityValue(car.number("battery_percent").map { "\(Int($0)) percent" } ?? "Unavailable")
            HStack {
                Label(car.text("location_name") ?? "Location unavailable", systemImage: "location.fill")
                Spacer()
                Text("Updated \(Formatters.date(car.observedAt))")
            }
            .font(.caption)
            .foregroundStyle(.secondary)
        }
        .pilotCard()
    }

    private var quickDestinations: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("Quick destinations").font(.headline)
                Spacer()
                Button { showingDestinationEditor = true } label: {
                    Label("Add destination", systemImage: "plus")
                }
                .buttonStyle(.borderedProminent)
                .tint(DriveTheme.accent)
                .accessibilityLabel("Add destination")
            }
            if model.destinations.isEmpty {
                Text("Save a regular destination to wake Jarvis, set climate, and send the route with one tap.")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                Button { showingDestinationEditor = true } label: {
                    Label("Choose a place", systemImage: "mappin.and.ellipse")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.bordered)
            } else {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 10) {
                        ForEach(model.destinations) { destination in
                            Button {
                                Task { await model.send(destination) }
                            } label: {
                                VStack(spacing: 7) {
                                    Image(systemName: destination.icon)
                                        .font(.title2)
                                    Text(destination.name)
                                        .font(.subheadline.weight(.semibold))
                                        .lineLimit(1)
                                    if destination.climateEnabled {
                                        Text("Climate \(destination.temperatureC.map { "\(Int($0))°" } ?? "22°")")
                                            .font(.caption2)
                                    }
                                    if let seat = destination.seatClimateMode {
                                        Text("Seat · \(seat.label)")
                                            .font(.caption2)
                                            .foregroundStyle(.secondary)
                                    }
                                }
                                .frame(width: 132, height: 112)
                            }
                            .buttonStyle(.bordered)
                            .accessibilityHint("Wakes the car if required, applies climate and front right seat settings, and sends this route")
                            .contextMenu {
                                Button {
                                    editingDestination = destination
                                } label: { Label("Edit", systemImage: "pencil") }
                                Button(role: .destructive) {
                                    Task { await model.deleteDestination(destination) }
                                } label: { Label("Delete", systemImage: "trash") }
                            }
                        }
                    }
                }
            }
        }
        .pilotCard()
    }

    private func conditionGrid(_ car: VehicleOverview) -> some View {
        LazyVGrid(columns: columns, spacing: 12) {
            MetricTile(
                title: "Battery SOC",
                value: car.number("battery_percent").map { "\(Int($0))%" } ?? "—",
                symbol: "battery.75percent"
            )
            MetricTile(
                title: "Stored energy",
                value: car.number("stored_energy_kwh").map { "\($0.formatted(.number.precision(.fractionLength(1)))) kWh" } ?? "—",
                symbol: "battery.100percent",
                detail: "Estimated usable energy"
            )
            MetricTile(
                title: "To charge limit",
                value: car.number("energy_to_charge_limit_kwh").map { "\($0.formatted(.number.precision(.fractionLength(1)))) kWh" } ?? "—",
                symbol: "bolt.badge.clock",
                detail: car.number("charge_limit_percent").map { "To \(Int($0))%" }
            )
            MetricTile(
                title: "Odometer",
                value: car.number("odometer_km").map { "\($0.formatted(.number.precision(.fractionLength(0)))) km" } ?? "—",
                symbol: "gauge.with.dots.needle.33percent"
            )
            MetricTile(
                title: "Cabin",
                value: car.number("inside_temperature_c").map { "\($0.formatted(.number.precision(.fractionLength(1))))°C" } ?? "—",
                symbol: "thermometer.medium",
                detail: car.number("outside_temperature_c").map { "Outside \($0.formatted(.number.precision(.fractionLength(1))))°C" }
            )
            MetricTile(
                title: "Doors",
                value: car.flag("locked") == true ? "Locked" : "Unlocked",
                symbol: car.flag("locked") == true ? "lock.fill" : "lock.open.fill",
                detail: closureSummary(car)
            )
        }
    }

    private func chargingCard(_ car: VehicleOverview) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Label("Charging", systemImage: "bolt.car")
                    .font(.headline)
                Spacer()
                StatusPill(text: car.text("charging_state") ?? "Unavailable")
            }
            LazyVGrid(columns: columns, spacing: 12) {
                MetricTile(
                    title: "Power",
                    value: car.number("charge_rate_kw").map { "\($0.formatted(.number.precision(.fractionLength(1)))) kW" } ?? "—",
                    symbol: "bolt.fill"
                )
                MetricTile(
                    title: "Added",
                    value: car.number("energy_added_kwh").map { "\($0.formatted(.number.precision(.fractionLength(1)))) kWh" } ?? "—",
                    symbol: "battery.75percent"
                )
                MetricTile(
                    title: "Limit",
                    value: car.number("charge_limit_percent").map { "\(Int($0))%" } ?? "—",
                    symbol: "slider.horizontal.3"
                )
                MetricTile(
                    title: "Time remaining",
                    value: car.number("time_to_full_hours").map { Duration.seconds($0 * 3_600).formatted(.units(allowed: [.hours, .minutes])) } ?? "—",
                    symbol: "clock"
                )
            }
        }
        .pilotCard()
    }

    private func tyreCard(_ car: VehicleOverview) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Label("Tyres", systemImage: "tire")
                .font(.headline)
            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())]) {
                ForEach(["front_left", "front_right", "rear_left", "rear_right"], id: \.self) { corner in
                    let tyre = car.tyres[corner]
                    VStack(spacing: 5) {
                        Text(corner.replacingOccurrences(of: "_", with: " ").capitalized)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Text(tyre?.valueBar.map { "\($0.formatted(.number.precision(.fractionLength(2)))) bar" } ?? "—")
                            .font(.headline)
                        if let status = tyre?.status {
                            StatusPill(
                                text: status,
                                tint: status == "plausible" ? DriveTheme.accent : .orange
                            )
                        }
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 8)
                    .accessibilityElement(children: .combine)
                }
            }
            if car.tyres.values.contains(where: { $0.status == "abnormal_unverified" }) {
                Label("One or more readings are implausible. Treat them as abnormal and unverified until physically checked.", systemImage: "exclamationmark.triangle.fill")
                    .font(.caption)
                    .foregroundStyle(.orange)
            }
        }
        .pilotCard()
    }

    private func controls(_ car: VehicleOverview) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Controls").font(.headline)
            if car.availableControls.contains("set_temperature") {
                VStack(alignment: .leading) {
                    Stepper("Climate target \(Int(temperature))°C", value: $temperature, in: 15...30)
                    Button("Apply temperature") {
                        Task { _ = await model.perform("set_temperature", parameters: ["temperature_c": .number(temperature)]) }
                    }
                    .buttonStyle(.bordered)
                }
            }
            if car.availableControls.contains("set_charge_limit") {
                VStack(alignment: .leading) {
                    Stepper("Charge limit \(Int(chargeLimit))%", value: $chargeLimit, in: 50...100, step: 5)
                    Button("Apply charge limit") {
                        Task { _ = await model.perform("set_charge_limit", parameters: ["percent": .number(chargeLimit)]) }
                    }
                    .buttonStyle(.bordered)
                }
            }
            LazyVGrid(columns: columns, spacing: 10) {
                ForEach(controlDescriptors.filter { car.availableControls.contains($0.action) }) { control in
                    Button {
                        Task { _ = await model.perform(control.action) }
                    } label: {
                        Label(control.title, systemImage: control.symbol)
                            .frame(maxWidth: .infinity, minHeight: 34)
                    }
                    .buttonStyle(.bordered)
                    .tint(control.highRisk ? .orange : DriveTheme.accent)
                    .accessibilityHint(control.highRisk ? "Requires Face ID or device passcode and server confirmation" : "")
                }
            }
            if car.availableControls.contains("set_seat_climate") {
                Menu("Front right seat") {
                    ForEach(SeatClimateMode.allCases) { mode in
                        Button(mode.label) {
                            Task {
                                _ = await model.perform(
                                    "set_seat_climate",
                                    parameters: ["mode": .string(mode.rawValue)]
                                )
                            }
                        }
                    }
                }
                .buttonStyle(.bordered)
            }
            if car.availableControls.contains("set_steering_heat") {
                Menu("Steering heat") {
                    ForEach(0..<4) { level in
                        Button(level == 0 ? "Off" : "Level \(level)") {
                            Task { _ = await model.perform("set_steering_heat", parameters: ["level": .number(Double(level))]) }
                        }
                    }
                }
                .buttonStyle(.bordered)
            }
            Text("Orange controls require Face ID or your device passcode, followed by a single-use server confirmation. Button commands remain unverified until observable state confirms them.")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .pilotCard()
    }

    private func providerCard(_ car: VehicleOverview) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Provider health").font(.headline)
            ForEach(car.providers.keys.sorted(), id: \.self) { provider in
                HStack {
                    Text(provider.replacingOccurrences(of: "_", with: " ").capitalized)
                    Spacer()
                    StatusPill(text: providerStatus(car.providers[provider]))
                }
            }
        }
        .pilotCard()
    }

    private func providerStatus(_ value: PilotJSONValue?) -> String {
        guard case let .object(object) = value else { return "Unknown" }
        return object["status"]?.stringValue ?? "Unknown"
    }

    private func closureSummary(_ car: VehicleOverview) -> String {
        let open = ["doors", "windows", "frunk", "trunk", "charge_port"]
            .filter { car.flag($0) == true }
            .map { $0.replacingOccurrences(of: "_", with: " ").capitalized }
        return open.isEmpty ? "All closures reported closed" : "Open: \(open.joined(separator: ", "))"
    }
}

private struct ControlDescriptor: Identifiable {
    var id: String { action }
    let action: String
    let title: String
    let symbol: String
    let highRisk: Bool
}

private let controlDescriptors = [
    ControlDescriptor(action: "wake", title: "Wake", symbol: "power", highRisk: false),
    ControlDescriptor(action: "lock", title: "Lock", symbol: "lock.fill", highRisk: false),
    ControlDescriptor(action: "unlock", title: "Unlock", symbol: "lock.open.fill", highRisk: true),
    ControlDescriptor(action: "climate_on", title: "Climate on", symbol: "fan.fill", highRisk: false),
    ControlDescriptor(action: "climate_off", title: "Stop climate", symbol: "fan.slash.fill", highRisk: false),
    ControlDescriptor(action: "start_charging", title: "Start charging", symbol: "bolt.fill", highRisk: false),
    ControlDescriptor(action: "stop_charging", title: "Stop charging", symbol: "bolt.slash.fill", highRisk: false),
    ControlDescriptor(action: "sentry_on", title: "Sentry on", symbol: "eye.fill", highRisk: false),
    ControlDescriptor(action: "sentry_off", title: "Sentry off", symbol: "eye.slash.fill", highRisk: false),
    ControlDescriptor(action: "flash_lights", title: "Flash lights", symbol: "light.beacon.max.fill", highRisk: false),
    ControlDescriptor(action: "honk_horn", title: "Horn", symbol: "speaker.wave.3.fill", highRisk: false),
    ControlDescriptor(action: "open_frunk", title: "Open frunk", symbol: "car.side.front.open", highRisk: true),
    ControlDescriptor(action: "open_trunk", title: "Open trunk", symbol: "car.side.rear.open", highRisk: true),
    ControlDescriptor(action: "close_trunk", title: "Close trunk", symbol: "car.side.rear.and.collision.and.car.side.front", highRisk: true),
    ControlDescriptor(action: "vent_windows", title: "Vent windows", symbol: "window.ceiling", highRisk: true),
    ControlDescriptor(action: "close_windows", title: "Close windows", symbol: "window.ceiling.closed", highRisk: true),
    ControlDescriptor(action: "remote_start", title: "Remote start", symbol: "key.fill", highRisk: true),
    ControlDescriptor(action: "valet_on", title: "Valet on", symbol: "person.badge.key.fill", highRisk: true),
    ControlDescriptor(action: "valet_off", title: "Valet off", symbol: "person.badge.key", highRisk: true),
    ControlDescriptor(action: "homelink", title: "HomeLink", symbol: "house.fill", highRisk: true),
    ControlDescriptor(action: "install_software", title: "Install update", symbol: "arrow.down.app.fill", highRisk: true),
]

struct ActionProgressView: View {
    @Bindable var model: DriveModel
    let action: VehicleAction
    @Environment(\.dismiss) private var dismiss

    private var displayed: VehicleAction { model.activeAction ?? action }

    var body: some View {
        NavigationStack {
            List {
                Section {
                    HStack {
                        Text(displayed.action.replacingOccurrences(of: "_", with: " ").capitalized)
                            .font(.headline)
                        Spacer()
                        StatusPill(text: displayed.status, tint: statusTint)
                    }
                    if displayed.risk == "high" {
                        Label("Device authentication and server confirmation required", systemImage: "faceid")
                            .font(.subheadline)
                    }
                }
                if !displayed.steps.isEmpty {
                    Section("Workflow") {
                        ForEach(displayed.steps) { step in
                            HStack {
                                Image(systemName: symbol(for: step.status))
                                    .foregroundStyle(tint(for: step.status))
                                VStack(alignment: .leading) {
                                    Text(step.step.replacingOccurrences(of: "_", with: " ").capitalized)
                                    if let error = step.error {
                                        Text(error).font(.caption).foregroundStyle(.secondary)
                                    }
                                }
                                Spacer()
                                Text(step.status.replacingOccurrences(of: "_", with: " ").capitalized)
                                    .font(.caption)
                            }
                        }
                    }
                }
                Section {
                    Text("Accepted means the provider received the command. Reconciled means Pilot observed the expected state. Unverified is not reported as confirmed success.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                    if ["failed", "unverified"].contains(displayed.status) {
                        Button("Retry explicitly") {
                            Task { await model.retryActiveAction() }
                        }
                    }
                    if displayed.action == "destination_workflow" {
                        Button("Stop climate") {
                            Task { _ = await model.perform("climate_off") }
                        }
                    }
                }
            }
            .navigationTitle("Action progress")
            .toolbar { Button("Done") { dismiss() } }
        }
    }

    private var statusTint: Color {
        switch displayed.status {
        case "failed": .red
        case "unverified": .orange
        default: DriveTheme.accent
        }
    }

    private func symbol(for status: String) -> String {
        switch status {
        case "failed", "unsupported": "xmark.circle.fill"
        case "accepted", "reconciled": "checkmark.circle.fill"
        default: "clock.fill"
        }
    }

    private func tint(for status: String) -> Color {
        ["failed", "unsupported"].contains(status) ? .red : DriveTheme.accent
    }
}
