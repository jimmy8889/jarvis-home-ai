import SwiftUI

struct WatchMeetingView: View {
    @ObservedObject var model: WatchMeetingModel
    @ObservedObject var transport: WatchMeetingTransport
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 12) {
                    recordingPanel
                    deliverySummary
                    transientMessage
                    recentCaptures
                }
                .padding(.horizontal, 8)
                .padding(.bottom, 8)
            }
            .navigationTitle("Pilot Meetings")
        }
        .onChange(of: scenePhase) { _, phase in
            if phase == .active {
                model.resumeDelivery()
            }
        }
    }

    private var recordingPanel: some View {
        VStack(spacing: 9) {
            HStack(spacing: 6) {
                Circle()
                    .fill(model.isRecording ? Color.red : statusColor)
                    .frame(width: 8, height: 8)
                Text(model.presentation.label)
                    .font(.caption.weight(.semibold))
                    .lineLimit(1)
                Spacer(minLength: 0)
            }

            if model.isRecording {
                Text(model.elapsedSeconds.formattedMeetingDuration)
                    .font(.system(.title2, design: .rounded, weight: .semibold))
                    .monospacedDigit()

                GeometryReader { proxy in
                    ZStack(alignment: .leading) {
                        Capsule().fill(Color.secondary.opacity(0.22))
                        Capsule()
                            .fill(Color.red)
                            .frame(width: max(4, proxy.size.width * model.meterLevel))
                    }
                }
                .frame(height: 5)
                .accessibilityLabel("Microphone level")
                .accessibilityValue("\(Int(model.meterLevel * 100)) percent")
            } else {
                TextField("Meeting title", text: $model.draftTitle)
                    .multilineTextAlignment(.center)
                    .disabled(model.presentation == .requestingPermission || model.presentation == .finalizing)
            }

            Button {
                if model.isRecording {
                    model.stopRecording()
                } else {
                    model.startRecording()
                }
            } label: {
                Label(
                    model.isRecording ? "Stop" : "Start",
                    systemImage: model.isRecording ? "stop.fill" : "mic.fill"
                )
                .font(.headline)
                .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .tint(model.isRecording ? .red : .blue)
            .disabled(model.presentation == .requestingPermission || model.presentation == .finalizing)
            .accessibilityHint(
                model.isRecording
                    ? "Stops and safely queues this meeting"
                    : "Begins a new local meeting recording"
            )
        }
        .padding(10)
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 16))
    }

    private var deliverySummary: some View {
        HStack(spacing: 8) {
            Image(systemName: transport.isReachable ? "iphone.radiowaves.left.and.right" : "arrow.triangle.2.circlepath")
                .foregroundStyle(transport.isReachable ? .green : .orange)
            VStack(alignment: .leading, spacing: 1) {
                Text(transport.phoneStatusLabel)
                    .font(.caption.weight(.semibold))
                Text(model.pendingCount == 0 ? "All recordings delivered" : "\(model.pendingCount) retained locally")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
            Spacer(minLength: 0)
        }
        .accessibilityElement(children: .combine)
    }

    @ViewBuilder
    private var transientMessage: some View {
        if let message = presentationMessage ?? model.persistenceError ?? transport.lastTransportError {
            VStack(alignment: .leading, spacing: 6) {
                Text(message)
                    .font(.caption2)
                    .foregroundStyle(.orange)
                if presentationMessage != nil {
                    Button("Dismiss") { model.clearTransientStatus() }
                        .font(.caption2)
                        .buttonStyle(.plain)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(8)
            .background(Color.orange.opacity(0.12), in: RoundedRectangle(cornerRadius: 10))
        }
    }

    @ViewBuilder
    private var recentCaptures: some View {
        if !model.mostRecentCaptures.isEmpty {
            VStack(alignment: .leading, spacing: 7) {
                Text("Recent")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                ForEach(model.mostRecentCaptures) { capture in
                    CaptureStatusRow(capture: capture) {
                        model.retry(capture.id)
                    }
                    if capture.id != model.mostRecentCaptures.last?.id {
                        Divider()
                    }
                }
            }
            .padding(9)
            .background(Color.secondary.opacity(0.1), in: RoundedRectangle(cornerRadius: 14))
        }
    }

    private var presentationMessage: String? {
        switch model.presentation {
        case let .interrupted(message), let .failed(message): message
        case .idle, .requestingPermission, .recording, .finalizing: nil
        }
    }

    private var statusColor: Color {
        switch model.presentation {
        case .idle: .green
        case .requestingPermission, .finalizing: .orange
        case .recording: .red
        case .interrupted, .failed: .orange
        }
    }
}

private struct CaptureStatusRow: View {
    let capture: WatchMeetingCapture
    let retry: () -> Void

    var body: some View {
        HStack(alignment: .top, spacing: 7) {
            Image(systemName: iconName)
                .foregroundStyle(iconColor)
                .frame(width: 15)
            VStack(alignment: .leading, spacing: 2) {
                Text(capture.title)
                    .font(.caption.weight(.semibold))
                    .lineLimit(1)
                Text("\(capture.deliveryState.label) · \(capture.durationSeconds.formattedMeetingDuration)")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
                if let error = capture.lastError, capture.deliveryState == .failed {
                    Text(error)
                        .font(.caption2)
                        .foregroundStyle(.orange)
                        .lineLimit(2)
                }
            }
            Spacer(minLength: 0)
            if canManuallyResend {
                Button(action: retry) {
                    Image(systemName: "arrow.clockwise")
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Resend \(capture.title)")
            }
        }
        .accessibilityElement(children: .combine)
    }

    private var iconName: String {
        switch capture.deliveryState {
        case .recording: "record.circle"
        case .queued: "iphone.and.arrow.forward"
        case .transferring: "arrow.up.circle"
        case .durableReceived: "gearshape.2"
        case .coreAccepted: "checkmark.circle.fill"
        case .failed: "exclamationmark.triangle.fill"
        }
    }

    private var iconColor: Color {
        switch capture.deliveryState {
        case .recording: .red
        case .queued, .transferring, .durableReceived: .orange
        case .coreAccepted: .green
        case .failed: .red
        }
    }

    private var canManuallyResend: Bool {
        capture.deliveryState == .durableReceived
            || (capture.deliveryState == .failed && capture.retryable)
    }
}

private extension TimeInterval {
    var formattedMeetingDuration: String {
        let totalSeconds = max(Int(self.rounded(.down)), 0)
        let hours = totalSeconds / 3_600
        let minutes = (totalSeconds % 3_600) / 60
        let seconds = totalSeconds % 60
        if hours > 0 {
            return String(format: "%d:%02d:%02d", hours, minutes, seconds)
        }
        return String(format: "%02d:%02d", minutes, seconds)
    }
}
