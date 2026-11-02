import XCTest
@testable import DaocKit

final class EventTests: XCTestCase {
    func testDecodesEveryEventAcrossChunkBoundaries() {
        let text = """
        {"t":"step","msg":"downloading Wine"}
        {"t":"download","path":"/d/x.part","bytes":1000,"what":"x"}
        {"t":"download","path":"/d/wine.tar.xz","bytes":null,"what":"Wine"}
        {"t":"ask","id":1,"question":"Stop?","default":false}
        {"t":"secret","id":2,"what":"login"}
        {"t":"error","msg":"refused","code":2}
        {"t":"later","x":1}
        not json

        """
        let data = Data(text.utf8)
        var decoder = EventLineDecoder()
        var events = decoder.feed(data.prefix(10))
        events += decoder.feed(data.dropFirst(10))
        XCTAssertEqual(events, [
            .step("downloading Wine"),
            .download(path: "/d/x.part", bytes: 1000, what: "x"),
            .download(path: "/d/wine.tar.xz", bytes: nil, what: "Wine"),
            .ask(id: 1, question: "Stop?", defaultAnswer: false),
            .secret(id: 2, what: "login"),
            .error(message: "refused", code: 2),
            .unknown("later"),
        ])
    }

    func testAnswersAreOneJSONLineTheCLIReads() throws {
        let ask = DaocAnswer.ask(id: 3, answer: true)
        XCTAssertEqual(ask.last, 0x0A)
        XCTAssertEqual(String(decoding: ask, as: UTF8.self), "{\"answer\":true,\"id\":3}\n")
        let secret = try JSONSerialization.jsonObject(
            with: DaocAnswer.secret(id: 4, account: "alice", password: "p\"w").dropLast()) as? [String: Any]
        XCTAssertEqual(secret?["id"] as? Int, 4)
        XCTAssertEqual(secret?["account"] as? String, "alice")
        XCTAssertEqual(secret?["password"] as? String, "p\"w")
    }
}
