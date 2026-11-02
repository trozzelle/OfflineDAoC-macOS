import Foundation

/// One line daoc writes on its DAOC_EVENTS channel (see daoc_cli/events.py).
public enum DaocEvent: Equatable, Sendable {
    case step(String)
    case download(path: String, bytes: Int64?, what: String)
    case ask(id: Int, question: String, defaultAnswer: Bool)
    case secret(id: Int, what: String)
    case error(message: String, code: Int)
    case unknown(String)
}

extension DaocEvent: Decodable {
    private enum Key: String, CodingKey {
        case t, msg, path, bytes, what, id, question, code
        case defaultAnswer = "default"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: Key.self)
        let kind = try c.decode(String.self, forKey: .t)
        switch kind {
        case "step":
            self = .step(try c.decode(String.self, forKey: .msg))
        case "download":
            self = .download(path: try c.decode(String.self, forKey: .path),
                             bytes: try c.decodeIfPresent(Int64.self, forKey: .bytes),
                             what: try c.decode(String.self, forKey: .what))
        case "ask":
            self = .ask(id: try c.decode(Int.self, forKey: .id),
                        question: try c.decode(String.self, forKey: .question),
                        defaultAnswer: try c.decodeIfPresent(Bool.self, forKey: .defaultAnswer) ?? false)
        case "secret":
            self = .secret(id: try c.decode(Int.self, forKey: .id), what: try c.decode(String.self, forKey: .what))
        case "error":
            self = .error(message: try c.decode(String.self, forKey: .msg), code: try c.decode(Int.self, forKey: .code))
        default:
            self = .unknown(kind)
        }
    }
}

/// Splits the channel's bytes into lines and decodes each. A line that is not an
/// event is dropped: the command's stderr log still has everything.
public struct EventLineDecoder {
    private var buffer = Data()

    public init() {}

    public mutating func feed(_ data: Data) -> [DaocEvent] {
        buffer.append(data)
        var events: [DaocEvent] = []
        while let newline = buffer.firstIndex(of: 0x0A) {
            let line = buffer[buffer.startIndex..<newline]
            buffer.removeSubrange(buffer.startIndex...newline)
            if let event = try? JSONDecoder().decode(DaocEvent.self, from: line) {
                events.append(event)
            }
        }
        return events
    }
}

/// Answers to `ask` and `secret`, one JSON line each, for the command's stdin.
public enum DaocAnswer {
    public static func ask(id: Int, answer: Bool) -> Data {
        line(["id": id, "answer": answer])
    }

    public static func secret(id: Int, account: String, password: String) -> Data {
        line(["id": id, "account": account, "password": password])
    }

    private static func line(_ object: [String: Any]) -> Data {
        var data = (try? JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])) ?? Data()
        data.append(0x0A)
        return data
    }
}
