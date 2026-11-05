import DaocKit
import SwiftUI

struct LauncherView: View {
    @EnvironmentObject var model: AppModel
    @State private var game = "0.37b"
    private static let games = ["0.37b", "0.37"]

    private var busy: Bool { model.running != nil }
    private var serverRunning: Bool { model.status?.server.running == true }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                header
                HStack(spacing: 12) {
                    Button { Task { await model.play() } } label: {
                        Label("Play", systemImage: "play.fill").frame(minWidth: 120)
                    }
                    .controlSize(.large)
                    .keyboardShortcut(.defaultAction)
                    .disabled(busy)
                    Button("Stop the game") { Task { await model.run("Stop the game", ["client", "stop"]) } }
                        .disabled(busy || model.status?.clientRunning == nil)
                }
                if let run = model.running { RunProgressView(run: run) }
                GroupBox("Server") {
                    HStack {
                        Button("Start") { Task { await model.run("Start the server", ["server", "start", "--detach"]) } }
                            .disabled(busy || serverRunning)
                        Button("Stop") { Task { await model.run("Stop the server", ["server", "stop"]) } }
                            .disabled(busy || !serverRunning)
                        Button("Open admin console") { model.openAdminConsole() }
                        Button("Show logs") { model.showLogs() }
                        Spacer()
                    }
                }
                BotsPanel().disabled(busy || !serverRunning)
                settings
                updates
            }
            .padding(24)
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("Offline DAoC").font(.largeTitle.bold())
            if let s = model.status {
                Text("Game \(s.game.name) · \(s.client) client · Wine: \(s.wine ?? "not installed")")
                    .foregroundStyle(.secondary)
                Label(s.server.running == true ? "Server running"
                      : (s.server.running == false ? "Server stopped" : "Server state unknown: \(s.server.detail)"),
                      systemImage: "circle.fill")
                    .foregroundStyle(s.server.running == true ? Color.green : Color.secondary)
            }
        }
    }

    private var settings: some View {
        GroupBox("Settings") {
            VStack(alignment: .leading) {
                HStack {
                    Picker("Game", selection: $game) {
                        ForEach(Self.games, id: \.self) { Text($0).tag($0) }
                    }
                    .frame(width: 200)
                    Button("Switch") { Task { await model.run("Switch to \(game)", ["game", "switch", game]) } }
                        .disabled(busy || game == model.status?.game.name)
                }
                HStack {
                    Button("Add the new client (36 GB), make it the default") {
                        Task { await model.run("Install the new client", ["client", "install", "--client", "new"]) }
                    }
                    .disabled(busy || model.status?.installed.newClient == true)
                    let wine = model.status?.wine == "arm64" ? "rosetta" : "arm64"
                    let wineName = wine == "arm64" ? "arm64" : "Rosetta"
                    Button("Use the \(wineName) Wine") {
                        Task { await model.run("Switch to the \(wineName) Wine", ["client", "install", "--wine", wine]) }
                    }
                    .disabled(busy || model.status?.client == "new" || (wine == "arm64" && SystemChecks.macOSMajor < 27))
                    .help("The Wine choice applies to the original client")
                    Button("Change account…") { Task { await model.run("Change the game account", ["client", "login"]) } }
                        .disabled(busy)
                }
            }
        }
        .onAppear {
            if let name = model.status?.game.name, Self.games.contains(name) { game = name }
        }
    }

    private var updates: some View {
        GroupBox("Updates") {
            HStack {
                Button("Check for updates") { Task { await model.checkForClientUpdates() } }
                Button("Update the client") { Task { await model.run("Update the client", ["client", "update"]) } }
                    .disabled(busy)
                if let url = model.appUpdate { Link("A new OfflineDAoC is out", destination: url) }
                Spacer()
            }
        }
    }
}
