import AVFoundation
import CryptoKit
import Foundation

protocol WatchMeetingOutboxStoring: Sendable {
    func audioURL(for capture: WatchMeetingCapture) -> URL
    func load() throws -> [WatchMeetingCapture]
    func save(_ captures: [WatchMeetingCapture]) throws
    func removeAudio(for capture: WatchMeetingCapture) throws
    func protectAudio(for capture: WatchMeetingCapture)
    func finalizedDetails(
        for capture: WatchMeetingCapture
    ) throws -> (duration: TimeInterval, sha256: String, size: Int64)
}

struct WatchMeetingOutboxStore: WatchMeetingOutboxStoring, Sendable {
    enum StoreError: LocalizedError {
        case missingApplicationSupport
        case invalidAudioFile

        var errorDescription: String? {
            switch self {
            case .missingApplicationSupport: "Pilot could not open its local meeting outbox."
            case .invalidAudioFile: "The local meeting recording is empty or unreadable."
            }
        }
    }

    let directoryURL: URL
    private let manifestURL: URL

    init(fileManager: FileManager = .default) throws {
        guard let applicationSupport = fileManager.urls(
            for: .applicationSupportDirectory,
            in: .userDomainMask
        ).first else {
            throw StoreError.missingApplicationSupport
        }

        directoryURL = applicationSupport.appendingPathComponent(
            "PilotMeetingOutbox",
            isDirectory: true
        )
        manifestURL = directoryURL.appendingPathComponent("manifest.json")
        try fileManager.createDirectory(
            at: directoryURL,
            withIntermediateDirectories: true
        )
        try? fileManager.setAttributes(
            [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication],
            ofItemAtPath: directoryURL.path
        )
        var resourceValues = URLResourceValues()
        resourceValues.isExcludedFromBackup = true
        var excludedFromBackupURL = directoryURL
        try? excludedFromBackupURL.setResourceValues(resourceValues)
    }

    func audioURL(for capture: WatchMeetingCapture) -> URL {
        directoryURL.appendingPathComponent(capture.originalFilename)
    }

    func load() throws -> [WatchMeetingCapture] {
        guard FileManager.default.fileExists(atPath: manifestURL.path) else {
            return []
        }
        let data = try Data(contentsOf: manifestURL)
        let captures = try JSONDecoder().decode([WatchMeetingCapture].self, from: data)
        // A crash after persisting a Core-accepted tombstone can leave an
        // unnecessary audio file. Retry that privacy-sensitive cleanup at
        // every launch without weakening the accepted state.
        for capture in captures where capture.deliveryState == .coreAccepted {
            try? removeAudio(for: capture)
        }
        return captures
    }

    func save(_ captures: [WatchMeetingCapture]) throws {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        let data = try encoder.encode(captures)
        try data.write(
            to: manifestURL,
            options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication]
        )
    }

    func removeAudio(for capture: WatchMeetingCapture) throws {
        let url = audioURL(for: capture)
        if FileManager.default.fileExists(atPath: url.path) {
            try FileManager.default.removeItem(at: url)
        }
    }

    func protectAudio(for capture: WatchMeetingCapture) {
        try? FileManager.default.setAttributes(
            [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication],
            ofItemAtPath: audioURL(for: capture).path
        )
    }

    func finalizedDetails(for capture: WatchMeetingCapture) throws -> (duration: TimeInterval, sha256: String, size: Int64) {
        let url = audioURL(for: capture)
        let attributes = try FileManager.default.attributesOfItem(atPath: url.path)
        let size = (attributes[.size] as? NSNumber)?.int64Value ?? 0
        guard size > 0 else { throw StoreError.invalidAudioFile }

        let duration = (try? AVAudioPlayer(contentsOf: url).duration) ?? capture.durationSeconds
        return (duration, try sha256(for: url), size)
    }

    private func sha256(for url: URL) throws -> String {
        let file = try FileHandle(forReadingFrom: url)
        defer { try? file.close() }

        var digest = SHA256()
        while let chunk = try file.read(upToCount: 64 * 1024), !chunk.isEmpty {
            digest.update(data: chunk)
        }
        return digest.finalize().map { String(format: "%02x", $0) }.joined()
    }
}
