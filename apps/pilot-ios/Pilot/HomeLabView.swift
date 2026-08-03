import SwiftUI

struct HomeLabView: View {
    @Environment(PilotModel.self) private var model
    @State private var selectedNode: ProxmoxNode?
    @State private var selectedWorkload: ProxmoxWorkload?
    @State private var pendingMigration: ProxmoxWorkload?
    @State private var pendingTargetNode = ""

    private let columns = [GridItem(.adaptive(minimum: 260), spacing: 14)]

    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 20) {
                header
                summary
                if let message = model.homelabError {
                    errorCard(message)
                }
                proxmoxSection
                acceleratorSection
                trueNASSection
                workloadSection
            }
            .padding()
        }
        .background(PilotTheme.background.ignoresSafeArea())
        .navigationTitle("Home Lab")
        .refreshable { await model.refreshHomeLab(force: true) }
        .task { await model.refreshHomeLab(silent: true) }
        .sheet(item: $selectedNode) { node in nodeDetail(node) }
        .sheet(item: $selectedWorkload) { workload in workloadDetail(workload) }
        .alert("Migrate workload?", isPresented: Binding(
            get: { pendingMigration != nil },
            set: { if !$0 { pendingMigration = nil } }
        )) {
            Button("Cancel", role: .cancel) { pendingMigration = nil }
            Button("Migrate", role: .destructive) {
                guard let workload = pendingMigration else { return }
                let target = pendingTargetNode
                pendingMigration = nil
                Task {
                    do { try await model.migrate(workload, to: target) }
                    catch { model.homelabError = error.localizedDescription }
                }
            }
        } message: {
            Text("Pilot will validate storage and locks, then move this workload to \(pendingTargetNode). Running services may briefly pause.")
        }
    }

    private var header: some View {
        HStack(alignment: .top, spacing: 14) {
            ZStack {
                RoundedRectangle(cornerRadius: 18)
                    .fill(PilotTheme.cyan.opacity(0.14))
                Image(systemName: "server.rack")
                    .font(.system(size: 30, weight: .semibold))
                    .foregroundStyle(PilotTheme.cyan)
            }
            .frame(width: 64, height: 64)
            VStack(alignment: .leading, spacing: 5) {
                Text("James Home Lab")
                    .font(.largeTitle.bold())
                Text("Compute, storage and accelerator health")
                    .foregroundStyle(.secondary)
                HStack(spacing: 7) {
                    Circle()
                        .fill(statusColor)
                        .frame(width: 8, height: 8)
                    Text(model.homelab.stale ? "Stale snapshot" : model.homelab.status.capitalized)
                        .font(.caption.weight(.semibold))
                    if !model.homelab.generatedAt.isEmpty {
                        Text("· \(relative(model.homelab.generatedAt))")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            }
            Spacer()
            if model.isLoadingHomeLab { ProgressView().tint(PilotTheme.cyan) }
        }
        .padding(18)
        .background(PilotTheme.card, in: RoundedRectangle(cornerRadius: 24))
        .overlay(RoundedRectangle(cornerRadius: 24).stroke(PilotTheme.border))
    }

    private var summary: some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 130), spacing: 10)], spacing: 10) {
            summaryTile(
                "Nodes",
                "\(model.homelab.summary.onlineNodeCount)/\(model.homelab.summary.nodeCount)",
                "server.rack",
                model.homelab.summary.onlineNodeCount == model.homelab.summary.nodeCount
                    ? PilotTheme.mint : PilotTheme.amber
            )
            summaryTile(
                "Workloads",
                "\(model.homelab.summary.runningWorkloadCount)/\(model.homelab.summary.workloadCount)",
                "square.3.layers.3d",
                PilotTheme.blue
            )
            summaryTile(
                "Drives",
                "\(model.homelab.summary.diskCount)",
                "internaldrive.fill",
                PilotTheme.violet
            )
            summaryTile(
                "Hottest",
                temperature(model.homelab.summary.hottestTemperatureC),
                "thermometer.medium",
                thermalColor(model.homelab.summary.hottestTemperatureC)
            )
        }
    }

    @ViewBuilder
    private var proxmoxSection: some View {
        let proxmox = model.homelab.providers.proxmox
        sectionHeader(
            proxmox.cluster?.name ?? "Proxmox",
            detail: proxmox.configured ? proxmox.status.capitalized : "Not configured",
            symbol: "rectangle.3.group.fill"
        )
        if proxmox.nodes.isEmpty {
            emptyProvider("No Proxmox node data", proxmox.error)
        } else {
            LazyVGrid(columns: columns, spacing: 14) {
                ForEach(proxmox.nodes) { node in
                    Button { selectedNode = node } label: { nodeCard(node) }
                        .buttonStyle(.plain)
                }
            }
        }
    }

    @ViewBuilder
    private var acceleratorSection: some View {
        let accelerators = model.homelab.agents.flatMap { agent in
            agent.gpus.map { Accelerator(agent: agent, gpu: $0) }
        }
        if !accelerators.isEmpty {
            sectionHeader("AI Accelerators", detail: "Live NVIDIA telemetry", symbol: "cpu.fill")
            LazyVGrid(columns: columns, spacing: 14) {
                ForEach(accelerators) { accelerator in
                    let agent = accelerator.agent
                    let gpu = accelerator.gpu
                    VStack(alignment: .leading, spacing: 13) {
                        HStack {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(gpu.name).font(.headline)
                                Text(agent.hostname)
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                            Spacer()
                            statusDot(agent.stale ? .orange : PilotTheme.mint)
                        }
                        metricBar("GPU", gpu.utilizationRatio, PilotTheme.violet)
                        metricBar(
                            "VRAM",
                            ratio(gpu.memoryUsedBytes, gpu.memoryTotalBytes),
                            PilotTheme.blue
                        )
                        HStack {
                            Label(temperature(gpu.temperatureC), systemImage: "thermometer.medium")
                            Spacer()
                            if let watts = gpu.powerWatts {
                                Label("\(Int(watts)) W", systemImage: "bolt.fill")
                            }
                        }
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.secondary)
                    }
                    .labCard()
                }
            }
        }
    }

    @ViewBuilder
    private var trueNASSection: some View {
        let nas = model.homelab.providers.truenas
        sectionHeader(
            nas.system?.hostname ?? "TrueNAS",
            detail: nas.configured ? nas.status.capitalized : "API key required",
            symbol: "externaldrive.connected.to.line.below.fill"
        )
        if !nas.alerts.isEmpty {
            VStack(alignment: .leading, spacing: 8) {
                ForEach(nas.alerts) { alert in
                    Label(alert.title, systemImage: "exclamationmark.triangle.fill")
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(PilotTheme.amber)
                }
            }
            .labCard()
        }
        if nas.pools.isEmpty && nas.disks.isEmpty {
            emptyProvider("No TrueNAS storage data", nas.error)
        } else {
            if !nas.pools.isEmpty {
                LazyVGrid(columns: columns, spacing: 14) {
                    ForEach(nas.pools) { pool in poolCard(pool) }
                }
            }
            if !nas.disks.isEmpty {
                Text("Drives").font(.title2.bold()).padding(.top, 4)
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 190), spacing: 12)], spacing: 12) {
                    ForEach(nas.disks) { disk in diskCard(disk) }
                }
            }
        }
    }

    @ViewBuilder
    private var workloadSection: some View {
        let workloads = model.homelab.providers.proxmox.workloads
        if !workloads.isEmpty {
            sectionHeader("Virtual Estate", detail: "VMs and containers", symbol: "cube.transparent.fill")
            ForEach(Dictionary(grouping: workloads, by: \.node).keys.sorted(), id: \.self) { node in
                VStack(alignment: .leading, spacing: 0) {
                    Text(node).font(.headline).padding(.top, 14).padding(.bottom, 6)
                    ForEach(workloads.filter { $0.node == node }) { workload in
                      Button { selectedWorkload = workload } label: {
                       HStack(spacing: 12) {
                        statusDot(workload.status == "running" ? PilotTheme.mint : .secondary)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(workload.name).font(.subheadline.weight(.semibold))
                            Text("\(workload.kind.uppercased()) · \(workload.node)")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                        Spacer()
                        VStack(alignment: .trailing, spacing: 2) {
                            Text(percent(workload.cpuRatio)).font(.caption.weight(.semibold))
                            Text(bytes(workload.memoryUsedBytes))
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                        }
                       }
                       .padding(.vertical, 11)
                      }
                      .buttonStyle(.plain)
                      Divider().opacity(0.35)
                    }
                }
            }
            .padding(.horizontal, 16)
            .background(PilotTheme.card, in: RoundedRectangle(cornerRadius: 20))
            .overlay(RoundedRectangle(cornerRadius: 20).stroke(PilotTheme.border))
        }
    }

    private func nodeDetail(_ node: ProxmoxNode) -> some View {
        let agent = model.homelab.agents.first { $0.hostname == node.name }
        return NavigationStack {
            List {
                Section("Capacity") {
                    LabeledContent("CPU threads", value: "\(node.cpuThreads ?? 0)")
                    LabeledContent("CPU usage", value: percent(node.cpuRatio))
                    LabeledContent("Memory", value: "\(bytes(node.memoryUsedBytes)) of \(bytes(node.memoryTotalBytes))")
                    LabeledContent("Root", value: "\(bytes(node.diskUsedBytes)) of \(bytes(node.diskTotalBytes))")
                    LabeledContent("Uptime", value: uptime(node.uptimeSeconds))
                }
                Section("Thermals") {
                    if let readings = agent?.temperatures, !readings.isEmpty {
                        ForEach(readings) { reading in
                            LabeledContent(reading.label, value: temperature(reading.temperatureC))
                        }
                    } else { Text("Host temperature agent has not reported yet.") }
                }
                Section("Workloads") {
                    ForEach(model.homelab.providers.proxmox.workloads.filter { $0.node == node.name }) {
                        Text($0.name)
                    }
                }
            }
            .navigationTitle(node.name)
        }
    }

    private func workloadDetail(_ workload: ProxmoxWorkload) -> some View {
        NavigationStack {
            List {
                Section("Runtime") {
                    LabeledContent("Type", value: workload.kind.uppercased())
                    LabeledContent("VM ID", value: workload.vmid.map(String.init) ?? "—")
                    LabeledContent("Node", value: workload.node)
                    LabeledContent("Status", value: workload.status.capitalized)
                    LabeledContent("CPU", value: percent(workload.cpuRatio))
                    LabeledContent("Memory", value: "\(bytes(workload.memoryUsedBytes)) of \(bytes(workload.memoryTotalBytes))")
                    LabeledContent("Uptime", value: uptime(workload.uptimeSeconds))
                }
                Section("Lifetime I/O") {
                    LabeledContent("Disk read", value: bytes(workload.diskReadBytes))
                    LabeledContent("Disk written", value: bytes(workload.diskWriteBytes))
                    LabeledContent("Network in", value: bytes(workload.networkInBytes))
                    LabeledContent("Network out", value: bytes(workload.networkOutBytes))
                }
                if model.clientManifest?.features["homelab_control"] == true {
                    Section("Migrate") {
                        ForEach(model.homelab.providers.proxmox.nodes.filter { $0.name != workload.node && $0.status == "online" }) { node in
                            Button("Move to \(node.name)…") {
                                selectedWorkload = nil
                                pendingTargetNode = node.name
                                pendingMigration = workload
                            }
                        }
                        Text("Pilot checks locks and node-local storage before issuing a one-use migration confirmation.")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                }
            }
            .navigationTitle(workload.name)
        }
    }

    private func nodeCard(_ node: ProxmoxNode) -> some View {
        let agent = model.homelab.agents.first { $0.hostname == node.name }
        return VStack(alignment: .leading, spacing: 13) {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text(node.name).font(.title3.bold())
                    Text("\(node.cpuThreads ?? 0) threads · up \(uptime(node.uptimeSeconds))")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                statusDot(node.status == "online" ? PilotTheme.mint : .red)
            }
            metricBar("CPU", node.cpuRatio, PilotTheme.cyan)
            metricBar("Memory", node.memoryRatio, PilotTheme.violet)
            metricBar("Root", node.diskRatio, PilotTheme.blue)
            if let hottest = agent?.temperatures.map(\.temperatureC).max() {
                Label(temperature(hottest), systemImage: "thermometer.medium")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(thermalColor(hottest))
            }
        }
        .labCard()
    }

    private func poolCard(_ pool: TrueNASPool) -> some View {
        VStack(alignment: .leading, spacing: 13) {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text(pool.name).font(.title3.bold())
                    Text(pool.status).font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                statusDot(pool.healthy == false ? .red : PilotTheme.mint)
            }
            metricBar("Used", pool.usageRatio, PilotTheme.blue)
            HStack {
                Text(bytes(pool.allocatedBytes))
                Spacer()
                Text("of \(bytes(pool.sizeBytes))")
            }
            .font(.caption)
            .foregroundStyle(.secondary)
        }
        .labCard()
    }

    private func diskCard(_ disk: TrueNASDisk) -> some View {
        VStack(alignment: .leading, spacing: 9) {
            HStack {
                Image(systemName: disk.type?.lowercased().contains("ssd") == true ? "memorychip.fill" : "internaldrive.fill")
                    .foregroundStyle(PilotTheme.violet)
                Text(disk.name).font(.headline)
                Spacer()
                Text(temperature(disk.temperatureC))
                    .font(.headline.monospacedDigit())
                    .foregroundStyle(thermalColor(disk.temperatureC))
            }
            Text(disk.model).font(.caption).lineLimit(2)
            HStack {
                Text(bytes(disk.sizeBytes))
                Spacer()
                Label(
                    disk.smartEnabled == false ? "SMART off" : "SMART on",
                    systemImage: disk.smartEnabled == false ? "exclamationmark.triangle" : "checkmark.shield.fill"
                )
            }
            .font(.caption2)
            .foregroundStyle(.secondary)
        }
        .labCard()
    }

    private func summaryTile(_ title: String, _ value: String, _ symbol: String, _ color: Color) -> some View {
        VStack(alignment: .leading, spacing: 9) {
            Image(systemName: symbol).foregroundStyle(color)
            Text(value).font(.title2.bold().monospacedDigit())
            Text(title).font(.caption).foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .labCard()
    }

    private func sectionHeader(_ title: String, detail: String, symbol: String) -> some View {
        HStack {
            Label(title, systemImage: symbol).font(.title2.bold())
            Spacer()
            Text(detail).font(.caption.weight(.semibold)).foregroundStyle(.secondary)
        }
    }

    private func metricBar(_ label: String, _ value: Double?, _ color: Color) -> some View {
        VStack(spacing: 5) {
            HStack {
                Text(label)
                Spacer()
                Text(percent(value)).monospacedDigit()
            }
            .font(.caption.weight(.semibold))
            ProgressView(value: value ?? 0).tint(color)
        }
    }

    private func emptyProvider(_ title: String, _ error: String?) -> some View {
        ContentUnavailableView(
            title,
            systemImage: "server.rack",
            description: Text(error ?? "Pilot Core is waiting for this read-only provider.")
        )
        .frame(maxWidth: .infinity)
        .padding(.vertical, 28)
        .background(PilotTheme.card, in: RoundedRectangle(cornerRadius: 20))
    }

    private func errorCard(_ message: String) -> some View {
        Label(message, systemImage: "exclamationmark.triangle.fill")
            .font(.subheadline)
            .foregroundStyle(PilotTheme.amber)
            .frame(maxWidth: .infinity, alignment: .leading)
            .labCard()
    }

    private func statusDot(_ color: Color) -> some View {
        Circle().fill(color).frame(width: 10, height: 10)
    }

    private var statusColor: Color {
        switch model.homelab.status {
        case "healthy": PilotTheme.mint
        case "degraded", "stale": PilotTheme.amber
        default: .secondary
        }
    }

    private func ratio(_ used: Int64?, _ total: Int64?) -> Double? {
        guard let used, let total, total > 0 else { return nil }
        return min(max(Double(used) / Double(total), 0), 1)
    }

    private func percent(_ value: Double?) -> String {
        guard let value else { return "—" }
        return "\(Int((value * 100).rounded()))%"
    }

    private func bytes(_ value: Int64?) -> String {
        guard let value else { return "—" }
        return ByteCountFormatter.string(fromByteCount: value, countStyle: .binary)
    }

    private func temperature(_ value: Double?) -> String {
        guard let value else { return "—" }
        return "\(Int(value.rounded()))°C"
    }

    private func thermalColor(_ value: Double?) -> Color {
        guard let value else { return .secondary }
        if value >= 75 { return .red }
        if value >= 60 { return PilotTheme.amber }
        return PilotTheme.mint
    }

    private func uptime(_ value: Int?) -> String {
        guard let value else { return "—" }
        let days = value / 86_400
        let hours = (value % 86_400) / 3_600
        return days > 0 ? "\(days)d \(hours)h" : "\(hours)h"
    }

    private func relative(_ value: String) -> String {
        guard let date = ISO8601DateFormatter().date(from: value) else { return "Updated recently" }
        return date.formatted(.relative(presentation: .named))
    }
}

private struct Accelerator: Identifiable {
    let agent: HomeLabAgent
    let gpu: HomeLabGPU

    var id: String { "\(agent.deviceID)-\(gpu.id)" }
}

private extension View {
    func labCard() -> some View {
        padding(16)
            .background(PilotTheme.card, in: RoundedRectangle(cornerRadius: 20))
            .overlay(RoundedRectangle(cornerRadius: 20).stroke(PilotTheme.border))
    }
}
