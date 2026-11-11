import Foundation

/// `daoc status --json` (daoc_cli/status.py, schema 1).
public struct StatusSnapshot: Decodable, Equatable, Sendable {
    public struct Game: Decodable, Equatable, Sendable {
        public let name: String
        public let version: String
        public let edition: String
    }

    public struct Installed: Decodable, Equatable, Sendable {
        public let server: Bool
        public let originalClient: Bool
        public let newClient: Bool
    }

    public struct Server: Decodable, Equatable, Sendable {
        public let running: Bool?
        public let detail: String
    }

    public let schema: Int
    public let version: String
    public let home: String
    public let game: Game
    public let client: String
    public let switchingTo: String?
    public let installed: Installed
    public let wine: String?
    public let server: Server
    public let clientRunning: String?
    public let accountSaved: Bool?
    public let save: String?

    public static func decode(_ data: Data) throws -> StatusSnapshot {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(StatusSnapshot.self, from: data)
    }
}

/// One entry of `daoc admin bots list --json`; the other keys are ignored.
public struct Bot: Decodable, Equatable, Sendable {
    public let name: String
    public let realm: String
    public let level: Int
    public let online: Bool
    public let deleting: Bool
}

/// `daoc admin population --json`; the other keys are ignored.
public struct Population: Decodable, Equatable, Sendable {
    public let enabled: Bool
}

public enum Realm: String, CaseIterable, Sendable {
    case albion = "Albion", midgard = "Midgard", hibernia = "Hibernia"

    /// The name `daoc-admin bots create --realm` takes.
    public var adminName: String {
        switch self {
        case .albion: return "alb"
        case .midgard: return "mid"
        case .hibernia: return "hib"
        }
    }
}

public struct RealmCount: Equatable, Sendable {
    public let realm: Realm
    public let roster: Int
    public let online: Int

    public init(realm: Realm, roster: Int, online: Int) {
        self.realm = realm
        self.roster = roster
        self.online = online
    }
}

public enum BotRoster {
    /// Roster and in-world counts per realm, every realm listed; bots queued for deletion left out.
    public static func counts(_ bots: [Bot]) -> [RealmCount] {
        let kept = bots.filter { !$0.deleting }
        return Realm.allCases.map { realm in
            let mine = kept.filter { $0.realm == realm.rawValue }
            return RealmCount(realm: realm, roster: mine.count, online: mine.filter(\.online).count)
        }
    }
}

public struct SetupChoice: Equatable, Sendable {
    public var game: String
    public var newClient: Bool
    public var arm64Wine: Bool

    public init(game: String = "0.37b", newClient: Bool = false, arm64Wine: Bool = false) {
        self.game = game
        self.newClient = newClient
        self.arm64Wine = arm64Wine
    }
}

public enum SetupPlan {
    /// The daoc commands Setup runs, in order, leaving out what status says is done.
    /// `game switch` on an empty data home installs the server, writes its edition and
    /// records the Selection, and installs no client.
    public static func commands(for choice: SetupChoice, status: StatusSnapshot?) -> [[String]] {
        var commands: [[String]] = []
        let installed = status?.installed
        if !(installed?.server ?? false) || status?.game.name != choice.game || status?.switchingTo != nil {
            commands.append(["game", "switch", choice.game])
        }
        if !(installed?.originalClient ?? false) {
            commands.append(["client", "install"] + (choice.arm64Wine ? ["--wine", "arm64"] : []))
        }
        if choice.newClient && !(installed?.newClient ?? false) {
            commands.append(["client", "install", "--client", "new"])
        }
        return commands
    }

    /// Whether this install has an account to log in with. The Keychain item is global, shared by
    /// every install on the Mac, so it counts only once this data home's server has created its
    /// world (`save` is set): a fresh world has no accounts.
    public static func hasAccount(_ status: StatusSnapshot) -> Bool {
        status.accountSaved == true && status.save != nil
    }

    public static func isComplete(_ status: StatusSnapshot) -> Bool {
        status.installed.server && (status.installed.originalClient || status.installed.newClient)
            && hasAccount(status)
    }
}

public enum ReleaseCheck {
    /// Whether a release tag (v0.5.0) is newer than version.txt's version (0.4.0).
    public static func isNewer(tag: String, than current: String) -> Bool {
        func parts(_ s: String) -> [Int] {
            s.trimmingCharacters(in: CharacterSet(charactersIn: "v")).split(separator: ".").map { Int($0) ?? 0 }
        }
        let a = parts(tag), b = parts(current)
        for i in 0..<max(a.count, b.count) {
            let x = i < a.count ? a[i] : 0, y = i < b.count ? b[i] : 0
            if x != y { return x > y }
        }
        return false
    }
}

/// The ~/.local/bin/daoc wrapper `daoc self-install` writes (daoc_cli/self_install.py).
public enum WrapperFile {
    public static let marker = "# daoc wrapper written by daoc self-install"

    /// The data folder a wrapper names: its DAOC_DATA, else its CHECKOUT; nil for any other file.
    public static func dataFolder(fromWrapper text: String) -> String? {
        let lines = text.split(separator: "\n", omittingEmptySubsequences: false).map(String.init)
        guard lines.contains(marker) else { return nil }
        func value(_ key: String) -> String? {
            lines.first { $0.hasPrefix(key + "=") }.flatMap { unquote(String($0.dropFirst(key.count + 1))) }
        }
        return value("DAOC_DATA") ?? value("CHECKOUT")
    }

    /// Undoes Python's shlex.quote: 'a b', with '"'"' for a quote inside.
    static func unquote(_ s: String) -> String? {
        guard s.hasPrefix("'") else { return s.isEmpty ? nil : s }
        guard s.count >= 2, s.hasSuffix("'") else { return nil }
        return String(s.dropFirst().dropLast()).replacingOccurrences(of: "'\"'\"'", with: "'")
    }
}
