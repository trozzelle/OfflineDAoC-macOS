import DaocKit
import SwiftUI

struct BotsPanel: View {
    @EnvironmentObject var model: AppModel
    @State private var count = 10

    private var rows: [RealmCount] {
        model.realms.isEmpty ? Realm.allCases.map { RealmCount(realm: $0, roster: 0, online: 0) } : model.realms
    }

    /// Reads the polled value; only a user's toggle reaches `setPopulation`, never a refresh.
    private var populationBinding: Binding<Bool> {
        Binding(get: { model.population ?? false },
                set: { on in
                    guard on != model.population else { return }
                    Task { await model.setPopulation(on) }
                })
    }

    var body: some View {
        GroupBox("Bots") {
            VStack(alignment: .leading, spacing: 8) {
                Grid(alignment: .leading, horizontalSpacing: 16, verticalSpacing: 6) {
                    GridRow {
                        Text("Realm").bold()
                        Text("Roster").bold()
                        Text("In the world").bold()
                        Text("")
                        Text("")
                    }
                    ForEach(rows, id: \.realm) { row in
                        GridRow {
                            Text(row.realm.rawValue)
                            Text("\(row.roster)")
                            Text("\(row.online)")
                            Button("+ Lv.1") { Task { await model.createBots(row.realm, level: 1, count: count) } }
                            Button("+ Lv.50") { Task { await model.createBots(row.realm, level: 50, count: count) } }
                        }
                    }
                }
                HStack {
                    Stepper("Bots per click: \(count)", value: $count, in: 1...100)
                    Spacer()
                    Toggle("Population", isOn: populationBinding)
                        .disabled(model.population == nil)
                }
            }
        }
    }
}
