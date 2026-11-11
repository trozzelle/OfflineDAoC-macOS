import AppKit
import DaocKit
import Foundation

enum SystemChecks {
    static var isAppleSilicon: Bool {
        var value: Int32 = 0
        var size = MemoryLayout<Int32>.size
        return sysctlbyname("hw.optional.arm64", &value, &size, nil, 0) == 0 && value == 1
    }

    static var macOSMajor: Int { ProcessInfo.processInfo.operatingSystemVersion.majorVersion }

    static var rosettaInstalled: Bool {
        FileManager.default.fileExists(atPath: "/Library/Apple/usr/libexec/oah/libRosettaRuntime")
    }

    static func freeBytes() -> Int64 {
        let values = try? FileManager.default.homeDirectoryForCurrentUser
            .resourceValues(forKeys: [.volumeAvailableCapacityForImportantUsageKey])
        return values?.volumeAvailableCapacityForImportantUsage ?? 0
    }

    /// macOS asks for an administrator password itself.
    @MainActor static func installRosetta() -> Bool {
        var error: NSDictionary?
        NSAppleScript(source: "do shell script \"/usr/sbin/softwareupdate --install-rosetta --agree-to-license\" with administrator privileges")?
            .executeAndReturnError(&error)
        return error == nil && rosettaInstalled
    }

    /// A data folder named by ~/.local/bin/daoc, when it holds an install.
    static func existingInstall() -> URL? {
        let wrapper = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".local/bin/daoc")
        guard let text = try? String(contentsOf: wrapper, encoding: .utf8),
              let path = WrapperFile.dataFolder(fromWrapper: text) else { return nil }
        let folder = URL(fileURLWithPath: path, isDirectory: true)
        let markers = ["server/dist/daoc-server", "dist", ".daoc"]
        return markers.contains { FileManager.default.fileExists(atPath: folder.appendingPathComponent($0).path) } ? folder : nil
    }
}
