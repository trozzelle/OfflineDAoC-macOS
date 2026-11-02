import XCTest
@testable import DaocKit

final class DaocProcessTests: XCTestCase {
    private var dir: URL!

    override func setUpWithError() throws {
        dir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: dir)
    }

    private func launcher(_ body: String) throws -> URL {
        let url = dir.appendingPathComponent("daoc")
        try ("#!/bin/sh\n" + body).write(to: url, atomically: true, encoding: .utf8)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: url.path)
        return url
    }

    private func invocation(_ launcher: URL, _ arguments: [String] = []) -> DaocInvocation {
        DaocInvocation(launcher: launcher, dataHome: dir.appendingPathComponent("data"),
                       arguments: arguments, logFile: dir.appendingPathComponent("logs/run.log"))
    }

    func testEventsAnswersStdoutLogAndStatus() async throws {
        let url = try launcher("""
        echo "args $*"
        echo "data $DAOC_DATA events $DAOC_EVENTS"
        echo 'to the log' >&2
        printf '{"t":"ask","id":1,"question":"Stop?","default":false}\\n' >&3
        read answer
        echo "answer $answer"
        printf '{"t":"error","msg":"refused","code":2}\\n' >&3
        exit 2
        """)
        let process = DaocProcess(invocation(url, ["server", "stop"]))
        let result = try await process.run { event in
            if case .ask(let id, _, _) = event { process.answer(DaocAnswer.ask(id: id, answer: true)) }
        }
        XCTAssertEqual(result.status, 2)
        XCTAssertEqual(result.errorMessage, "refused")
        XCTAssertEqual(result.events.first, .ask(id: 1, question: "Stop?", defaultAnswer: false))
        let out = String(decoding: result.stdout, as: UTF8.self)
        XCTAssertTrue(out.contains("args server stop\n"), out)
        XCTAssertTrue(out.contains("data \(dir.appendingPathComponent("data").path) events 3\n"), out)
        XCTAssertTrue(out.contains("answer {\"answer\":true,\"id\":1}\n"), out)
        XCTAssertEqual(try String(contentsOf: dir.appendingPathComponent("logs/run.log"), encoding: .utf8),
                       "to the log\n")
    }

    func testReturnsWhenTheCommandExitsThoughAChildStillHoldsThePipes() async throws {
        // daoc-server.sh start --detach leaves the server running; the app must not wait for it.
        let pidFile = dir.appendingPathComponent("sleep.pid")
        let url = try launcher("sleep 20 &\necho $! > '\(pidFile.path)'\necho started\n")
        let started = Date()
        let result = try await DaocProcess(invocation(url)).run { _ in }
        XCTAssertEqual(result.status, 0)
        XCTAssertEqual(String(decoding: result.stdout, as: UTF8.self), "started\n")
        XCTAssertLessThan(Date().timeIntervalSince(started), 10)
        if let text = try? String(contentsOf: pidFile, encoding: .utf8),
           let pid = pid_t(text.trimmingCharacters(in: .whitespacesAndNewlines)) {
            kill(pid, SIGKILL)
        }
    }

    func testInterruptReachesTheCommand() async throws {
        let url = try launcher("trap 'exit 130' INT\nwhile :; do sleep 0.1; done\n")
        let process = DaocProcess(invocation(url))
        Task {
            try? await Task.sleep(nanoseconds: 500_000_000)
            process.interrupt()
        }
        let result = try await process.run { _ in }
        XCTAssertEqual(result.status, 130)
    }

    func testInterruptBeforeSpawnIsKept() async throws {
        let url = try launcher("trap 'exit 130' INT\nwhile :; do sleep 0.1; done\n")
        let process = DaocProcess(invocation(url))
        process.interrupt()
        let result = try await process.run { _ in }
        XCTAssertEqual(result.status, 130)
    }

    func testALateAnswerNeverRaisesSIGPIPE() async throws {
        // The command exits without reading stdin; answers sent after (and racing) its exit
        // write to a pipe with no reader. SIGPIPE would kill this test process.
        let url = try launcher("printf '{\"t\":\"ask\",\"id\":1,\"question\":\"?\",\"default\":true}\\n' >&3\nsleep 0.1\nexit 0\n")
        let process = DaocProcess(invocation(url))
        let result = try await process.run { event in
            if case .ask(let id, _, _) = event {
                for _ in 0..<50 { process.answer(DaocAnswer.ask(id: id, answer: true)) }
                // Hold the queue until the command has exited: the answers above then run after
                // its exit but before the completion block closes stdin.
                Thread.sleep(forTimeInterval: 0.5)
            }
        }
        XCTAssertEqual(result.status, 0)
        for _ in 0..<50 { process.answer(DaocAnswer.ask(id: 1, answer: true)) }
        try await Task.sleep(nanoseconds: 200_000_000)  // let the queued writes run
    }
}
