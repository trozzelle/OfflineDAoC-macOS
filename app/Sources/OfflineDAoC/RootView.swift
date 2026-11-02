import AppKit
import SwiftUI

struct RootView: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        Group {
            switch model.mode {
            case .loading: ProgressView("Reading your install…")
            case .setup: SetupView()
            case .launcher: LauncherView()
            }
        }
        .frame(minWidth: 680, minHeight: 560)
        .sheet(item: $model.pendingAsk) { AskSheet(request: $0).environmentObject(model) }
        .sheet(item: $model.pendingSecret) { SecretSheet(request: $0).environmentObject(model) }
        .alert(item: $model.failure) { failure in
            Alert(title: Text(failure.title), message: Text(failure.message),
                  primaryButton: .default(Text("Show log")) {
                      NSWorkspace.shared.activateFileViewerSelecting([failure.log])
                  },
                  secondaryButton: .cancel(Text("OK")))
        }
        .alert("Updates", isPresented: Binding(get: { model.notice != nil }, set: { if !$0 { model.notice = nil } })) {
            Button("OK") {}
        } message: {
            Text(model.notice ?? "")
        }
        .task { await model.start() }
    }
}
