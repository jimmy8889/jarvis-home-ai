import PilotClientKit
import SwiftUI

struct RootView: View {
    @Bindable var model: DriveModel

    var body: some View {
        Group {
            if model.isPaired {
                TabView {
                    CarView(model: model)
                        .tabItem { Label("Car", systemImage: "car.side.fill") }
                    DrivesView(model: model)
                        .tabItem { Label("Drives", systemImage: "road.lanes") }
                    ChargingView(model: model)
                        .tabItem { Label("Charging", systemImage: "bolt.car.fill") }
                    CareView(model: model)
                        .tabItem { Label("Care", systemImage: "wrench.and.screwdriver.fill") }
                }
                .tint(DriveTheme.accent)
                .overlay(alignment: .top) {
                    if model.isOffline {
                        Label("Offline — showing saved data", systemImage: "wifi.slash")
                            .font(.caption.weight(.semibold))
                            .padding(.horizontal, 12)
                            .padding(.vertical, 7)
                            .background(.orange, in: Capsule())
                            .padding(.top, 4)
                            .accessibilityLabel("Offline. Showing saved vehicle data.")
                    }
                }
            } else {
                PairingView(model: model)
            }
        }
        .alert("Pilot Drive", isPresented: Binding(
            get: { model.errorMessage != nil },
            set: { if !$0 { model.errorMessage = nil } }
        )) {
            Button("OK") { model.errorMessage = nil }
        } message: {
            Text(model.errorMessage ?? "")
        }
    }
}

struct PairingView: View {
    @Bindable var model: DriveModel

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 24) {
                    Image(systemName: "car.side.fill")
                        .font(.system(size: 66, weight: .semibold))
                        .foregroundStyle(DriveTheme.accent)
                        .accessibilityHidden(true)
                    VStack(spacing: 8) {
                        Text("Pilot Drive")
                            .font(.largeTitle.bold())
                        Text("Your private companion for Jarvis")
                            .foregroundStyle(.secondary)
                    }
                    VStack(alignment: .leading, spacing: 12) {
                        Text("Pair with Pilot Core")
                            .font(.headline)
                        Text("Create a Vehicle phone pairing code or managed Pilot Drive API key in Pilot Core, then paste it here. Pilot Drive connects through the trusted public HTTPS endpoint.")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                        ZStack(alignment: .topLeading) {
                            TextEditor(text: $model.pairingText)
                                .font(.system(.footnote, design: .monospaced))
                                .scrollContentBackground(.hidden)
                                .textInputAutocapitalization(.never)
                                .autocorrectionDisabled()
                            if model.pairingText.isEmpty {
                                Text("Paste pairing code or API key bundle")
                                    .font(.footnote)
                                    .foregroundStyle(.tertiary)
                                    .padding(.horizontal, 5)
                                    .padding(.vertical, 8)
                                    .allowsHitTesting(false)
                            }
                        }
                        .frame(minHeight: 120)
                        .padding(8)
                        .background(.background, in: RoundedRectangle(cornerRadius: 12))
                        .accessibilityElement(children: .contain)
                        .accessibilityLabel("Pilot Core pairing code or API key bundle")
                        Button {
                            Task { await model.pair() }
                        } label: {
                            Label(model.isLoading ? "Pairing…" : "Pair securely", systemImage: "lock.shield")
                                .frame(maxWidth: .infinity)
                        }
                        .buttonStyle(.borderedProminent)
                        .tint(DriveTheme.accent)
                        .disabled(model.pairingText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || model.isLoading)
                    }
                    .pilotCard()
                }
                .frame(maxWidth: 560)
                .padding()
                .frame(maxWidth: .infinity)
            }
            .background(
                LinearGradient(
                    colors: [DriveTheme.accent.opacity(0.15), .clear],
                    startPoint: .top,
                    endPoint: .center
                )
            )
        }
    }
}

struct SettingsView: View {
    @Bindable var model: DriveModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            Form {
                Section("Pilot Core") {
                    LabeledContent("Host", value: model.credentials?.coreURL.host ?? "Unknown")
                    LabeledContent("Device", value: model.credentials?.deviceID ?? "Unknown")
                    LabeledContent("Connection", value: model.isOffline ? "Offline" : "Connected")
                    if let lastRefresh = model.lastRefresh {
                        LabeledContent("Last refresh", value: lastRefresh.formatted(date: .abbreviated, time: .shortened))
                    }
                }
                Section("Security") {
                    Button("Rotate device credentials") {
                        Task { await model.rotateCredentials() }
                    }
                    Button("Unpair this device", role: .destructive) {
                        model.disconnect()
                        dismiss()
                    }
                }
                Section {
                    Text("Pilot Drive stores its device credential in the Keychain. Tesla, TeslaMate, Home Assistant, database, and MQTT credentials never enter this app.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
            }
            .navigationTitle("Settings")
            .toolbar { Button("Done") { dismiss() } }
        }
    }
}
