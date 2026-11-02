import AppKit
import DaocKit
import SwiftUI

struct DownloadState {
    var path: String
    var total: Int64?
    var what: String
    var done: Int64 = 0
}

struct RunState {
    var title: String
    var step = ""
    var download: DownloadState?
}

struct AskRequest: Identifiable {
    let id: Int
    let question: String
    let process: DaocProcess
}

struct SecretRequest: Identifiable {
    let id: Int
    let process: DaocProcess
}

struct Failure: Identifiable {
    let id = UUID()
    let title: String
    let message: String
    let log: URL
}

private struct LatestRelease: Decodable {
    let tagName: String
    let htmlUrl: String
}

/// The app's state, and every daoc command it runs.
@MainActor
final class AppModel: ObservableObject {
    static let shared = AppModel()

    enum Mode { case loading, setup, launcher }

    @Published var mode: Mode = .loading
    @Published var status: StatusSnapshot?
    @Published var running: RunState?
    @Published var pendingAsk: AskRequest?
    @Published var pendingSecret: SecretRequest?
    @Published var failure: Failure?
    @Published var realms: [RealmCount] = []
    @Published var population: Bool?
    @Published var notice: String?
    @Published var appUpdate: URL?

    private(set) var paths = AppPaths.current()
    private var current: DaocProcess?
    private var timers: [Timer] = []

    func start() async {
        guard await capture(["--version"]) != nil else {
            failure = Failure(title: "OfflineDAoC is damaged",
                              message: "Its bundled daoc does not run. Download OfflineDAoC again.", log: paths.logs)
            return
        }
        await refreshStatus()
        mode = status.map(SetupPlan.isComplete) == true ? .launcher : .setup
        timers.append(Timer.scheduledTimer(withTimeInterval: 3, repeats: true) { _ in
            Task { @MainActor in
                let model = AppModel.shared
                guard NSApp.windows.contains(where: { $0.isVisible && !$0.isMiniaturized }) else { return }
                await model.refreshStatus()
                await model.refreshBots()
            }
        })
        timers.append(Timer.scheduledTimer(withTimeInterval: 0.5, repeats: true) { _ in
            Task { @MainActor in AppModel.shared.pollDownload() }
        })
        await checkAppRelease()
    }

    func adopt(_ folder: URL) {
        UserDefaults.standard.set(folder.path, forKey: AppPaths.dataHomeKey)
        paths.dataHome = folder
    }

    // MARK: Commands

    /// Runs a daoc command that changes something, shown as the current task.
    /// login answers a `secret` event without asking (Setup's account page).
    @discardableResult
    func run(_ title: String, _ arguments: [String], login: (account: String, password: String)? = nil) async -> Bool {
        guard current == nil else { return false }
        let log = paths.logFile(for: arguments)
        let process = DaocProcess(DaocInvocation(launcher: paths.launcher, dataHome: paths.dataHome,
                                                 arguments: arguments, logFile: log))
        current = process
        running = RunState(title: title)
        defer {
            current = nil
            running = nil
            pendingAsk = nil
            pendingSecret = nil
        }
        do {
            let result = try await process.run { event in
                Task { @MainActor in AppModel.shared.handle(event, from: process, login: login) }
            }
            await refreshStatus()
            if result.status == 0 { return true }
            if result.status != 130 {
                failure = Failure(title: "\(title) did not finish",
                                  message: result.errorMessage ?? Self.tail(of: log), log: log)
            }
        } catch {
            failure = Failure(title: "\(title) could not start", message: "\(error)", log: log)
        }
        return false
    }

    /// Runs a read-only daoc command quietly; its stdout when it succeeds.
    func capture(_ arguments: [String]) async -> Data? {
        let process = DaocProcess(DaocInvocation(launcher: paths.launcher, dataHome: paths.dataHome,
                                                 arguments: arguments, logFile: URL(fileURLWithPath: "/dev/null")))
        guard let result = try? await process.run(onEvent: { _ in }), result.status == 0 else { return nil }
        return result.stdout
    }

    private func handle(_ event: DaocEvent, from process: DaocProcess, login: (account: String, password: String)?) {
        switch event {
        case .step(let message):
            running?.step = message
        case .download(let path, let bytes, let what):
            running?.download = DownloadState(path: path, total: bytes, what: what)
        case .ask(let id, let question, _):
            pendingAsk = AskRequest(id: id, question: question, process: process)
        case .secret(let id, _):
            if let login {
                process.answer(DaocAnswer.secret(id: id, account: login.account, password: login.password))
            } else {
                pendingSecret = SecretRequest(id: id, process: process)
            }
        case .error, .unknown:
            break
        }
    }

    func answer(_ request: AskRequest, _ yes: Bool) {
        request.process.answer(DaocAnswer.ask(id: request.id, answer: yes))
        pendingAsk = nil
    }

    func answer(_ request: SecretRequest, account: String, password: String) {
        request.process.answer(DaocAnswer.secret(id: request.id, account: account, password: password))
        pendingSecret = nil
    }

    func cancel(_ request: SecretRequest) {
        request.process.interrupt()
        pendingSecret = nil
    }

    func stop() { current?.interrupt() }

    func pollDownload() {
        guard let path = running?.download?.path,
              let size = (try? FileManager.default.attributesOfItem(atPath: path))?[.size] as? NSNumber else { return }
        running?.download?.done = size.int64Value
    }

    func refreshStatus() async {
        guard let data = await capture(["status", "--json"]), let snapshot = try? StatusSnapshot.decode(data) else { return }
        status = snapshot
    }

    func refreshBots() async {
        guard status?.server.running == true else {
            realms = []
            population = nil
            return
        }
        if let data = await capture(["admin", "bots", "list", "--json"]),
           let bots = try? JSONDecoder().decode([Bot].self, from: data) {
            realms = BotRoster.counts(bots)
        }
        if let data = await capture(["admin", "population", "--json"]),
           let value = try? JSONDecoder().decode(Population.self, from: data) {
            population = value.enabled
        }
    }

    // MARK: Actions

    func play() async {
        if status?.server.running != true {
            guard await run("Start the server", ["server", "start", "--detach"]) else { return }
        }
        await run("Start the game", ["client", "start"])
    }

    func createAccount(_ account: String, _ password: String) async -> Bool {
        if status?.server.running != true {
            guard await run("Start the server", ["server", "start", "--detach"]) else { return false }
        }
        // A rerun after a failed Keychain save finds the account already made.
        if await capture(["admin", "accounts", "show", account]) == nil {
            guard await run("Create the account", ["admin", "accounts", "create", account, password]) else { return false }
        }
        return await run("Save the account in your Keychain", ["client", "login"], login: (account, password))
    }

    func createBots(_ realm: Realm, level: Int, count: Int) async {
        await run("Create \(count) level \(level) \(realm.rawValue) bots",
                  ["admin", "bots", "create", "--realm", realm.adminName, "--level", "\(level)", "--count", "\(count)"])
        await refreshBots()
    }

    func setPopulation(_ on: Bool) async {
        await run(on ? "Turn the population on" : "Turn the population off", ["admin", "population", on ? "on" : "off"])
        await refreshBots()
    }

    func checkForClientUpdates() async {
        notice = await capture(["client", "update", "--check"]).map { String(decoding: $0, as: UTF8.self) }
            ?? "Could not check for updates (no network?)."
    }

    func openAdminConsole() {
        let file = paths.logs.appendingPathComponent("admin-console.command")
        let script = "#!/bin/sh\nexport DAOC_DATA=\(Self.shellQuote(paths.dataHome.path))\n"
            + "exec \(Self.shellQuote(paths.launcher.path)) server start\n"
        do {
            try FileManager.default.createDirectory(at: paths.logs, withIntermediateDirectories: true)
            try script.write(to: file, atomically: true, encoding: .utf8)
            try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: file.path)
            NSWorkspace.shared.open(file)
        } catch {
            failure = Failure(title: "Could not open the admin console", message: "\(error)", log: file)
        }
    }

    func showLogs() {
        let folder = FileManager.default.fileExists(atPath: paths.serverLogs.path) ? paths.serverLogs : paths.logs
        NSWorkspace.shared.open(folder)
    }

    private func checkAppRelease() async {
        guard let url = URL(string: "https://api.github.com/repos/trozzelle/OfflineDAoC-macOS/releases/latest"),
              let (data, _) = try? await URLSession.shared.data(from: url) else { return }
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        guard let release = try? decoder.decode(LatestRelease.self, from: data), let version = status?.version,
              ReleaseCheck.isNewer(tag: release.tagName, than: version) else { return }
        appUpdate = URL(string: release.htmlUrl)
    }

    static func shellQuote(_ s: String) -> String {
        "'" + s.replacingOccurrences(of: "'", with: "'\\''") + "'"
    }

    static func tail(of log: URL) -> String {
        let text = (try? String(contentsOf: log, encoding: .utf8)) ?? ""
        return text.split(separator: "\n").suffix(8).joined(separator: "\n")
    }
}
