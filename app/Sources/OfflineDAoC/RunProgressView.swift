import SwiftUI

struct RunProgressView: View {
    @EnvironmentObject var model: AppModel
    let run: RunState

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(run.title).font(.headline)
            Text(run.step).font(.callout).foregroundStyle(.secondary).lineLimit(2)
            if let download = run.download {
                if let total = download.total, total > 0 {
                    ProgressView(value: Double(min(download.done, total)), total: Double(total)) {
                        Text(download.what)
                    } currentValueLabel: {
                        Text("\(Self.size(download.done)) of \(Self.size(total))")
                    }
                } else {
                    ProgressView {
                        Text(download.what)
                    }
                    Text(Self.size(download.done)).font(.callout).foregroundStyle(.secondary)
                }
                Button("Stop") { model.stop() }
            } else {
                ProgressView().progressViewStyle(.linear)
            }
        }
    }

    static func size(_ bytes: Int64) -> String {
        ByteCountFormatter.string(fromByteCount: bytes, countStyle: .file)
    }
}

struct CheckRow: View {
    let text: String
    let ok: Bool

    init(_ text: String, ok: Bool) {
        self.text = text
        self.ok = ok
    }

    var body: some View {
        Label(text, systemImage: ok ? "checkmark.circle.fill" : "xmark.circle.fill")
            .foregroundStyle(ok ? Color.green : Color.red)
    }
}
