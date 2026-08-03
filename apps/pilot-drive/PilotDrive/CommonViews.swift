import SwiftUI

enum DriveTheme {
    static let accent = Color(red: 0.25, green: 0.78, blue: 0.64)
    static let warning = Color.orange
    static let danger = Color.red
}

struct StatusPill: View {
    let text: String
    var tint: Color = DriveTheme.accent

    var body: some View {
        Text(text.replacingOccurrences(of: "_", with: " ").capitalized)
            .font(.caption.weight(.semibold))
            .padding(.horizontal, 10)
            .padding(.vertical, 5)
            .foregroundStyle(tint)
            .background(tint.opacity(0.14), in: Capsule())
    }
}

struct MetricTile: View {
    let title: String
    let value: String
    let symbol: String
    var detail: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            Label(title, systemImage: symbol)
                .font(.caption)
                .foregroundStyle(.secondary)
            Text(value)
                .font(.title3.weight(.semibold))
                .contentTransition(.numericText())
            if let detail {
                Text(detail)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding()
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 18))
        .accessibilityElement(children: .combine)
    }
}

struct EmptyState: View {
    let symbol: String
    let title: String
    let detail: String

    var body: some View {
        ContentUnavailableView(title, systemImage: symbol, description: Text(detail))
    }
}

extension View {
    func pilotCard() -> some View {
        padding()
            .background(.background.secondary, in: RoundedRectangle(cornerRadius: 20))
    }
}
