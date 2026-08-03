import Foundation
import LocalAuthentication
import Observation
import PilotClientKit
import Security

protocol DeviceAuthenticator: Sendable {
    func authenticate(reason: String) async throws
}

struct LocalDeviceAuthenticator: DeviceAuthenticator {
    func authenticate(reason: String) async throws {
        let context = LAContext()
        context.localizedCancelTitle = "Cancel"
        var error: NSError?
        guard context.canEvaluatePolicy(.deviceOwnerAuthentication, error: &error) else {
            throw error ?? LAError(.biometryNotAvailable)
        }
        try await context.evaluatePolicy(.deviceOwnerAuthentication, localizedReason: reason)
    }
}

@MainActor
@Observable
final class DriveModel {
    static let productionCoreURL = URL(string: "https://pilot.jameshomeautomation.work")!
    private static let legacyCoreHosts: Set<String> = ["10.0.1.64", "10.0.1.204"]
    var credentials: PilotCredentials?
    var manifest: PilotClientManifest?
    var vehicles: [VehicleSummary] = []
    var selectedVehicleID: String?
    var overview: VehicleOverview?
    var drives: [VehicleDrive] = []
    var charges: [VehicleCharge] = []
    var batteryHealth: BatteryHealth?
    var destinations: [SavedDestination] = []
    var maintenance: [MaintenanceRecord] = []
    var selectedDrive: VehicleDrive?
    var activeAction: VehicleAction?
    var isLoading = false
    var isOffline = false
    var historyUnavailable = false
    var pairingText = ""
    var errorMessage: String?
    var lastRefresh: Date?

    @ObservationIgnored private let vault: PilotCredentialVault
    @ObservationIgnored private let authenticator: any DeviceAuthenticator
    @ObservationIgnored private let cacheURL: URL
    @ObservationIgnored private var eventCursor: String?
    @ObservationIgnored private var eventTask: Task<Void, Never>?

    init(
        vault: PilotCredentialVault = PilotCredentialVault(
            service: "com.jameshazell.pilotdrive"
        ),
        authenticator: any DeviceAuthenticator = LocalDeviceAuthenticator(),
        cacheURL: URL? = nil
    ) {
        self.vault = vault
        self.authenticator = authenticator
        self.cacheURL = cacheURL ?? Self.defaultCacheURL()
        restoreCache()
        do {
            if let saved = try vault.load() {
                let migrated = Self.migrateLegacyCredentials(saved)
                if migrated != saved { try vault.save(migrated) }
                credentials = migrated
            }
        } catch PilotClientError.keychain(let status)
            where status == errSecMissingEntitlement {
            // Unsigned simulator builds cannot read Keychain. They remain
            // safely unpaired; production builds still surface all failures.
            credentials = nil
        } catch {
            errorMessage = error.localizedDescription
        }
        eventCursor = UserDefaults.standard.string(forKey: "pilotdrive.events.cursor")
    }

    deinit { eventTask?.cancel() }

    var selectedVehicle: VehicleSummary? {
        vehicles.first(where: { $0.id == selectedVehicleID })
    }

    var isPaired: Bool { credentials != nil }

    var canControl: Bool { manifest?.features["vehicle_control"] == true }

    var canMaintain: Bool { manifest?.features["vehicle_maintenance"] == true }

    func run() async {
        guard credentials != nil else { return }
        await refreshAll()
        startEvents()
    }

    func pair() async {
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }
        do {
            let candidate: PilotCredentials
            if let managed = try? PilotCredentialBundle.parse(pairingText) {
                candidate = managed
            } else {
                let payload = try PilotPairingPayload.parse(
                    pairingText,
                    defaultCoreURL: Self.productionCoreURL
                )
                candidate = try await PilotTransport.redeem(payload)
            }
            let api = try DriveAPI(credentials: candidate)
            let candidateManifest = try await api.manifest()
            guard candidateManifest.features["vehicle_read"] == true else {
                throw PilotClientError.authentication(
                    "This pairing does not include the vehicle-read capability."
                )
            }
            try vault.save(candidate)
            credentials = candidate
            manifest = candidateManifest
            pairingText = ""
            await refreshAll()
            startEvents()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    static func migrateLegacyCredentials(_ credentials: PilotCredentials) -> PilotCredentials {
        guard let host = credentials.coreURL.host,
              legacyCoreHosts.contains(host) else { return credentials }
        return PilotCredentials(
            coreURL: productionCoreURL,
            deviceID: credentials.deviceID,
            deviceToken: credentials.deviceToken,
            credentialRevision: credentials.credentialRevision
        )
    }

    func disconnect() {
        eventTask?.cancel()
        eventTask = nil
        do { try vault.remove() } catch { errorMessage = error.localizedDescription }
        credentials = nil
        manifest = nil
        vehicles = []
        selectedVehicleID = nil
        activeAction = nil
    }

    func rotateCredentials() async {
        guard let credentials else { return }
        do {
            let transport = try PilotTransport(credentials: credentials)
            let replacement = try await transport.rotateCredentials()
            try vault.save(replacement)
            self.credentials = replacement
            startEvents()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func refreshAll() async {
        guard let credentials else { return }
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }
        do {
            let api = try DriveAPI(credentials: credentials)
            async let manifestRequest = api.manifest()
            async let vehicleRequest = api.vehicles()
            let (loadedManifest, envelope) = try await (manifestRequest, vehicleRequest)
            guard loadedManifest.features["vehicle_read"] == true else {
                throw PilotClientError.authentication("Vehicle access has been revoked.")
            }
            manifest = loadedManifest
            vehicles = envelope.items
            if selectedVehicleID == nil || !vehicles.contains(where: { $0.id == selectedVehicleID }) {
                selectedVehicleID = vehicles.first?.id
            }
            guard let vehicleID = selectedVehicleID else {
                throw PilotClientError.invalidResponse
            }
            // Live Home Assistant state is the primary Car experience. The
            // TeslaMate history adapter is deliberately optional: an outage
            // must not make an otherwise healthy vehicle appear unavailable.
            let loadedOverview = try await api.overview(vehicleID)
            overview = loadedOverview
            if let loadedDestinations = try? await api.destinations(vehicleID) {
                destinations = loadedDestinations.items
            }
            if let loadedMaintenance = try? await api.maintenance(
                vehicleID,
                odometerKM: loadedOverview.number("odometer_km")
            ) {
                maintenance = loadedMaintenance.items
            }
            let loadedDrives = try? await api.drives(vehicleID)
            let loadedCharges = try? await api.charges(vehicleID)
            let loadedHealth = try? await api.batteryHealth(vehicleID)
            if let loadedDrives { drives = loadedDrives.items }
            if let loadedCharges { charges = loadedCharges.items }
            if let loadedHealth { batteryHealth = loadedHealth }
            historyUnavailable = loadedDrives == nil
                || loadedCharges == nil
                || loadedHealth == nil
            isOffline = false
            lastRefresh = Date()
            saveCache()
        } catch {
            isOffline = true
            errorMessage = error.localizedDescription
        }
    }

    func loadDrive(_ drive: VehicleDrive) async {
        guard let credentials, let vehicleID = selectedVehicleID else { return }
        selectedDrive = drive
        do {
            selectedDrive = try await DriveAPI(credentials: credentials).drive(
                vehicleID,
                driveID: drive.id
            )
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func saveDestination(_ draft: DestinationDraft, id: String? = nil) async -> Bool {
        guard let credentials, let vehicleID = selectedVehicleID else { return false }
        do {
            _ = try await DriveAPI(credentials: credentials).saveDestination(
                draft,
                vehicleID: vehicleID,
                destinationID: id
            )
            destinations = try await DriveAPI(credentials: credentials).destinations(vehicleID).items
            saveCache()
            return true
        } catch {
            errorMessage = error.localizedDescription
            return false
        }
    }

    func deleteDestination(_ destination: SavedDestination) async {
        guard let credentials, let vehicleID = selectedVehicleID else { return }
        do {
            try await DriveAPI(credentials: credentials).deleteDestination(
                destination.id,
                vehicleID: vehicleID
            )
            destinations.removeAll(where: { $0.id == destination.id })
            saveCache()
        } catch { errorMessage = error.localizedDescription }
    }

    func saveMaintenance(_ draft: MaintenanceDraft, id: String? = nil) async -> Bool {
        guard let credentials, let vehicleID = selectedVehicleID else { return false }
        do {
            _ = try await DriveAPI(credentials: credentials).saveMaintenance(
                draft,
                vehicleID: vehicleID,
                maintenanceID: id
            )
            await refreshMaintenance()
            return true
        } catch {
            errorMessage = error.localizedDescription
            return false
        }
    }

    func deleteMaintenance(_ record: MaintenanceRecord) async {
        guard let credentials, let vehicleID = selectedVehicleID else { return }
        do {
            try await DriveAPI(credentials: credentials).deleteMaintenance(
                record.id,
                vehicleID: vehicleID
            )
            maintenance.removeAll(where: { $0.id == record.id })
            saveCache()
        } catch { errorMessage = error.localizedDescription }
    }

    func uploadReceipt(
        data: Data,
        filename: String,
        contentType: String,
        record: MaintenanceRecord
    ) async -> Bool {
        guard let credentials, let vehicleID = selectedVehicleID else { return false }
        do {
            _ = try await DriveAPI(credentials: credentials).uploadReceipt(
                data,
                filename: filename,
                contentType: contentType,
                maintenanceID: record.id,
                vehicleID: vehicleID
            )
            await refreshMaintenance()
            return true
        } catch {
            errorMessage = error.localizedDescription
            return false
        }
    }

    func downloadReceipt(
        _ attachment: MaintenanceAttachment,
        record: MaintenanceRecord
    ) async -> URL? {
        guard let credentials, let vehicleID = selectedVehicleID else { return nil }
        do {
            let data = try await DriveAPI(credentials: credentials).receipt(
                attachment.id,
                maintenanceID: record.id,
                vehicleID: vehicleID
            )
            let directory = FileManager.default.temporaryDirectory
                .appending(path: "PilotDriveReceipts", directoryHint: .isDirectory)
            try FileManager.default.createDirectory(
                at: directory,
                withIntermediateDirectories: true
            )
            let destination = directory.appending(
                path: "\(attachment.id)-\(attachment.filename)"
            )
            try data.write(to: destination, options: [.atomic, .completeFileProtection])
            return destination
        } catch {
            errorMessage = error.localizedDescription
            return nil
        }
    }

    @discardableResult
    func perform(
        _ action: String,
        parameters: [String: PilotJSONValue] = [:]
    ) async -> VehicleAction? {
        guard let credentials, let vehicleID = selectedVehicleID else { return nil }
        errorMessage = nil
        do {
            let api = try DriveAPI(credentials: credentials)
            var request = try await api.requestAction(
                action,
                parameters: parameters,
                vehicleID: vehicleID,
                idempotencyKey: UUID().uuidString
            )
            activeAction = request
            if request.confirmationRequired {
                try await authenticateSensitiveAction(action)
                request = try await api.confirmAction(request.id)
                activeAction = request
            }
            return await pollAction(request.id, api: api)
        } catch {
            errorMessage = error.localizedDescription
            return nil
        }
    }

    func send(_ destination: SavedDestination) async {
        _ = await perform(
            "destination_workflow",
            parameters: ["destination_id": .string(destination.id)]
        )
    }

    func retryActiveAction() async {
        guard let activeAction else { return }
        _ = await perform(activeAction.action, parameters: activeAction.parameters)
    }

    private func pollAction(_ actionID: String, api: DriveAPI) async -> VehicleAction? {
        for _ in 0..<90 {
            do {
                let result = try await api.action(actionID)
                activeAction = result
                if !["requested", "accepted", "executing"].contains(result.status) {
                    await refreshOverview()
                    return result
                }
            } catch {
                errorMessage = error.localizedDescription
                return nil
            }
            try? await Task.sleep(for: .seconds(1))
        }
        errorMessage = "Pilot Core is still working on this command. Its result will update when available."
        return activeAction
    }

    func authenticateSensitiveAction(_ action: String) async throws {
        try await authenticator.authenticate(
            reason: "Confirm \(action.replacingOccurrences(of: "_", with: " ")) for \(overview?.name ?? "your vehicle")"
        )
    }

    private func refreshOverview() async {
        guard let credentials, let vehicleID = selectedVehicleID else { return }
        overview = try? await DriveAPI(credentials: credentials).overview(vehicleID)
        saveCache()
    }

    private func refreshMaintenance() async {
        guard let credentials, let vehicleID = selectedVehicleID else { return }
        do {
            maintenance = try await DriveAPI(credentials: credentials).maintenance(
                vehicleID,
                odometerKM: overview?.number("odometer_km")
            ).items
            saveCache()
        } catch { errorMessage = error.localizedDescription }
    }

    private func startEvents() {
        eventTask?.cancel()
        guard credentials != nil else { return }
        eventTask = Task { [weak self] in
            await self?.eventLoop()
        }
    }

    private func eventLoop() async {
        while !Task.isCancelled, let credentials {
            do {
                let api = try DriveAPI(credentials: credentials)
                let envelope = try await api.pollEvents(after: eventCursor)
                if envelope.resetRequired == true || envelope.resyncRequired == true {
                    let snapshot = try await api.eventSnapshot(after: eventCursor)
                    eventCursor = snapshot.cursor
                    await refreshAll()
                } else {
                    eventCursor = envelope.cursor
                    if !envelope.events.isEmpty { await refreshAll() }
                }
                UserDefaults.standard.set(eventCursor, forKey: "pilotdrive.events.cursor")
            } catch {
                isOffline = true
                try? await Task.sleep(for: .seconds(5))
            }
        }
    }

    private func saveCache() {
        let cache = DriveCache(
            overview: overview,
            drives: drives,
            charges: charges,
            batteryHealth: batteryHealth,
            destinations: destinations,
            maintenance: maintenance,
            savedAt: Date()
        )
        do {
            let data = try JSONEncoder().encode(cache)
            try FileManager.default.createDirectory(
                at: cacheURL.deletingLastPathComponent(),
                withIntermediateDirectories: true
            )
            try data.write(to: cacheURL, options: [.atomic, .completeFileProtection])
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func restoreCache() {
        guard let data = try? Data(contentsOf: cacheURL),
              let cache = try? JSONDecoder().decode(DriveCache.self, from: data)
        else { return }
        overview = cache.overview
        drives = cache.drives
        charges = cache.charges
        batteryHealth = cache.batteryHealth
        destinations = cache.destinations
        maintenance = cache.maintenance
        lastRefresh = cache.savedAt
    }

    private static func defaultCacheURL() -> URL {
        let directory = FileManager.default.urls(
            for: .applicationSupportDirectory,
            in: .userDomainMask
        ).first ?? FileManager.default.temporaryDirectory
        return directory
            .appending(path: "PilotDrive", directoryHint: .isDirectory)
            .appending(path: "vehicle-cache-v1.json")
    }
}
