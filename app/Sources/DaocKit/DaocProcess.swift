import Darwin
import Foundation

public struct DaocInvocation: Sendable {
    public var launcher: URL
    public var dataHome: URL
    public var arguments: [String]
    public var logFile: URL

    public init(launcher: URL, dataHome: URL, arguments: [String], logFile: URL) {
        self.launcher = launcher
        self.dataHome = dataHome
        self.arguments = arguments
        self.logFile = logFile
    }
}

public struct DaocResult: Sendable {
    public let status: Int32
    public let stdout: Data
    public let events: [DaocEvent]

    /// The message of the last `error` event, when daoc sent one.
    public var errorMessage: String? {
        for case let .error(message, _) in events.reversed() { return message }
        return nil
    }
}

public enum DaocProcessError: Error, Equatable {
    case log(Int32), pipe(Int32), spawn(Int32)
}

/// One `daoc` command: events on fd 3 (DAOC_EVENTS=3), answers on stdin, stdout
/// captured, stderr appended to the log file. It runs in its own process group so
/// interrupt() reaches what it started. It is done when it exits: whatever it left
/// running (a detached server) may hold the pipes open, so they are drained once,
/// never read to EOF.
public final class DaocProcess: @unchecked Sendable {
    public let invocation: DaocInvocation
    private let queue = DispatchQueue(label: "daoc.process")
    private var pid: pid_t = 0
    private var stdinFD: Int32 = -1

    public init(_ invocation: DaocInvocation) {
        self.invocation = invocation
    }

    /// Runs the command; onEvent is called on a background queue, in order.
    public func run(onEvent: @escaping @Sendable (DaocEvent) -> Void) async throws -> DaocResult {
        try await withCheckedThrowingContinuation { continuation in
            queue.async {
                do {
                    try self.start(onEvent: onEvent) { continuation.resume(returning: $0) }
                } catch {
                    continuation.resume(throwing: error)
                }
            }
        }
    }

    /// Sends one answer line (DaocAnswer) to the command's stdin.
    public func answer(_ line: Data) {
        queue.async {
            guard self.stdinFD >= 0 else { return }
            line.withUnsafeBytes { buffer in _ = write(self.stdinFD, buffer.baseAddress, buffer.count) }
        }
    }

    /// SIGINT to the command's process group: daoc exits 130 through its own Ctrl-C path.
    public func interrupt() {
        queue.async { if self.pid > 0 { kill(-self.pid, SIGINT) } }
    }

    static func exitCode(_ status: Int32) -> Int32 {
        let signal = status & 0x7f
        return signal == 0 ? (status >> 8) & 0xff : 128 + signal
    }

    private func start(onEvent: @escaping @Sendable (DaocEvent) -> Void,
                       done: @escaping (DaocResult) -> Void) throws {
        try FileManager.default.createDirectory(at: invocation.logFile.deletingLastPathComponent(),
                                                withIntermediateDirectories: true)
        let logFD = open(invocation.logFile.path, O_WRONLY | O_CREAT | O_APPEND | O_CLOEXEC, 0o644)
        guard logFD >= 0 else { throw DaocProcessError.log(errno) }
        var input: [Int32] = [-1, -1], output: [Int32] = [-1, -1], channel: [Int32] = [-1, -1]
        guard pipe(&input) == 0, pipe(&output) == 0, pipe(&channel) == 0 else {
            let error = errno
            for fd in input + output + channel + [logFD] where fd >= 0 { close(fd) }
            throw DaocProcessError.pipe(error)
        }

        var actions: posix_spawn_file_actions_t?
        posix_spawn_file_actions_init(&actions)
        defer { posix_spawn_file_actions_destroy(&actions) }
        posix_spawn_file_actions_adddup2(&actions, input[0], 0)
        posix_spawn_file_actions_adddup2(&actions, output[1], 1)
        posix_spawn_file_actions_adddup2(&actions, logFD, 2)
        posix_spawn_file_actions_adddup2(&actions, channel[1], 3)
        var attributes: posix_spawnattr_t?
        posix_spawnattr_init(&attributes)
        defer { posix_spawnattr_destroy(&attributes) }
        // Only fds 0-3 reach the child; it leads a new process group; it starts with
        // default signal dispositions and an empty mask (an ignored SIGINT cannot be trapped).
        var defaults = sigset_t(), none = sigset_t()
        sigfillset(&defaults)
        sigemptyset(&none)
        posix_spawnattr_setsigdefault(&attributes, &defaults)
        posix_spawnattr_setsigmask(&attributes, &none)
        posix_spawnattr_setflags(&attributes, Int16(POSIX_SPAWN_SETPGROUP | POSIX_SPAWN_CLOEXEC_DEFAULT
                                                    | POSIX_SPAWN_SETSIGDEF | POSIX_SPAWN_SETSIGMASK))
        posix_spawnattr_setpgroup(&attributes, 0)

        var environment = ProcessInfo.processInfo.environment
        environment["DAOC_DATA"] = invocation.dataHome.path
        environment["DAOC_EVENTS"] = "3"
        let argv = [invocation.launcher.path] + invocation.arguments
        let envp = environment.map { "\($0.key)=\($0.value)" }
        var child: pid_t = 0
        let rc = withCStrings(argv) { argvC in
            withCStrings(envp) { envC in
                posix_spawn(&child, invocation.launcher.path, &actions, &attributes, argvC, envC)
            }
        }
        for fd in [input[0], output[1], channel[1], logFD] { close(fd) }
        guard rc == 0 else {
            for fd in [input[1], output[0], channel[0]] { close(fd) }
            throw DaocProcessError.spawn(rc)
        }
        pid = child
        stdinFD = input[1]

        var decoder = EventLineDecoder()
        var events: [DaocEvent] = []
        var stdout = Data()
        let eventReader = Reader(fd: channel[0], queue: queue) { data in
            for event in decoder.feed(data) {
                events.append(event)
                onEvent(event)
            }
        }
        let outputReader = Reader(fd: output[0], queue: queue) { stdout.append($0) }
        Thread.detachNewThread { [queue] in
            var status: Int32 = 0
            while waitpid(child, &status, 0) < 0 && errno == EINTR {}
            queue.async {
                eventReader.pump()
                outputReader.pump()
                eventReader.finish()
                outputReader.finish()
                close(self.stdinFD)
                self.stdinFD = -1
                self.pid = 0
                done(DaocResult(status: Self.exitCode(status), stdout: stdout, events: events))
            }
        }
    }
}

/// A non-blocking pipe read end, pumped by a dispatch source on the process queue.
private final class Reader {
    private let fd: Int32
    private let source: DispatchSourceRead
    private let onData: (Data) -> Void
    private var open = true

    init(fd: Int32, queue: DispatchQueue, onData: @escaping (Data) -> Void) {
        self.fd = fd
        self.onData = onData
        _ = fcntl(fd, F_SETFL, fcntl(fd, F_GETFL) | O_NONBLOCK)
        source = DispatchSource.makeReadSource(fileDescriptor: fd, queue: queue)
        source.setEventHandler { [unowned self] in self.pump() }
        source.setCancelHandler { close(fd) }
        source.resume()
    }

    func pump() {
        guard open else { return }
        var buffer = [UInt8](repeating: 0, count: 65536)
        while true {
            let n = read(fd, &buffer, buffer.count)
            if n > 0 {
                onData(Data(buffer[0..<n]))
                continue
            }
            if n < 0 && (errno == EAGAIN || errno == EINTR) { return }
            finish()  // EOF or a read error
            return
        }
    }

    func finish() {
        guard open else { return }
        open = false
        source.cancel()
    }
}

private func withCStrings<R>(_ strings: [String],
                             _ body: (UnsafePointer<UnsafeMutablePointer<CChar>?>) -> R) -> R {
    var pointers: [UnsafeMutablePointer<CChar>?] = strings.map { strdup($0) }
    pointers.append(nil)
    defer { pointers.forEach { free($0) } }
    return pointers.withUnsafeBufferPointer { body($0.baseAddress!) }
}
