import MapKit
import SwiftUI

struct DrivesView: View {
    @Bindable var model: DriveModel
    @State private var search = ""
    @State private var route: VehicleDrive?

    private var filtered: [VehicleDrive] {
        guard !search.isEmpty else { return model.drives }
        return model.drives.filter {
            [String($0.id), $0.startAddress ?? "", $0.endAddress ?? ""]
                .joined(separator: " ")
                .localizedCaseInsensitiveContains(search)
        }
    }

    var body: some View {
        NavigationStack {
            Group {
                if filtered.isEmpty {
                    EmptyState(
                        symbol: "road.lanes",
                        title: search.isEmpty ? "No drives yet" : "No matching drives",
                        detail: search.isEmpty
                            ? (model.historyUnavailable
                                ? "Live vehicle data is connected. TeslaMate drive history is temporarily offline."
                                : "TeslaMate history will appear after the first recorded drive.")
                            : "Try a different place or address."
                    )
                } else {
                    List(filtered) { drive in
                        Button {
                            route = drive
                            Task {
                                await model.loadDrive(drive)
                                route = model.selectedDrive
                            }
                        } label: {
                            DriveRow(drive: drive)
                        }
                        .buttonStyle(.plain)
                    }
                    .listStyle(.insetGrouped)
                }
            }
            .navigationTitle("Drives")
            .searchable(text: $search, prompt: "Search locations")
            .refreshable { await model.refreshAll() }
            .sheet(item: $route) { drive in
                DriveDetailView(drive: model.selectedDrive?.id == drive.id ? model.selectedDrive ?? drive : drive)
            }
        }
    }
}

private struct DriveRow: View {
    let drive: VehicleDrive

    var body: some View {
        VStack(alignment: .leading, spacing: 9) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 3) {
                    Text(drive.startAddress ?? "Unknown start")
                        .font(.headline)
                    Label(drive.endAddress ?? "Unknown destination", systemImage: "arrow.turn.down.right")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                if drive.incomplete {
                    Image(systemName: "exclamationmark.triangle.fill")
                        .foregroundStyle(.orange)
                        .accessibilityLabel("Incomplete data")
                }
            }
            HStack(spacing: 16) {
                Label(drive.distance.map { "\($0.formatted(.number.precision(.fractionLength(1)))) km" } ?? "—", systemImage: "point.topleft.down.to.point.bottomright.curvepath")
                Label(Formatters.duration(minutes: drive.durationMin), systemImage: "clock")
                if let consumption = drive.estimatedConsumptionWhPerKm {
                    Label("\(Int(consumption)) Wh/km", systemImage: "bolt")
                }
            }
            .font(.caption)
            .foregroundStyle(.secondary)
            Text(Formatters.date(drive.startDate))
                .font(.caption2)
                .foregroundStyle(.tertiary)
        }
        .padding(.vertical, 5)
        .accessibilityElement(children: .combine)
    }
}

struct DriveDetailView: View {
    let drive: VehicleDrive
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 16) {
                    if let positions = drive.positions, positions.count > 1 {
                        Map(initialPosition: .region(region(for: positions))) {
                            MapPolyline(coordinates: positions.map(\.coordinate))
                                .stroke(DriveTheme.accent, lineWidth: 5)
                            if let first = positions.first {
                                Marker("Start", coordinate: first.coordinate)
                            }
                            if let last = positions.last {
                                Marker("End", coordinate: last.coordinate)
                            }
                        }
                        .frame(height: 330)
                        .clipShape(RoundedRectangle(cornerRadius: 20))
                        .accessibilityLabel("Map of this drive")
                    } else {
                        EmptyState(
                            symbol: "map",
                            title: "Route unavailable",
                            detail: "TeslaMate did not return enough positions for this drive."
                        )
                        .frame(minHeight: 220)
                    }
                    VStack(alignment: .leading, spacing: 10) {
                        Label(drive.startAddress ?? "Unknown start", systemImage: "circle.fill")
                        Label(drive.endAddress ?? "Unknown end", systemImage: "mappin.circle.fill")
                        Divider()
                        Text("\(Formatters.date(drive.startDate)) – \(Formatters.date(drive.endDate))")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .pilotCard()
                    LazyVGrid(columns: [GridItem(.adaptive(minimum: 145), spacing: 12)], spacing: 12) {
                        MetricTile(title: "Distance", value: drive.distance.map { "\($0.formatted(.number.precision(.fractionLength(1)))) km" } ?? "—", symbol: "road.lanes")
                        MetricTile(title: "Duration", value: Formatters.duration(minutes: drive.durationMin), symbol: "clock")
                        MetricTile(title: "SOC", value: socText, symbol: "battery.50percent")
                        MetricTile(title: "Estimated energy", value: drive.estimatedEnergyKwh.map { "\($0.formatted(.number.precision(.fractionLength(2)))) kWh" } ?? "—", symbol: "bolt.fill", detail: "Estimate from rated-range change")
                        MetricTile(title: "Consumption", value: drive.estimatedConsumptionWhPerKm.map { "\(Int($0)) Wh/km" } ?? "—", symbol: "gauge.with.dots.needle.67percent")
                        MetricTile(title: "Maximum speed", value: drive.speedMax.map { "\($0) km/h" } ?? "—", symbol: "speedometer")
                        MetricTile(title: "Inside temperature", value: drive.insideTempAvg.map { "\($0.formatted(.number.precision(.fractionLength(1))))°C" } ?? "—", symbol: "thermometer.medium")
                        MetricTile(title: "Outside temperature", value: drive.outsideTempAvg.map { "\($0.formatted(.number.precision(.fractionLength(1))))°C" } ?? "—", symbol: "thermometer.snowflake")
                    }
                    if drive.incomplete || drive.positionsTruncated == true {
                        Label(
                            drive.positionsTruncated == true ? "The route was truncated to the server safety limit." : "This drive has incomplete TeslaMate data.",
                            systemImage: "exclamationmark.triangle.fill"
                        )
                        .font(.footnote)
                        .foregroundStyle(.orange)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
                .padding()
            }
            .navigationTitle("Drive")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { Button("Done") { dismiss() } }
        }
    }

    private var socText: String {
        guard let start = drive.startBatteryLevel, let end = drive.endBatteryLevel else { return "—" }
        return "\(start)% → \(end)% (\(end - start)%)"
    }

    private func region(for positions: [DrivePosition]) -> MKCoordinateRegion {
        let latitudes = positions.map(\.latitude)
        let longitudes = positions.map(\.longitude)
        let minLatitude = latitudes.min() ?? 0
        let maxLatitude = latitudes.max() ?? 0
        let minLongitude = longitudes.min() ?? 0
        let maxLongitude = longitudes.max() ?? 0
        return MKCoordinateRegion(
            center: CLLocationCoordinate2D(
                latitude: (minLatitude + maxLatitude) / 2,
                longitude: (minLongitude + maxLongitude) / 2
            ),
            span: MKCoordinateSpan(
                latitudeDelta: max(maxLatitude - minLatitude, 0.01) * 1.25,
                longitudeDelta: max(maxLongitude - minLongitude, 0.01) * 1.25
            )
        )
    }
}
