import XCTest
@testable import DaocKit

final class ModelTests: XCTestCase {
    private func status(server: Bool, original: Bool, game: String = "0.37b",
                        switching: String? = nil, account: Bool? = nil,
                        save: String? = nil) throws -> StatusSnapshot {
        let json = """
        {"schema": 1, "version": "0.4.0", "home": "/h",
         "game": {"name": "\(game)", "version": "0.37", "edition": "sluaghbinder"},
         "client": "original", "switching_to": \(switching.map { "\"\($0)\"" } ?? "null"),
         "installed": {"server": \(server), "original_client": \(original), "new_client": false},
         "wine": "rosetta", "server": {"running": null, "detail": "x"},
         "client_running": null, "account_saved": \(account.map { "\($0)" } ?? "null"),
         "save": \(save.map { "\"\($0)\"" } ?? "null")}
        """
        return try StatusSnapshot.decode(Data(json.utf8))
    }

    func testStatusDecodesTheCLIsJSON() throws {
        let s = try status(server: true, original: false, account: true)
        XCTAssertEqual(s.game.name, "0.37b")
        XCTAssertTrue(s.installed.server)
        XCTAssertNil(s.server.running)
        XCTAssertEqual(s.accountSaved, true)
    }

    func testAFreshSetupSwitchesThenInstallsTheClients() {
        XCTAssertEqual(SetupPlan.commands(for: SetupChoice(game: "0.37b", newClient: true, arm64Wine: true), status: nil), [
            ["game", "switch", "0.37b"],
            ["client", "install", "--wine", "arm64"],
            ["client", "install", "--client", "new"],
        ])
    }

    func testAResumedSetupSkipsWhatIsDone() throws {
        XCTAssertEqual(SetupPlan.commands(for: SetupChoice(game: "0.37b"), status: try status(server: true, original: false)),
                       [["client", "install"]])
        XCTAssertEqual(SetupPlan.commands(for: SetupChoice(game: "0.37"), status: try status(server: true, original: true)),
                       [["game", "switch", "0.37"]])
        XCTAssertEqual(SetupPlan.commands(for: SetupChoice(game: "0.37b"),
                                          status: try status(server: true, original: true, switching: "0.37b")),
                       [["game", "switch", "0.37b"]])
    }

    func testSetupIsCompleteWithAServerAClientAndASavedAccount() throws {
        XCTAssertTrue(SetupPlan.isComplete(try status(server: true, original: true, account: true, save: "sluaghbinder")))
        XCTAssertFalse(SetupPlan.isComplete(try status(server: true, original: true, account: nil, save: "sluaghbinder")))
        XCTAssertFalse(SetupPlan.isComplete(try status(server: true, original: false, account: true, save: "sluaghbinder")))
    }

    /// The Keychain item is shared by every install on the Mac: an account saved by the CLI
    /// does not exist in a data home whose server has not created its world yet.
    func testAKeychainAccountFromAnotherInstallDoesNotCompleteSetup() throws {
        let cliUser = try status(server: true, original: true, account: true, save: nil)
        XCTAssertFalse(SetupPlan.isComplete(cliUser))
        XCTAssertFalse(SetupPlan.hasAccount(cliUser))
        XCTAssertTrue(SetupPlan.hasAccount(try status(server: true, original: true, account: true, save: "sluaghbinder")))
        XCTAssertFalse(SetupPlan.hasAccount(try status(server: true, original: true, account: nil, save: "sluaghbinder")))
        XCTAssertFalse(SetupPlan.hasAccount(try status(server: true, original: true, account: false, save: "sluaghbinder")))
    }

    func testRealmCountsLeaveOutBotsBeingDeleted() throws {
        let json = """
        [{"id":1,"name":"Aldric","realm":"Albion","class":"Armsman","race":"Briton","level":12,"zone":"","activity":"","goal":"","online":true,"deleting":false},
         {"id":2,"name":"Siv","realm":"Midgard","class":"Healer","race":"Norseman","level":1,"zone":"","activity":"","goal":"","online":false,"deleting":true},
         {"id":3,"name":"Bran","realm":"Albion","class":"Cleric","race":"Briton","level":50,"zone":"","activity":"","goal":"","online":false,"deleting":false}]
        """
        let bots = try JSONDecoder().decode([Bot].self, from: Data(json.utf8))
        XCTAssertEqual(BotRoster.counts(bots), [
            RealmCount(realm: .albion, roster: 2, online: 1),
            RealmCount(realm: .midgard, roster: 0, online: 0),
            RealmCount(realm: .hibernia, roster: 0, online: 0),
        ])
    }

    func testReleaseCheck() {
        XCTAssertTrue(ReleaseCheck.isNewer(tag: "v0.5.0", than: "0.4.0"))
        XCTAssertTrue(ReleaseCheck.isNewer(tag: "v0.4.10", than: "0.4.9"))
        XCTAssertFalse(ReleaseCheck.isNewer(tag: "v0.4.0", than: "0.4.0"))
        XCTAssertFalse(ReleaseCheck.isNewer(tag: "v0.3.9", than: "0.4.0"))
    }

    func testWrapperFileNamesItsDataFolder() {
        let marker = WrapperFile.marker
        XCTAssertEqual(WrapperFile.dataFolder(fromWrapper: "#!/bin/sh\n\(marker)\nCHECKOUT='/a b/it'\"'\"'s'\nexec x\n"),
                       "/a b/it's")
        XCTAssertEqual(WrapperFile.dataFolder(fromWrapper: "#!/bin/sh\n\(marker)\nCHECKOUT=/app/Resources/daoc\nDAOC_DATA=/d\nexport DAOC_DATA\n"),
                       "/d")
        XCTAssertNil(WrapperFile.dataFolder(fromWrapper: "#!/bin/sh\nCHECKOUT=/x\n"))
    }
}
