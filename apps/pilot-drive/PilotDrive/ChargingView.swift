import SwiftUI

struct ChargingView: View {
    @Bindable var model: DriveModel

    var body: some View {
        NavigationStack {
            ScrollView {
                LazyVStack(spacing: 16) {
                    currentSession
                    batteryHealthCard
                    history
                }
                .padding()
            }
            .navigationTitle("Charging")
            .refreshable { await model.refreshAll() }
        }
    }

    @ViewBuilder
    private var currentSession: some View {
        if let car = model.overview {
            VStack(alignment: .leading, spacing: 14) {
                HStack {
                    Label("Current session", systemImage: "bolt.car.fill")
                        .font(.headline)
                    Spacer()
                    StatusPill(text: car.text("charging_state") ?? "Unavailable")
                }
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 140), spacing: 10)], spacing: 10) {
                    MetricTile(title: "Battery", value: car.number("battery_percent").map { "\(Int($0))%" } ?? "—", symbol: "battery.75percent")
                    MetricTile(title: "Power", value: car.number("charge_rate_kw").map { "\($0.formatted(.number.precision(.fractionLength(1)))) kW" } ?? "—", symbol: "bolt.fill")
                    MetricTile(title: "Energy added", value: car.number("energy_added_kwh").map { "\($0.formatted(.number.precision(.fractionLength(1)))) kWh" } ?? "—", symbol: "plus.circle")
                    MetricTile(title: "Limit", value: car.number("charge_limit_percent").map { "\(Int($0))%" } ?? "—", symbol: "slider.horizontal.3")
                    MetricTile(title: "Time remaining", value: car.number("time_to_full_hours").map { Duration.seconds($0 * 3_600).formatted(.units(allowed: [.hours, .minutes])) } ?? "—", symbol: "clock")
                    MetricTile(title: "Port", value: car.flag("charge_port") == true ? "Open" : "Closed", symbol: "powerplug")
                }
            }
            .pilotCard()
        }
    }

    @ViewBuilder
    private var batteryHealthCard: some View {
        if let health = model.batteryHealth {
            VStack(alignment: .leading, spacing: 13) {
                HStack {
                    Label("Battery health", systemImage: "waveform.path.ecg.rectangle")
                        .font(.headline)
                    Spacer()
                    StatusPill(text: health.status, tint: health.status == "estimate" ? DriveTheme.accent : .orange)
                }
                if health.status == "estimate" {
                    HStack(alignment: .firstTextBaseline) {
                        Text(health.estimatedDegradationPercent.map { "\($0.formatted(.number.precision(.fractionLength(2))))%" } ?? "—")
                            .font(.system(size: 38, weight: .bold, design: .rounded))
                        Text("estimated degradation")
                            .foregroundStyle(.secondary)
                    }
                    LazyVGrid(columns: [GridItem(.adaptive(minimum: 140), spacing: 10)], spacing: 10) {
                        MetricTile(title: "Estimated capacity", value: health.estimatedCapacityKwh.map { "\($0.formatted(.number.precision(.fractionLength(2)))) kWh" } ?? "—", symbol: "battery.100percent")
                        MetricTile(title: "Baseline", value: health.baselineCapacityKwh.map { "\($0.formatted(.number.precision(.fractionLength(2)))) kWh" } ?? "—", symbol: "chart.line.uptrend.xyaxis", detail: health.baselineSource?.replacingOccurrences(of: "_", with: " ").capitalized)
                        MetricTile(title: "Samples", value: String(health.sampleCount), symbol: "number", detail: "Latest qualified samples, maximum 100")
                        MetricTile(title: "Derived efficiency", value: health.derivedEfficiencyWhPerKm.map { "\(Int($0)) Wh/km" } ?? "Fallback", symbol: "function")
                    }
                    Text("Coverage: \(Formatters.date(health.dateFrom)) to \(Formatters.date(health.dateTo))")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                } else {
                    Label("There are not enough qualifying completed charging samples to estimate battery capacity. No capacity or degradation value has been fabricated.", systemImage: "info.circle.fill")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
                Text(health.label ?? "Estimate based on TeslaMate qualified charging sessions")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            .pilotCard()
        }
    }

    private var history: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("History").font(.headline)
            if model.charges.isEmpty {
                Text(model.historyUnavailable
                    ? "Live charging state is connected. TeslaMate charging history is temporarily offline."
                    : "No TeslaMate charging sessions have been recorded yet.")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            } else {
                ForEach(model.charges) { charge in
                    ChargeRow(charge: charge)
                    if charge.id != model.charges.last?.id { Divider() }
                }
            }
        }
        .pilotCard()
    }
}

private struct ChargeRow: View {
    let charge: VehicleCharge

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .top) {
                VStack(alignment: .leading) {
                    Text(charge.address ?? "Unknown charging location")
                        .font(.headline)
                    Text(Formatters.date(charge.startDate))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                StatusPill(text: charge.chargeType ?? "Unknown")
                if charge.incomplete {
                    Image(systemName: "exclamationmark.triangle.fill")
                        .foregroundStyle(.orange)
                        .accessibilityLabel("Incomplete charging data")
                }
            }
            HStack(spacing: 14) {
                Label(socText, systemImage: "battery.75percent")
                Label(Formatters.duration(minutes: charge.durationMin), systemImage: "clock")
            }
            .font(.caption)
            HStack(spacing: 14) {
                Label(charge.chargeEnergyAdded.map { "\($0.formatted(.number.precision(.fractionLength(1)))) kWh added" } ?? "Energy unavailable", systemImage: "bolt.fill")
                if let efficiency = charge.efficiencyPercent {
                    Text("\(efficiency.formatted(.number.precision(.fractionLength(1))))% efficient")
                }
            }
            .font(.caption)
            .foregroundStyle(.secondary)
            HStack {
                if let power = charge.maximumChargerPowerKw {
                    Text("Peak \(power.formatted(.number.precision(.fractionLength(1)))) kW")
                }
                Spacer()
                if let cost = charge.cost {
                    Text(cost, format: .currency(code: "AUD"))
                        .fontWeight(.semibold)
                }
            }
            .font(.caption)
        }
        .padding(.vertical, 4)
        .accessibilityElement(children: .combine)
    }

    private var socText: String {
        guard let start = charge.startBatteryLevel, let end = charge.endBatteryLevel else { return "SOC unavailable" }
        return "\(start)% → \(end)%"
    }
}
