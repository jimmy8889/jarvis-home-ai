import Foundation
import PilotClientKit

struct DriveAPI: Sendable {
    let transport: PilotTransport
    private var deviceID: String { transport.credentials.deviceID }
    private var deviceBase: String { "v1/devices/\(deviceID)" }

    init(credentials: PilotCredentials, session: URLSession = .shared) throws {
        transport = try PilotTransport(
            credentials: credentials,
            allowsInsecureHTTP: false,
            session: session
        )
    }

    func manifest() async throws -> PilotClientManifest { try await transport.manifest() }

    func vehicles() async throws -> VehicleListEnvelope {
        try await transport.decode(VehicleListEnvelope.self, path: "\(deviceBase)/vehicles")
    }

    func overview(_ vehicleID: String) async throws -> VehicleOverview {
        try await transport.decode(
            VehicleOverview.self,
            path: "\(deviceBase)/vehicles/\(vehicleID)"
        )
    }

    func drives(_ vehicleID: String, cursor: Int? = nil) async throws -> DriveEnvelope {
        var query = [URLQueryItem(name: "limit", value: "100")]
        if let cursor { query.append(URLQueryItem(name: "cursor", value: String(cursor))) }
        return try await transport.decode(
            DriveEnvelope.self,
            path: "\(deviceBase)/vehicles/\(vehicleID)/drives",
            queryItems: query
        )
    }

    func drive(_ vehicleID: String, driveID: Int) async throws -> VehicleDrive {
        try await transport.decode(
            VehicleDrive.self,
            path: "\(deviceBase)/vehicles/\(vehicleID)/drives/\(driveID)"
        )
    }

    func charges(_ vehicleID: String, cursor: Int? = nil) async throws -> ChargeEnvelope {
        var query = [URLQueryItem(name: "limit", value: "100")]
        if let cursor { query.append(URLQueryItem(name: "cursor", value: String(cursor))) }
        return try await transport.decode(
            ChargeEnvelope.self,
            path: "\(deviceBase)/vehicles/\(vehicleID)/charges",
            queryItems: query
        )
    }

    func batteryHealth(_ vehicleID: String) async throws -> BatteryHealth {
        try await transport.decode(
            BatteryHealth.self,
            path: "\(deviceBase)/vehicles/\(vehicleID)/battery-health"
        )
    }

    func destinations(_ vehicleID: String) async throws -> DestinationEnvelope {
        try await transport.decode(
            DestinationEnvelope.self,
            path: "\(deviceBase)/vehicles/\(vehicleID)/destinations"
        )
    }

    func saveDestination(
        _ draft: DestinationDraft,
        vehicleID: String,
        destinationID: String? = nil
    ) async throws -> SavedDestination {
        let suffix = destinationID.map { "/\($0)" } ?? ""
        return try await transport.decode(
            SavedDestination.self,
            path: "\(deviceBase)/vehicles/\(vehicleID)/destinations\(suffix)",
            method: destinationID == nil ? "POST" : "PUT",
            body: try JSONEncoder().encode(draft)
        )
    }

    func deleteDestination(_ destinationID: String, vehicleID: String) async throws {
        _ = try await transport.data(
            path: "\(deviceBase)/vehicles/\(vehicleID)/destinations/\(destinationID)",
            method: "DELETE"
        )
    }

    func maintenance(_ vehicleID: String, odometerKM: Double?) async throws -> MaintenanceEnvelope {
        let query = odometerKM.map {
            [URLQueryItem(name: "odometer_km", value: String($0))]
        } ?? []
        return try await transport.decode(
            MaintenanceEnvelope.self,
            path: "\(deviceBase)/vehicles/\(vehicleID)/maintenance",
            queryItems: query
        )
    }

    func saveMaintenance(
        _ draft: MaintenanceDraft,
        vehicleID: String,
        maintenanceID: String? = nil
    ) async throws -> MaintenanceRecord {
        let suffix = maintenanceID.map { "/\($0)" } ?? ""
        return try await transport.decode(
            MaintenanceRecord.self,
            path: "\(deviceBase)/vehicles/\(vehicleID)/maintenance\(suffix)",
            method: maintenanceID == nil ? "POST" : "PUT",
            body: try JSONEncoder().encode(draft)
        )
    }

    func deleteMaintenance(_ maintenanceID: String, vehicleID: String) async throws {
        _ = try await transport.data(
            path: "\(deviceBase)/vehicles/\(vehicleID)/maintenance/\(maintenanceID)",
            method: "DELETE"
        )
    }

    func uploadReceipt(
        _ data: Data,
        filename: String,
        contentType: String,
        maintenanceID: String,
        vehicleID: String
    ) async throws -> MaintenanceAttachment {
        let responseData = try await transport.data(
            path: "\(deviceBase)/vehicles/\(vehicleID)/maintenance/\(maintenanceID)/attachments",
            method: "POST",
            body: data,
            queryItems: [URLQueryItem(name: "filename", value: filename)],
            contentType: contentType
        )
        return try JSONDecoder().decode(MaintenanceAttachment.self, from: responseData)
    }

    func receipt(
        _ attachmentID: String,
        maintenanceID: String,
        vehicleID: String
    ) async throws -> Data {
        try await transport.data(
            path: "\(deviceBase)/vehicles/\(vehicleID)/maintenance/\(maintenanceID)/attachments/\(attachmentID)"
        )
    }

    func requestAction(
        _ action: String,
        parameters: [String: PilotJSONValue] = [:],
        vehicleID: String,
        idempotencyKey: String
    ) async throws -> VehicleAction {
        let request = VehicleActionRequest(
            action: action,
            parameters: parameters,
            idempotencyKey: idempotencyKey
        )
        return try await transport.decode(
            VehicleAction.self,
            path: "\(deviceBase)/vehicles/\(vehicleID)/actions",
            method: "POST",
            body: try JSONEncoder().encode(request)
        )
    }

    func action(_ actionID: String) async throws -> VehicleAction {
        try await transport.decode(
            VehicleAction.self,
            path: "\(deviceBase)/actions/\(actionID)"
        )
    }

    func confirmAction(_ actionID: String) async throws -> VehicleAction {
        try await transport.decode(
            VehicleAction.self,
            path: "\(deviceBase)/actions/\(actionID)/confirm",
            method: "POST",
            body: Data(#"{"biometric_verified":true}"#.utf8)
        )
    }

    func pollEvents(after cursor: String?) async throws -> PilotEventSnapshot {
        try await transport.pollEvents(after: cursor)
    }

    func eventSnapshot(after cursor: String?) async throws -> PilotEventSnapshot {
        try await transport.eventSnapshot(after: cursor)
    }
}

private struct VehicleActionRequest: Encodable {
    let action: String
    let parameters: [String: PilotJSONValue]
    let idempotencyKey: String

    enum CodingKeys: String, CodingKey {
        case action, parameters
        case idempotencyKey = "idempotency_key"
    }
}
