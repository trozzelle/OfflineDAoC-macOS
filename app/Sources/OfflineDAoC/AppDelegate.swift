import AppKit

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        let model = AppModel.shared
        if let run = model.running {
            guard run.download != nil else {
                _ = alert("Let it finish", "“\(run.title)” is changing your install. Quit when it is done.", ["OK"])
                return .terminateCancel
            }
            model.stop()  // a download resumes from its finished parts next time
        }
        guard model.status?.server.running == true else { return .terminateNow }
        switch alert("Stop the server?", "The server keeps running after OfflineDAoC quits unless you stop it.",
                     ["Stop the server", "Leave it running", "Cancel"]) {
        case .alertFirstButtonReturn:
            Task { @MainActor in
                _ = await model.capture(["server", "stop"])
                sender.reply(toApplicationShouldTerminate: true)
            }
            return .terminateLater
        case .alertSecondButtonReturn:
            return .terminateNow
        default:
            return .terminateCancel
        }
    }

    private func alert(_ title: String, _ text: String, _ buttons: [String]) -> NSApplication.ModalResponse {
        let alert = NSAlert()
        alert.messageText = title
        alert.informativeText = text
        buttons.forEach { alert.addButton(withTitle: $0) }
        return alert.runModal()
    }
}
