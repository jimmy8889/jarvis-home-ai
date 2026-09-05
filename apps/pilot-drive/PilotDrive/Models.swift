import CoreLocation
import Foundation
import PilotClientKit

extension PilotJSONValue {
    var stringValue: String? {
        switch self {
        case let .string(value): value
        case let .number(value): String(value)
        case let .boolean(value): value ? "true" : "false"
        default: nil
        }
    }

    var doubleValue: Double? {
        switch self {
        case let .number(value): value
        case let .string(value): Double(value)
        default: nil
        }
    }

    var boolValue: Bool? {
        switch self {
        case let .boolean(value): value
        case let .string(value): ["true", "on", "yes", "open", "locked"].contains(value.lowercased())
        default: nil
        }
    }
}

struct VehicleSummary: Codable, Identifiable, Sendable {
    let id: String
    let name: String
    let defaultClimateTargetC: Double
    let availableControls: [String]

    enum CodingKeys: String, CodingKey {
        case id, name
        case defaultClimateTargetC = "default_climate_target_c"
        case availableControls = "available_controls"
    }
}

struct VehicleListEnvelope: Codable, Sendable {
    let items: [VehicleSummary]
}

struct TyreReading: Codable, Sendable {
    let valueBar: Double?
    let status: String
    let sourceUnit: String?

    enum CodingKeys: String, CodingKey {
        case status
        case valueBar = "value_bar"
        case sourceUnit = "source_unit"
    }
}

struct VehicleOverview: Codable, Sendable {
    let schemaVersion: String
    let id: String
    let name: String
    let observedAt: String?
    let freshness: String
    let state: [String: PilotJSONValue]
    let tyres: [String: TyreReading]
    let availableControls: [String]
    let providers: [String: PilotJSONValue]

    enum CodingKeys: String, CodingKey {
        case id, name, freshness, state, tyres, providers
        case schemaVersion = "schema_version"
        case observedAt = "observed_at"
        case availableControls = "available_controls"
    }

    func number(_ key: String) -> Double? { state[key]?.doubleValue }
    func text(_ key: String) -> String? { state[key]?.stringValue }
    func flag(_ key: String) -> Bool? { state[key]?.boolValue }
}

struct DrivePosition: Codable, Identifiable, Sendable {
    let id: Int
    let date: String?
    let latitude: Double
    let longitude: Double
    let speed: Int?
    let power: Double?
    let batteryLevel: Int?

    enum CodingKeys: String, CodingKey {
        case id, date, latitude, longitude, speed, power
        case batteryLevel = "battery_level"
    }

    var coordinate: CLLocationCoordinate2D {
        CLLocationCoordinate2D(latitude: latitude, longitude: longitude)
    }
}

struct VehicleDrive: Codable, Identifiable, Sendable {
    let id: Int
    let startDate: String?
    let endDate: String?
    let durationMin: Int?
    let distance: Double?
    let startAddress: String?
    let endAddress: String?
    let startBatteryLevel: Int?
    let endBatteryLevel: Int?
    let estimatedEnergyKwh: Double?
    let estimatedConsumptionWhPerKm: Double?
    let speedMax: Int?
    let outsideTempAvg: Double?
    let insideTempAvg: Double?
    let incomplete: Bool
    let positions: [DrivePosition]?
    let positionsTruncated: Bool?

    enum CodingKeys: String, CodingKey {
        case id, distance, incomplete, positions
        case startDate = "start_date"
        case endDate = "end_date"
        case durationMin = "duration_min"
        case startAddress = "start_address"
        case endAddress = "end_address"
        case startBatteryLevel = "start_battery_level"
        case endBatteryLevel = "end_battery_level"
        case estimatedEnergyKwh = "estimated_energy_kwh"
        case estimatedConsumptionWhPerKm = "estimated_consumption_wh_per_km"
        case speedMax = "speed_max"
        case outsideTempAvg = "outside_temp_avg"
        case insideTempAvg = "inside_temp_avg"
        case positionsTruncated = "positions_truncated"
    }
}

struct DriveEnvelope: Codable, Sendable {
    let items: [VehicleDrive]
    let nextCursor: Int?

    enum CodingKeys: String, CodingKey {
        case items
        case nextCursor = "next_cursor"
    }
}

struct VehicleCharge: Codable, Identifiable, Sendable {
    let id: Int
    let startDate: String?
    let endDate: String?
    let durationMin: Int?
    let startBatteryLevel: Int?
    let endBatteryLevel: Int?
    let chargeEnergyAdded: Double?
    let chargeEnergyUsed: Double?
    let efficiencyPercent: Double?
    let cost: Double?
    let address: String?
    let maximumChargerPowerKw: Double?
    let chargeType: String?
    let incomplete: Bool

    enum CodingKeys: String, CodingKey {
        case id, cost, address, incomplete
        case startDate = "start_date"
        case endDate = "end_date"
        case durationMin = "duration_min"
        case startBatteryLevel = "start_battery_level"
        case endBatteryLevel = "end_battery_level"
        case chargeEnergyAdded = "charge_energy_added"
        case chargeEnergyUsed = "charge_energy_used"
        case efficiencyPercent = "efficiency_percent"
        case maximumChargerPowerKw = "maximum_charger_power_kw"
        case chargeType = "charge_type"
    }
}

struct ChargeEnvelope: Codable, Sendable {
    let items: [VehicleCharge]
    let nextCursor: Int?

    enum CodingKeys: String, CodingKey {
        case items
        case nextCursor = "next_cursor"
    }
}

struct BatteryHealth: Codable, Sendable {
    let status: String
    let method: String?
    let sampleCount: Int
    let dateFrom: String?
    let dateTo: String?
    let derivedEfficiencyWhPerKm: Double?
    let estimatedCapacityKwh: Double?
    let baselineCapacityKwh: Double?
    let baselineSource: String?
    let estimatedDegradationPercent: Double?
    let label: String?
    let reason: String?

    enum CodingKeys: String, CodingKey {
        case status, method, label, reason
        case sampleCount = "sample_count"
        case dateFrom = "date_from"
        case dateTo = "date_to"
        case derivedEfficiencyWhPerKm = "derived_efficiency_wh_per_km"
        case estimatedCapacityKwh = "estimated_capacity_kwh"
        case baselineCapacityKwh = "baseline_capacity_kwh"
        case baselineSource = "baseline_source"
        case estimatedDegradationPercent = "estimated_degradation_percent"
    }
}

struct SavedDestination: Codable, Identifiable, Sendable {
    let id: String
    let vehicleID: String
    let name: String
    let address: String
    let latitude: Double
    let longitude: Double
    let icon: String
    let climateEnabled: Bool
    let temperatureC: Double?
    let seatClimateMode: SeatClimateMode?

    enum CodingKeys: String, CodingKey {
        case id, name, address, latitude, longitude, icon
        case vehicleID = "vehicle_id"
        case climateEnabled = "climate_enabled"
        case temperatureC = "temperature_c"
        case seatClimateMode = "seat_climate_mode"
    }
}

struct DestinationEnvelope: Codable, Sendable { let items: [SavedDestination] }

struct DestinationDraft: Codable, Sendable {
    var name: String
    var address: String
    var latitude: Double
    var longitude: Double
    var icon: String = "pin"
    var climateEnabled: Bool = true
    var temperatureC: Double?
    var seatClimateMode: SeatClimateMode?

    enum CodingKeys: String, CodingKey {
        case name, address, latitude, longitude, icon
        case climateEnabled = "climate_enabled"
        case temperatureC = "temperature_c"
        case seatClimateMode = "seat_climate_mode"
    }

    init(destination: SavedDestination? = nil) {
        name = destination?.name ?? ""
        address = destination?.address ?? ""
        latitude = destination?.latitude ?? -27.4698
        longitude = destination?.longitude ?? 153.0251
        icon = destination?.icon ?? "pin"
        climateEnabled = destination?.climateEnabled ?? true
        temperatureC = destination?.temperatureC
        seatClimateMode = destination?.seatClimateMode
    }
}

enum SeatClimateMode: String, Codable, CaseIterable, Identifiable, Sendable {
    case off
    case heatLow = "heat_low"
    case heatMedium = "heat_medium"
    case heatHigh = "heat_high"
    case coolLow = "cool_low"
    case coolMedium = "cool_medium"
    case coolHigh = "cool_high"

    var id: String { rawValue }

    var label: String {
        switch self {
        case .off: "Off"
        case .heatLow: "Heat · Low"
        case .heatMedium: "Heat · Medium"
        case .heatHigh: "Heat · High"
        case .coolLow: "Cool · Low"
        case .coolMedium: "Cool · Medium"
        case .coolHigh: "Cool · High"
        }
    }
}

struct MaintenanceAttachment: Codable, Identifiable, Sendable {
    let id: String
    let filename: String
    let contentType: String
    let sizeBytes: Int

    enum CodingKeys: String, CodingKey {
        case id, filename
        case contentType = "content_type"
        case sizeBytes = "size_bytes"
    }
}

struct MaintenanceRecord: Codable, Identifiable, Sendable {
    let id: String
    let vehicleID: String
    let category: String
    let title: String
    let completedDate: String?
    let odometerKm: Double?
    let costAmount: Double?
    let costCurrency: String
    let workshop: String
    let notes: String
    let nextDueDate: String?
    let nextDueOdometerKm: Double?
    let warningDays: Int
    let warningKm: Int
    let dueStatus: String?
    let daysRemaining: Int?
    let kmRemaining: Double?
    let attachments: [MaintenanceAttachment]?

    enum CodingKeys: String, CodingKey {
        case id, category, title, workshop, notes, attachments
        case vehicleID = "vehicle_id"
        case completedDate = "completed_date"
        case odometerKm = "odometer_km"
        case costAmount = "cost_amount"
        case costCurrency = "cost_currency"
        case nextDueDate = "next_due_date"
        case nextDueOdometerKm = "next_due_odometer_km"
        case warningDays = "warning_days"
        case warningKm = "warning_km"
        case dueStatus = "due_status"
        case daysRemaining = "days_remaining"
        case kmRemaining = "km_remaining"
    }
}

struct MaintenanceEnvelope: Codable, Sendable { let items: [MaintenanceRecord] }

struct MaintenanceDraft: Codable, Sendable {
    var category: String = "general"
    var title: String = ""
    var completedDate: String?
    var odometerKm: Double?
    var costAmount: Double?
    var costCurrency: String = "AUD"
    var workshop: String = ""
    var notes: String = ""
    var nextDueDate: String?
    var nextDueOdometerKm: Double?
    var warningDays: Int = 30
    var warningKm: Int = 1_000

    enum CodingKeys: String, CodingKey {
        case category, title, workshop, notes
        case completedDate = "completed_date"
        case odometerKm = "odometer_km"
        case costAmount = "cost_amount"
        case costCurrency = "cost_currency"
        case nextDueDate = "next_due_date"
        case nextDueOdometerKm = "next_due_odometer_km"
        case warningDays = "warning_days"
        case warningKm = "warning_km"
    }

    init(record: MaintenanceRecord? = nil) {
        guard let record else { return }
        category = record.category
        title = record.title
        completedDate = record.completedDate
        odometerKm = record.odometerKm
        costAmount = record.costAmount
        costCurrency = record.costCurrency
        workshop = record.workshop
        notes = record.notes
        nextDueDate = record.nextDueDate
        nextDueOdometerKm = record.nextDueOdometerKm
        warningDays = record.warningDays
        warningKm = record.warningKm
    }
}

struct VehicleActionStep: Codable, Identifiable, Sendable {
    var id: String { step }
    let step: String
    let status: String
    let error: String?
}

struct VehicleAction: Codable, Identifiable, Sendable {
    let id: String
    let vehicleID: String
    let action: String
    let parameters: [String: PilotJSONValue]
    let risk: String
    let confirmationRequired: Bool
    let status: String
    let steps: [VehicleActionStep]
    let expiresAt: String

    enum CodingKeys: String, CodingKey {
        case id, action, parameters, risk, status, steps
        case vehicleID = "vehicle_id"
        case confirmationRequired = "confirmation_required"
        case expiresAt = "expires_at"
    }
}

struct DriveCache: Codable, Sendable {
    let vehicles: [VehicleSummary]
    let selectedVehicleID: String?
    let overview: VehicleOverview?
    let drives: [VehicleDrive]
    let charges: [VehicleCharge]
    let batteryHealth: BatteryHealth?
    let destinations: [SavedDestination]
    let maintenance: [MaintenanceRecord]
    let savedAt: Date

    init(
        vehicles: [VehicleSummary] = [], selectedVehicleID: String? = nil,
        overview: VehicleOverview?, drives: [VehicleDrive], charges: [VehicleCharge],
        batteryHealth: BatteryHealth?, destinations: [SavedDestination],
        maintenance: [MaintenanceRecord], savedAt: Date
    ) {
        self.vehicles = vehicles
        self.selectedVehicleID = selectedVehicleID
        self.overview = overview
        self.drives = drives
        self.charges = charges
        self.batteryHealth = batteryHealth
        self.destinations = destinations
        self.maintenance = maintenance
        self.savedAt = savedAt
    }

    enum CodingKeys: String, CodingKey {
        case vehicles, selectedVehicleID, overview, drives, charges, batteryHealth
        case destinations, maintenance, savedAt
    }

    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        vehicles = try values.decodeIfPresent([VehicleSummary].self, forKey: .vehicles) ?? []
        selectedVehicleID = try values.decodeIfPresent(String.self, forKey: .selectedVehicleID)
        overview = try values.decodeIfPresent(VehicleOverview.self, forKey: .overview)
        drives = try values.decodeIfPresent([VehicleDrive].self, forKey: .drives) ?? []
        charges = try values.decodeIfPresent([VehicleCharge].self, forKey: .charges) ?? []
        batteryHealth = try values.decodeIfPresent(BatteryHealth.self, forKey: .batteryHealth)
        destinations = try values.decodeIfPresent([SavedDestination].self, forKey: .destinations) ?? []
        maintenance = try values.decodeIfPresent([MaintenanceRecord].self, forKey: .maintenance) ?? []
        savedAt = try values.decodeIfPresent(Date.self, forKey: .savedAt) ?? .distantPast
    }
}

enum Formatters {
    static func date(_ value: String?) -> String {
        guard let value else { return "Unknown" }
        let formatter = ISO8601DateFormatter()
        guard let date = formatter.date(from: value) else { return String(value.prefix(10)) }
        return date.formatted(date: .abbreviated, time: .shortened)
    }

    static func duration(minutes: Int?) -> String {
        guard let minutes else { return "—" }
        return Duration.seconds(minutes * 60).formatted(.units(allowed: [.hours, .minutes]))
    }

    static func timeRemaining(hours: Double?) -> String {
        guard let hours, hours.isFinite, hours >= 0 else { return "—" }
        if hours < (1.0 / 120.0) { return "Charged" }
        let minutes = max(1, Int((hours * 60).rounded()))
        return duration(minutes: minutes)
    }

    static func arrivalRemaining(hours: Double?) -> String {
        guard let hours, hours.isFinite, hours >= 0 else { return "—" }
        if hours < (1.0 / 120.0) { return "Arrived" }
        let minutes = max(1, Int((hours * 60).rounded()))
        return duration(minutes: minutes)
    }
}
