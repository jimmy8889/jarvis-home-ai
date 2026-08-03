import SwiftUI
import UniformTypeIdentifiers
import QuickLook

struct CareView: View {
    @Bindable var model: DriveModel
    @State private var editingRecord: MaintenanceRecord?
    @State private var showingNewRecord = false
    @State private var receiptRecord: MaintenanceRecord?
    @State private var showingImporter = false
    @State private var previewDocument: PreviewDocument?

    var body: some View {
        NavigationStack {
            Group {
                if model.maintenance.isEmpty {
                    EmptyState(
                        symbol: "wrench.and.screwdriver",
                        title: "No care records",
                        detail: "Track services, costs, receipts, and the next due date or odometer."
                    )
                } else {
                    List {
                        if !dueItems.isEmpty {
                            Section("Due and upcoming") {
                                ForEach(dueItems) { record in
                                    MaintenanceRow(record: record)
                                        .contentShape(Rectangle())
                                        .onTapGesture { editingRecord = record }
                                }
                            }
                        }
                        Section("Service history") {
                            ForEach(model.maintenance) { record in
                                MaintenanceRow(record: record)
                                    .contentShape(Rectangle())
                                    .onTapGesture { editingRecord = record }
                                    .contextMenu { receiptMenu(record) }
                                    .swipeActions(edge: .trailing) {
                                        Button(role: .destructive) {
                                            Task { await model.deleteMaintenance(record) }
                                        } label: { Label("Delete", systemImage: "trash") }
                                    }
                                    .swipeActions(edge: .leading) {
                                        Button {
                                            receiptRecord = record
                                            showingImporter = true
                                        } label: { Label("Receipt", systemImage: "paperclip") }
                                        .tint(DriveTheme.accent)
                                    }
                            }
                        }
                    }
                    .listStyle(.insetGrouped)
                }
            }
            .navigationTitle("Care")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button { showingNewRecord = true } label: {
                        Label("Add care record", systemImage: "plus")
                    }
                    .disabled(!model.canMaintain)
                }
            }
            .refreshable { await model.refreshAll() }
            .sheet(isPresented: $showingNewRecord) {
                MaintenanceEditor(model: model)
            }
            .sheet(item: $editingRecord) { record in
                MaintenanceEditor(model: model, record: record)
            }
            .fileImporter(
                isPresented: $showingImporter,
                allowedContentTypes: [.jpeg, .heic, .pdf],
                allowsMultipleSelection: false
            ) { result in
                guard let record = receiptRecord else { return }
                Task { await importReceipt(result, record: record) }
            }
            .sheet(item: $previewDocument) { document in
                QuickLookPreview(url: document.url)
            }
        }
    }

    private var dueItems: [MaintenanceRecord] {
        model.maintenance.filter { ["overdue", "due_soon"].contains($0.dueStatus ?? "") }
    }

    private func importReceipt(
        _ result: Result<[URL], any Error>,
        record: MaintenanceRecord
    ) async {
        do {
            guard let url = try result.get().first else { return }
            let scoped = url.startAccessingSecurityScopedResource()
            defer { if scoped { url.stopAccessingSecurityScopedResource() } }
            let data = try Data(contentsOf: url, options: .mappedIfSafe)
            let contentType = try url.resourceValues(forKeys: [.contentTypeKey])
                .contentType?.preferredMIMEType ?? mimeType(for: url)
            _ = await model.uploadReceipt(
                data: data,
                filename: url.lastPathComponent,
                contentType: contentType,
                record: record
            )
        } catch {
            model.errorMessage = error.localizedDescription
        }
    }

    private func mimeType(for url: URL) -> String {
        switch url.pathExtension.lowercased() {
        case "pdf": "application/pdf"
        case "heic": "image/heic"
        default: "image/jpeg"
        }
    }

    @ViewBuilder
    private func receiptMenu(_ record: MaintenanceRecord) -> some View {
        Button {
            receiptRecord = record
            showingImporter = true
        } label: { Label("Attach receipt", systemImage: "paperclip") }
        ForEach(record.attachments ?? []) { attachment in
            Button {
                Task {
                    if let url = await model.downloadReceipt(attachment, record: record) {
                        previewDocument = PreviewDocument(url: url)
                    }
                }
            } label: {
                Label("Open \(attachment.filename)", systemImage: "doc")
            }
        }
    }
}

private struct PreviewDocument: Identifiable {
    let id = UUID()
    let url: URL
}

private struct QuickLookPreview: UIViewControllerRepresentable {
    let url: URL

    func makeCoordinator() -> Coordinator { Coordinator(url: url) }

    func makeUIViewController(context: Context) -> QLPreviewController {
        let controller = QLPreviewController()
        controller.dataSource = context.coordinator
        return controller
    }

    func updateUIViewController(_ controller: QLPreviewController, context: Context) {
        context.coordinator.url = url
        controller.reloadData()
    }

    final class Coordinator: NSObject, QLPreviewControllerDataSource {
        var url: URL

        init(url: URL) { self.url = url }

        func numberOfPreviewItems(in controller: QLPreviewController) -> Int { 1 }

        func previewController(
            _ controller: QLPreviewController,
            previewItemAt index: Int
        ) -> any QLPreviewItem {
            url as NSURL
        }
    }
}

private struct MaintenanceRow: View {
    let record: MaintenanceRecord

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text(record.title).font(.headline)
                    Text(record.category.capitalized)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                if let dueStatus = record.dueStatus {
                    StatusPill(text: dueStatus, tint: dueStatus == "overdue" ? .red : dueStatus == "due_soon" ? .orange : DriveTheme.accent)
                }
            }
            HStack(spacing: 14) {
                Label(Formatters.date(record.completedDate), systemImage: "calendar")
                if let odometer = record.odometerKm {
                    Label("\(Int(odometer)) km", systemImage: "gauge.with.dots.needle.33percent")
                }
                if let cost = record.costAmount {
                    Text(cost, format: .currency(code: record.costCurrency))
                }
            }
            .font(.caption)
            .foregroundStyle(.secondary)
            if let due = record.nextDueDate {
                Text("Next due \(Formatters.date(due))")
                    .font(.caption)
            }
            if let km = record.nextDueOdometerKm {
                Text("Next due at \(Int(km)) km")
                    .font(.caption)
            }
            if let attachments = record.attachments, !attachments.isEmpty {
                Label("\(attachments.count) receipt\(attachments.count == 1 ? "" : "s")", systemImage: "paperclip")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.vertical, 4)
        .accessibilityElement(children: .combine)
    }
}

struct MaintenanceEditor: View {
    @Bindable var model: DriveModel
    let record: MaintenanceRecord?
    @Environment(\.dismiss) private var dismiss
    @State private var draft: MaintenanceDraft
    @State private var isSaving = false

    init(model: DriveModel, record: MaintenanceRecord? = nil) {
        self.model = model
        self.record = record
        _draft = State(initialValue: MaintenanceDraft(record: record))
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("Service") {
                    TextField("Title", text: $draft.title)
                    Picker("Category", selection: $draft.category) {
                        ForEach(["general", "tyres", "brakes", "inspection", "air_filter", "wipers", "registration", "insurance"], id: \.self) {
                            Text($0.replacingOccurrences(of: "_", with: " ").capitalized).tag($0)
                        }
                    }
                    TextField("Completed date (YYYY-MM-DD)", text: optionalText($draft.completedDate))
                        .textContentType(.dateTime)
                    TextField("Odometer km", value: $draft.odometerKm, format: .number)
                        .keyboardType(.decimalPad)
                    TextField("Workshop", text: $draft.workshop)
                    TextField("Notes", text: $draft.notes, axis: .vertical)
                        .lineLimit(3...8)
                }
                Section("Cost") {
                    TextField("Amount", value: $draft.costAmount, format: .number)
                        .keyboardType(.decimalPad)
                    TextField("Currency", text: $draft.costCurrency)
                        .textInputAutocapitalization(.characters)
                }
                Section("Next due") {
                    TextField("Due date (YYYY-MM-DD)", text: optionalText($draft.nextDueDate))
                        .textContentType(.dateTime)
                    TextField("Due odometer km", value: $draft.nextDueOdometerKm, format: .number)
                        .keyboardType(.decimalPad)
                    Stepper("Warn \(draft.warningDays) days ahead", value: $draft.warningDays, in: 0...3_650)
                    Stepper("Warn \(draft.warningKm) km ahead", value: $draft.warningKm, in: 0...100_000, step: 100)
                }
                Section {
                    Text("Care reminders stay inside Pilot Drive. No push notification or cloud service is used.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
            }
            .navigationTitle(record == nil ? "New care record" : "Edit care record")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(isSaving ? "Saving…" : "Save") {
                        Task {
                            isSaving = true
                            draft.costCurrency = draft.costCurrency.uppercased()
                            let saved = await model.saveMaintenance(draft, id: record?.id)
                            isSaving = false
                            if saved { dismiss() }
                        }
                    }
                    .disabled(draft.title.trimmingCharacters(in: .whitespaces).isEmpty || draft.costCurrency.count != 3 || isSaving)
                }
            }
        }
    }

    private func optionalText(_ binding: Binding<String?>) -> Binding<String> {
        Binding(
            get: { binding.wrappedValue ?? "" },
            set: { binding.wrappedValue = $0.isEmpty ? nil : $0 }
        )
    }
}
