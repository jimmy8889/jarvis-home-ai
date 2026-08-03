import MapKit
import SwiftUI

struct DestinationEditor: View {
    @Bindable var model: DriveModel
    let destination: SavedDestination?
    @Environment(\.dismiss) private var dismiss
    @State private var draft: DestinationDraft
    @State private var useTemperatureOverride: Bool
    @State private var isSaving = false

    init(model: DriveModel, destination: SavedDestination? = nil) {
        self.model = model
        self.destination = destination
        _draft = State(initialValue: DestinationDraft(destination: destination))
        _useTemperatureOverride = State(initialValue: destination?.temperatureC != nil)
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("Destination") {
                    TextField("Name", text: $draft.name)
                    TextField("Address", text: $draft.address, axis: .vertical)
                    Picker("Icon", selection: $draft.icon) {
                        Label("Pin", systemImage: "mappin").tag("mappin")
                        Label("Home", systemImage: "house.fill").tag("house.fill")
                        Label("Work", systemImage: "briefcase.fill").tag("briefcase.fill")
                        Label("Shopping", systemImage: "cart.fill").tag("cart.fill")
                        Label("Favourite", systemImage: "star.fill").tag("star.fill")
                    }
                }
                Section("Location") {
                    MapReader { proxy in
                        Map(initialPosition: .region(region)) {
                            Marker(draft.name.isEmpty ? "Destination" : draft.name, coordinate: coordinate)
                        }
                        .frame(minHeight: 270)
                        .clipShape(RoundedRectangle(cornerRadius: 14))
                        .onTapGesture { point in
                            if let coordinate = proxy.convert(point, from: .local) {
                                draft.latitude = coordinate.latitude
                                draft.longitude = coordinate.longitude
                            }
                        }
                        .accessibilityLabel("Destination map")
                        .accessibilityHint("Tap the map to move the destination pin")
                    }
                    LabeledContent("Latitude", value: draft.latitude.formatted(.number.precision(.fractionLength(5))))
                    LabeledContent("Longitude", value: draft.longitude.formatted(.number.precision(.fractionLength(5))))
                }
                Section("One-tap climate") {
                    Toggle("Start climate", isOn: $draft.climateEnabled)
                    if draft.climateEnabled {
                        Toggle("Use temperature override", isOn: $useTemperatureOverride)
                        if useTemperatureOverride {
                            Stepper(
                                "Target \(Int(draft.temperatureC ?? model.selectedVehicle?.defaultClimateTargetC ?? 22))°C",
                                value: Binding(
                                    get: { draft.temperatureC ?? model.selectedVehicle?.defaultClimateTargetC ?? 22 },
                                    set: { draft.temperatureC = $0 }
                                ),
                                in: 15...30
                            )
                        } else {
                            Text("Uses the Pilot Core default of \(Int(model.selectedVehicle?.defaultClimateTargetC ?? 22))°C.")
                                .font(.footnote)
                                .foregroundStyle(.secondary)
                        }
                        Picker("Front passenger seat", selection: $draft.seatClimateMode) {
                            Text("No change").tag(SeatClimateMode?.none)
                            ForEach(SeatClimateMode.allCases) { mode in
                                Text(mode.label).tag(SeatClimateMode?.some(mode))
                            }
                        }
                    }
                }
                Section {
                    Text("Sending this destination may wake the car, waits up to 60 seconds, starts climate, applies the optional front passenger seat setting, and sends coordinates to the touchscreen. Each step is reported independently.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
            }
            .navigationTitle(destination == nil ? "New destination" : "Edit destination")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(isSaving ? "Saving…" : "Save") {
                        Task {
                            isSaving = true
                            if !useTemperatureOverride { draft.temperatureC = nil }
                            if !draft.climateEnabled { draft.seatClimateMode = nil }
                            let saved = await model.saveDestination(draft, id: destination?.id)
                            isSaving = false
                            if saved { dismiss() }
                        }
                    }
                    .disabled(draft.name.trimmingCharacters(in: .whitespaces).isEmpty || draft.address.trimmingCharacters(in: .whitespaces).isEmpty || isSaving)
                }
            }
        }
    }

    private var coordinate: CLLocationCoordinate2D {
        CLLocationCoordinate2D(latitude: draft.latitude, longitude: draft.longitude)
    }

    private var region: MKCoordinateRegion {
        MKCoordinateRegion(
            center: coordinate,
            span: MKCoordinateSpan(latitudeDelta: 0.04, longitudeDelta: 0.04)
        )
    }
}
