import DaocKit
import SwiftUI

struct SetupView: View {
    @EnvironmentObject var model: AppModel
    @State private var page: Page = .check
    @State private var choice = SetupChoice(arm64Wine: !SystemChecks.rosettaInstalled && SystemChecks.macOSMajor >= 27)
    @State private var rosetta = SystemChecks.rosettaInstalled
    @State private var account = ""
    @State private var password = ""
    @State private var installFailed = false
    @State private var installing = false

    enum Page { case check, choose, install, account, done }

    private static let baseBytes: Int64 = 8_000_000_000
    private static let newClientBytes: Int64 = 36_000_000_000

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text("Offline DAoC Setup").font(.largeTitle.bold())
            switch page {
            case .check: checkPage
            case .choose: choosePage
            case .install: installPage
            case .account: accountPage
            case .done: donePage
            }
            Spacer()
        }
        .padding(32)
    }

    private var rosettaOK: Bool { rosetta || SystemChecks.macOSMajor >= 27 }
    private var existing: URL? {
        SystemChecks.existingInstall().flatMap { $0.standardizedFileURL == model.paths.dataHome.standardizedFileURL ? nil : $0 }
    }

    private var checkPage: some View {
        let free = SystemChecks.freeBytes()
        let ready = SystemChecks.isAppleSilicon && SystemChecks.macOSMajor >= 26 && free >= Self.baseBytes && rosettaOK
        return VStack(alignment: .leading, spacing: 10) {
            CheckRow("A Mac with Apple Silicon", ok: SystemChecks.isAppleSilicon)
            CheckRow("macOS 26 or later", ok: SystemChecks.macOSMajor >= 26)
            CheckRow("8 GB free (\(RunProgressView.size(free)) free)", ok: free >= Self.baseBytes)
            CheckRow(rosetta ? "Rosetta 2"
                     : (SystemChecks.macOSMajor >= 27 ? "No Rosetta: the game will use the arm64 Wine"
                        : "Rosetta 2 is needed"), ok: rosettaOK)
            HStack {
                if !rosettaOK {
                    Button("Install Rosetta") {
                        rosetta = SystemChecks.installRosetta()
                        choice.arm64Wine = !rosetta && SystemChecks.macOSMajor >= 27
                    }
                }
                if let existing {
                    Button("Use my existing install") {
                        model.adopt(existing)
                        Task {
                            await model.refreshStatus()
                            if let status = model.status, SetupPlan.isComplete(status) { model.mode = .launcher }
                        }
                    }
                }
                Spacer()
                Button("Continue") { page = .choose }
                    .keyboardShortcut(.defaultAction)
                    .disabled(!ready)
            }
        }
    }

    private var choosePage: some View {
        let need = Self.baseBytes + (choice.newClient ? Self.newClientBytes : 0)
        return VStack(alignment: .leading, spacing: 12) {
            Picker("Game", selection: $choice.game) {
                Text("0.37b, with the Sluaghbinder").tag("0.37b")
                Text("0.37, classic classes only").tag("0.37")
            }
            .pickerStyle(.radioGroup)
            Toggle("Also install the new client (about 34 GB more)", isOn: $choice.newClient)
            if choice.arm64Wine {
                Text("The game runs on the arm64 Wine (no Rosetta).").foregroundStyle(.secondary)
            }
            HStack {
                Button("Back") { page = .check }
                Spacer()
                if SystemChecks.freeBytes() < need {
                    Text("Needs \(RunProgressView.size(need)) free").foregroundStyle(.red)
                }
                Button("Install") { page = .install }
                    .keyboardShortcut(.defaultAction)
                    .disabled(SystemChecks.freeBytes() < need)
            }
        }
    }

    private var installPage: some View {
        VStack(alignment: .leading, spacing: 12) {
            if let run = model.running { RunProgressView(run: run) }
            if installFailed {
                HStack {
                    Text("Setup stopped. It continues where it stopped.").foregroundStyle(.secondary)
                    Spacer()
                    Button("Try again") {
                        installFailed = false
                        Task { await install() }
                    }
                }
            }
        }
        .task { await install() }
    }

    /// Runs the plan once at a time. SwiftUI re-runs `.task` whenever the page reappears, and
    /// `model.run` refuses a second command while one runs; without the guard that refusal would
    /// show as a failed install. A failed install waits for "Try again" instead of rerunning itself.
    private func install() async {
        guard !installing, !installFailed else { return }
        installing = true
        defer { installing = false }
        for command in SetupPlan.commands(for: choice, status: model.status) {
            guard await model.run(Self.title(command), command) else {
                installFailed = true
                return
            }
        }
        page = model.status?.accountSaved == true ? .done : .account
    }

    static func title(_ command: [String]) -> String {
        if command.first == "game" { return "Install the server for \(command[2])" }
        if command.contains("new") { return "Install the new client" }
        return "Install the game client and Wine"
    }

    private var accountPage: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Your game account lives on your own server. Pick any name and password.")
            TextField("Account name", text: $account).frame(maxWidth: 320)
            SecureField("Password", text: $password).frame(maxWidth: 320)
            HStack {
                Spacer()
                Button("Create account") {
                    Task { if await model.createAccount(account, password) { page = .done } }
                }
                .keyboardShortcut(.defaultAction)
                .disabled(account.isEmpty || password.isEmpty || model.running != nil)
            }
            if let run = model.running { RunProgressView(run: run) }
        }
    }

    private var donePage: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("The realm awaits.").font(.title2)
            Text("Make some bots in the Bots panel, then press Play.")
            Button("Open the launcher") { model.mode = .launcher }.keyboardShortcut(.defaultAction)
        }
    }
}
