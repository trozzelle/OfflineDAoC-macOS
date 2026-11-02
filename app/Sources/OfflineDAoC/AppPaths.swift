import Foundation

/// Where the bundled daoc lives and where it installs.
struct AppPaths {
    static let dataHomeKey = "dataHome"

    let resources: URL
    var dataHome: URL

    /// Contents/Resources/daoc/daoc: the repo's ./daoc launcher, next to Resources/python.
    var launcher: URL { resources.appendingPathComponent("daoc/daoc") }
    var logs: URL { dataHome.appendingPathComponent("logs/app", isDirectory: true) }
    var serverLogs: URL { dataHome.appendingPathComponent("server/dist/daoc-server/logs", isDirectory: true) }

    static func current() -> AppPaths {
        let resources = Bundle.main.resourceURL ?? URL(fileURLWithPath: CommandLine.arguments[0]).deletingLastPathComponent()
        let saved = UserDefaults.standard.string(forKey: dataHomeKey)
        return AppPaths(resources: resources, dataHome: saved.map { URL(fileURLWithPath: $0, isDirectory: true) } ?? defaultDataHome)
    }

    static var defaultDataHome: URL {
        FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("OfflineDAoC", isDirectory: true)
    }

    func logFile(for arguments: [String]) -> URL {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyyMMdd-HHmmss"
        let name = ([formatter.string(from: Date())] + arguments.prefix(2)).joined(separator: "-")
        return logs.appendingPathComponent(name + ".log")
    }
}
