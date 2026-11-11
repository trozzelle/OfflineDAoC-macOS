import AppKit

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        let model = AppModel.shared
        if let run = model.running, run.download == nil {
            _ = alert("Let it finish", "“\(run.title)” is changing your install. Quit when it is done.", ["OK"])
            return .terminateCancel
        }
        // A running download is interrupted only once a quit path is chosen: Cancel leaves it going.
        guard model.status?.server.running == true else {
            model.stop()  // a download resumes from its finished parts next time
            return .terminateNow
        }
        switch alert("Stop the server?", "The server keeps running after OfflineDAoC quits unless you stop it.",
                     ["Stop the server", "Leave it running", "Cancel"]) {
        case .alertFirstButtonReturn:
            model.stop()
            Task { @MainActor in
                if let log = await model.stopServer() {
                    let choice = alert("The server did not stop", "daoc could not stop the server. It may still be running.",
                                       ["Quit anyway", "Cancel", "Show log"])
                    if choice == .alertThirdButtonReturn { NSWorkspace.shared.activateFileViewerSelecting([log]) }
                    sender.reply(toApplicationShouldTerminate: choice == .alertFirstButtonReturn)
                } else {
                    sender.reply(toApplicationShouldTerminate: true)
                }
            }
            return .terminateLater
        case .alertSecondButtonReturn:
            model.stop()
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
