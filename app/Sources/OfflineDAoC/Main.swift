import AppKit
import SwiftUI

@main
enum Main {
    static func main() {
        if CommandLine.arguments.contains("--self-test") {
            exit(SelfTest.run())
        }
        OfflineDAoCApp.main()
    }
}

struct OfflineDAoCApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate
    @StateObject private var model = AppModel.shared

    var body: some Scene {
        Window("OfflineDAoC", id: "main") {
            RootView().environmentObject(model)
        }
        .commands {
            CommandGroup(after: .appSettings) {
                Button("Install daoc Command…") {
                    Task { await AppModel.shared.run("Install the daoc command", ["self-install"]) }
                }
            }
        }
    }
}
