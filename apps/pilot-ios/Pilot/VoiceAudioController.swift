import AVFoundation
import Foundation
import Observation

@MainActor
@Observable
final class VoiceAudioController {
    private(set) var level: Double = 0
    private(set) var duration: TimeInterval = 0
    private(set) var isCapturing = false
    private(set) var isPlaying = false

    @ObservationIgnored private var recorder: AVAudioRecorder?
    @ObservationIgnored private var player: AVAudioPlayer?
    @ObservationIgnored private var meteringTask: Task<Void, Never>?
    @ObservationIgnored private var recordingURL: URL?
    @ObservationIgnored private var autoSubmitHandler: (@MainActor @Sendable () -> Void)?
    @ObservationIgnored private var noSpeechHandler: (@MainActor @Sendable () -> Void)?

    func setCaptureHandlers(
        autoSubmit: @escaping @MainActor @Sendable () -> Void,
        noSpeech: @escaping @MainActor @Sendable () -> Void
    ) {
        autoSubmitHandler = autoSubmit
        noSpeechHandler = noSpeech
    }

    func startCapture() async throws {
        cancelCapture()
        guard await AVAudioApplication.requestRecordPermission() else {
            throw VoiceAudioError.microphonePermissionDenied
        }
        // The system permission sheet does not itself inherit Swift task
        // cancellation. Re-check before taking ownership of AVAudioSession so
        // a user who tapped Cancel while the sheet was open cannot start a
        // recorder after the UI has returned to idle.
        try Task.checkCancellation()

        let session = AVAudioSession.sharedInstance()
#if compiler(>=6.2)
        let options: AVAudioSession.CategoryOptions = [
            .defaultToSpeaker,
            .allowBluetoothHFP,
            .duckOthers,
        ]
#else
        let options: AVAudioSession.CategoryOptions = [
            .defaultToSpeaker,
            .allowBluetooth,
            .duckOthers,
        ]
#endif
        try session.setCategory(.playAndRecord, mode: .voiceChat, options: options)
        try session.setPreferredSampleRate(16_000)
        try session.setPreferredIOBufferDuration(0.02)
        try session.setActive(true)

        let url = FileManager.default.temporaryDirectory
            .appending(path: "pilot-voice-\(UUID().uuidString).wav")
        let recorder = try AVAudioRecorder(
            url: url,
            settings: [
                AVFormatIDKey: Int(kAudioFormatLinearPCM),
                AVSampleRateKey: 16_000,
                AVNumberOfChannelsKey: 1,
                AVLinearPCMBitDepthKey: 16,
                AVLinearPCMIsBigEndianKey: false,
                AVLinearPCMIsFloatKey: false,
                AVEncoderAudioQualityKey: AVAudioQuality.high.rawValue,
            ]
        )
        recorder.isMeteringEnabled = true
        guard recorder.prepareToRecord(), recorder.record() else {
            throw VoiceAudioError.couldNotStartRecording
        }

        self.recorder = recorder
        recordingURL = url
        level = 0
        duration = 0
        isCapturing = true
        meteringTask = Task { [weak self, weak recorder] in
            var endOfSpeech = VoiceEndOfSpeechDetector()
            while !Task.isCancelled {
                guard let self, let recorder, recorder.isRecording else { return }
                recorder.updateMeters()
                let decibels = Double(recorder.averagePower(forChannel: 0))
                // -52 dB is effectively silence for the phone microphone. The
                // square curve keeps quiet rooms calm while speech feels alive.
                let linear = min(max((decibels + 52) / 52, 0), 1)
                level = pow(linear, 1.65)
                duration = recorder.currentTime
                switch endOfSpeech.observe(
                    decibels: decibels,
                    duration: recorder.currentTime
                ) {
                case .none:
                    break
                case .submit:
                    autoSubmitHandler?()
                    return
                case .noSpeech:
                    noSpeechHandler?()
                    return
                }
                try? await Task.sleep(for: .milliseconds(50))
            }
        }
    }

    func finishCapture() throws -> Data {
        guard let recorder, let url = recordingURL else {
            throw VoiceAudioError.notRecording
        }
        recorder.stop()
        meteringTask?.cancel()
        meteringTask = nil
        self.recorder = nil
        recordingURL = nil
        isCapturing = false
        level = 0

        defer { try? FileManager.default.removeItem(at: url) }
        let wave = try Data(contentsOf: url, options: .mappedIfSafe)
        let pcm = try VoicePCMExtractor.signed16BitMonoPCM(fromWave: wave)
        guard pcm.count >= 8_000 else { throw VoiceAudioError.recordingTooShort }
        return pcm
    }

    func cancelCapture() {
        recorder?.stop()
        meteringTask?.cancel()
        meteringTask = nil
        recorder = nil
        isCapturing = false
        level = 0
        duration = 0
        if let recordingURL { try? FileManager.default.removeItem(at: recordingURL) }
        recordingURL = nil
    }

    @discardableResult
    func playResponse(_ data: Data) throws -> TimeInterval {
        stopPlayback()
        guard !data.isEmpty else { throw VoiceAudioError.emptyResponseAudio }
        let player = try AVAudioPlayer(data: data)
        player.volume = 1
        player.prepareToPlay()
        guard player.play() else { throw VoiceAudioError.couldNotPlayResponse }
        self.player = player
        isPlaying = true
        return player.duration
    }

    func stopPlayback() {
        player?.stop()
        player = nil
        isPlaying = false
    }

    func finishAudioSession() {
        cancelCapture()
        stopPlayback()
        try? AVAudioSession.sharedInstance().setActive(
            false,
            options: .notifyOthersOnDeactivation
        )
    }
}

enum VoicePCMExtractor {
    static func signed16BitMonoPCM(fromWave data: Data) throws -> Data {
        guard data.count >= 12,
              String(data: data[0..<4], encoding: .ascii) == "RIFF",
              String(data: data[8..<12], encoding: .ascii) == "WAVE"
        else { throw VoiceAudioError.invalidRecordingFormat }

        var offset = 12
        var formatIsValid = false
        var payload: Data?
        while offset + 8 <= data.count {
            let identifier = String(data: data[offset..<(offset + 4)], encoding: .ascii)
            let size = Int(littleEndianUInt32(data, at: offset + 4))
            let start = offset + 8
            guard size >= 0, start + size <= data.count else {
                throw VoiceAudioError.invalidRecordingFormat
            }
            if identifier == "fmt ", size >= 16 {
                let audioFormat = littleEndianUInt16(data, at: start)
                let channels = littleEndianUInt16(data, at: start + 2)
                let sampleRate = littleEndianUInt32(data, at: start + 4)
                let bitsPerSample = littleEndianUInt16(data, at: start + 14)
                formatIsValid = audioFormat == 1
                    && channels == 1
                    && sampleRate == 16_000
                    && bitsPerSample == 16
            } else if identifier == "data" {
                payload = data.subdata(in: start..<(start + size))
            }
            offset = start + size + (size % 2)
        }
        guard formatIsValid, let payload, !payload.isEmpty else {
            throw VoiceAudioError.invalidRecordingFormat
        }
        return payload
    }

    private static func littleEndianUInt16(_ data: Data, at offset: Int) -> UInt16 {
        UInt16(data[offset]) | UInt16(data[offset + 1]) << 8
    }

    private static func littleEndianUInt32(_ data: Data, at offset: Int) -> UInt32 {
        UInt32(data[offset])
            | UInt32(data[offset + 1]) << 8
            | UInt32(data[offset + 2]) << 16
            | UInt32(data[offset + 3]) << 24
    }
}

struct VoiceEndOfSpeechDetector {
    enum Decision: Equatable {
        case none
        case submit
        case noSpeech
    }

    static let speechThresholdDecibels = -34.0
    static let requiredSpeechFrames = 4
    static let minimumRecordingDuration = 0.65
    static let sustainedSilenceDuration = 1.10
    static let maximumRecordingDuration = 45.0

    private var consecutiveSpeechFrames = 0
    private var speechDetected = false
    private var lastSpeechAt: TimeInterval?
    private var completed = false

    mutating func observe(
        decibels: Double,
        duration: TimeInterval
    ) -> Decision {
        guard !completed else { return .none }
        if decibels >= Self.speechThresholdDecibels {
            consecutiveSpeechFrames += 1
            if consecutiveSpeechFrames >= Self.requiredSpeechFrames {
                speechDetected = true
            }
            if speechDetected { lastSpeechAt = duration }
        } else if !speechDetected {
            consecutiveSpeechFrames = max(0, consecutiveSpeechFrames - 1)
        }

        if speechDetected,
           duration >= Self.minimumRecordingDuration,
           let lastSpeechAt,
           duration - lastSpeechAt >= Self.sustainedSilenceDuration {
            completed = true
            return .submit
        }
        if duration >= Self.maximumRecordingDuration {
            completed = true
            return speechDetected ? .submit : .noSpeech
        }
        return .none
    }
}

enum VoiceAudioError: LocalizedError {
    case microphonePermissionDenied
    case couldNotStartRecording
    case notRecording
    case recordingTooShort
    case noSpeechDetected
    case invalidRecordingFormat
    case emptyResponseAudio
    case couldNotPlayResponse

    var errorDescription: String? {
        switch self {
        case .microphonePermissionDenied:
            "Microphone access is off. Enable it for Pilot in Settings."
        case .couldNotStartRecording:
            "Pilot could not start the microphone."
        case .notRecording:
            "Pilot is not currently listening."
        case .recordingTooShort:
            "That was too brief to understand. Hold for a moment and try again."
        case .noSpeechDetected:
            "I didn’t hear a voice. Move a little closer and try again."
        case .invalidRecordingFormat:
            "The microphone returned an unsupported recording format."
        case .emptyResponseAudio:
            "Pilot returned an empty spoken response."
        case .couldNotPlayResponse:
            "Pilot could not play the spoken response."
        }
    }
}
