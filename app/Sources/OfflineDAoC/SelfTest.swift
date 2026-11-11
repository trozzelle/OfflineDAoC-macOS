import DaocKit
import Foundation

/// `OfflineDAoC --self-test`: the bundled daoc runs under this app's signature
/// (CI runs it after signing): --version, and status --json on an empty data home.
enum SelfTest {
    static func run() -> Int32 {
        let paths = AppPaths.current()
        let data = FileManager.default.temporaryDirectory.appendingPathComponent("offlinedaoc-selftest-\(getpid())")
        defer { try? FileManager.default.removeItem(at: data) }
        for arguments in [["--version"], ["status", "--json"]] {
            let process = Process()
            process.executableURL = paths.launcher
            process.arguments = arguments
            process.environment = ProcessInfo.processInfo.environment.merging(["DAOC_DATA": data.path]) { $1 }
            let output = Pipe()
            process.standardOutput = output
            do {
                try process.run()
            } catch {
                print("self-test: cannot run \(paths.launcher.path): \(error)")
                return 1
            }
            let stdout = output.fileHandleForReading.readDataToEndOfFile()
            process.waitUntilExit()
            let name = "daoc " + arguments.joined(separator: " ")
            guard process.terminationStatus == 0 else {
                print("self-test: \(name) exited \(process.terminationStatus)")
                return 1
            }
            if arguments.first == "status", (try? StatusSnapshot.decode(stdout)) == nil {
                print("self-test: \(name) printed no status")
                return 1
            }
            print("self-test: \(name) ok")
        }
        return 0
    }
}
