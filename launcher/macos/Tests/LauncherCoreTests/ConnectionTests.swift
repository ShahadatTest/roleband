import Foundation
import Testing
@testable import LauncherCore

private let instance = "0123456789abcdef01234567"
private func registration(_ origin: String = "http://127.0.0.1:58221", product: String = "roleband") throws -> Installation {
    let data = try JSONSerialization.data(withJSONObject: ["product": product, "instance": instance, "api_origin": origin, "version": "0.1.0", "format": 1])
    return try JSONDecoder().decode(Installation.self, from: data)
}
private func fixture() throws -> [String: Any] {
    let path = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
        .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        .appendingPathComponent("launcher/contracts/status-cases.json")
    return try JSONSerialization.jsonObject(with: Data(contentsOf: path)) as! [String: Any]
}
private func wire(_ presentation: [String: Any], changes: [String: Any] = [:]) throws -> Data {
    let identity: [String: Any] = ["product": "roleband", "instance": instance, "api_origin": "http://127.0.0.1:58221", "version": "0.1.0", "format": 1, "status": presentation]
    return try JSONSerialization.data(withJSONObject: ["db": "ok", "launcher": identity.merging(changes) { _, right in right }])
}

@Test func sharedProjectionCasesPreserveLabelsAttentionAndClocks() throws {
    for value in try fixture()["cases"] as! [[String: Any]] {
        let status = try StatusClient.decode(wire(value["wire"] as! [String: Any]), status: 200, installation: registration())
        let expected = value["native"] as! [String: String]
        #expect(status.presentation.titleKey == expected["title"], "\(value["name"]!)")
        #expect(status.presentation.symbol == expected["symbol"], "\(value["name"]!)")
        if status.presentation.activity == .idle { #expect(status.presentation.activitySince == nil) }
        #expect(status.presentation.reasonKey == expected["reason"], "\(value["name"]!)")
    }
}

@Test func valuesFromANewerEngineDecodeAsUnknownInsteadOfFailing() throws {
    var presentation = try #require((try fixture()["cases"] as! [[String: Any]]).first)["wire"] as! [String: Any]
    presentation["activity"] = "rebuilding_index"
    presentation["hold"] = ["kind": "advisory", "reason": "new_engine_reason"]
    let status = try StatusClient.decode(wire(presentation), status: 200, installation: registration())
    #expect(status.presentation.activity == .unknown)
    #expect(status.presentation.hold?.kind == .unknown)
    #expect(!status.presentation.isActive)
    #expect(status.presentation.titleKey == "waiting")
    #expect(status.presentation.symbol == "pause.circle")
    #expect(status.presentation.reasonKey == "reason-other")
}

private func scanCases() throws -> [[String: Any]] {
    let path = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
        .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        .appendingPathComponent("launcher/contracts/scan-cases.json")
    return (try JSONSerialization.jsonObject(with: Data(contentsOf: path)) as! [String: Any])["cases"] as! [[String: Any]]
}

@Test func theScanPictureFromTheEngineDecodesAndAnUnreadableOneLeavesTheStatusUsable() throws {
    let presentation = try #require((try fixture()["cases"] as! [[String: Any]]).first)["wire"] as! [String: Any]
    let cases = try scanCases()
    let live = try StatusClient.decode(wire(presentation, changes: ["scan": cases[0]["wire"]!]), status: 200, installation: registration())
    let picture = try #require(live.scan)
    #expect(picture.live && picture.percent == 38 && picture.companiesTotal == 42)
    #expect(picture.inFlight == [ScanPicture.Company(name: "Nvidia", since: "2026-10-31T11:57:32Z"),
                                 ScanPicture.Company(name: "Apple", since: "2026-10-31T11:57:47Z")])
    #expect(picture.rolesPending == 214 && picture.rolesRecorded == 498 && picture.nextScanAt == "2026-10-31T15:00:00Z")
    #expect(picture.stage == .collecting && !picture.everyCompanyRead)
    let finishing = try #require(cases.first { $0["name"] as? String == "finishing_after_every_company_is_read" })
    let closing = try #require(try StatusClient.decode(wire(presentation, changes: ["scan": finishing["wire"]!]),
                                                       status: 200, installation: registration()).scan)
    #expect(closing.stage == .finishing && closing.everyCompanyRead && closing.inFlight.isEmpty && closing.rolesRecorded == 59)
    // A stage this app does not know leaves the picture usable.
    var newer = cases[0]["wire"] as! [String: Any]
    newer["phase"] = "tidying"
    let unknown = try #require(try StatusClient.decode(wire(presentation, changes: ["scan": newer]), status: 200, installation: registration()).scan)
    #expect(unknown.stage == nil && unknown.live && unknown.inFlight.count == 2)
    let stopped = try #require(try StatusClient.decode(wire(presentation, changes: ["scan": cases[1]["wire"]!]),
                                                       status: 200, installation: registration()).scan)
    #expect(!stopped.live && stopped.lastStopped && stopped.lastCompanies == 16 && stopped.lastPostings == 301)

    let older = try StatusClient.decode(wire(presentation), status: 200, installation: registration())
    #expect(older.scan == nil)
    var broken = cases[0]["wire"] as! [String: Any]
    broken["in_flight"] = "Nvidia"
    let unreadable = try StatusClient.decode(wire(presentation, changes: ["scan": broken]), status: 200, installation: registration())
    #expect(unreadable.scan == nil && unreadable.presentation.titleKey == older.presentation.titleKey)
}

@Test func theScanPictureSaysHowScansStartAndAnEngineThatDoesNotSaySendsNoSchedule() throws {
    let presentation = try #require((try fixture()["cases"] as! [[String: Any]]).first)["wire"] as! [String: Any]
    func schedule(_ scan: [String: Any]) throws -> ScheduleState? {
        try StatusClient.decode(wire(presentation, changes: ["scan": scan]), status: 200, installation: registration()).scan?.schedule
    }
    let cases = Dictionary(uniqueKeysWithValues: try scanCases().map { ($0["name"] as! String, $0["wire"] as! [String: Any]) })
    let plan = try #require(try schedule(cases["scanning"]!))
    #expect(plan.enabled && plan.pausable && plan.pausedUntil == nil)
    let off = try #require(try schedule(cases["stopped_by_the_person"]!))
    #expect(!off.enabled && !off.pausable)
    let timers = try #require(try schedule(cases["never_scanned"]!))
    #expect(timers.enabled && !timers.pausable)
    let paused = try #require(try schedule(cases["paused_by_the_person"]!))
    let until = try #require(paused.pausedUntil)
    #expect(paused.pausable && paused.isPaused(at: until.addingTimeInterval(-1)) && !paused.isPaused(at: until))

    var older = cases["scanning"]!
    older["scheduling"] = nil
    older["paused_until"] = nil
    #expect(try schedule(older) == nil)
    for change: [String: Any] in [["scheduling": "weekly"], ["paused_until": "soon"]] {
        #expect(try schedule(cases["scanning"]!.merging(change) { $1 }) == nil)
    }
}

@Test func aNextScanAtOrBeforeNowIsDueRatherThanATimeToShow() throws {
    let presentation = try #require((try fixture()["cases"] as! [[String: Any]]).first)["wire"] as! [String: Any]
    let scan = try #require(try scanCases().first)["wire"] as! [String: Any]
    let picture = try #require(try StatusClient.decode(wire(presentation, changes: ["scan": scan]), status: 200,
                                                       installation: registration()).scan)
    let next = try #require(ISO8601DateFormatter().date(from: "2026-10-31T15:00:00Z"))
    #expect(picture.nextScan(after: next.addingTimeInterval(-60)) == next)
    #expect(picture.nextScan(after: next) == nil)
    #expect(picture.nextScan(after: next.addingTimeInterval(3_600)) == nil)
    let unreadable = try #require(try StatusClient.decode(wire(presentation, changes: ["scan": scan.merging(["next_scan_at": "later"]) { $1 }]),
                                                          status: 200, installation: registration()).scan)
    #expect(unreadable.nextScan(after: next.addingTimeInterval(-60)) == nil)
}

@Test func identityMismatchAndUnsafeTargetsNeverVerify() throws {
    let value = try fixture()["cases"] as! [[String: Any]]
    let presentation = value[0]["wire"] as! [String: Any]
    for change: [String: Any] in [["product": "another-app"], ["instance": "other"], ["format": 2], ["api_origin": "http://127.0.0.1:8010"]] {
        #expect(throws: ConnectionProblem.identityMismatch) {
            try StatusClient.decode(wire(presentation, changes: change), status: 200, installation: registration())
        }
    }
    for origin in ["https://127.0.0.1:58221", "http://example.com:58221", "http://user:secret@localhost:58221", "http://127.0.0.1:58221/path", "http://127.0.0.1:58221?query=yes"] {
        #expect(throws: ConnectionProblem.invalidInstallation) { try registration(origin).target() }
    }
    #expect(throws: ConnectionProblem.invalidInstallation) {
        try StatusClient.decode(wire(presentation), status: 200, installation: registration(product: "other"))
    }
}

@Test func legacyErrorsAndOversizedRepliesFailClosed() throws {
    let install = try registration()
    #expect(throws: ConnectionProblem.upgradeRequired) {
        try StatusClient.decode(Data(#"{"db":"ok","running":false}"#.utf8), status: 200, installation: install)
    }
    for code in [302, 500, 503] {
        #expect(throws: ConnectionProblem.invalidResponse) {
            try StatusClient.decode(Data(), status: code, installation: install)
        }
    }
    for data in [Data("unrelated response".utf8), Data(repeating: 0, count: 4194305)] {
        #expect(throws: ConnectionProblem.invalidResponse) { try StatusClient.decode(data, status: 200, installation: install) }
    }
}

@Test func aStatusCarryingTheSchedulersLongListsIsReadAndOnlyAnOversizedOneIsRefused() async throws {
    let large = try LocalEngineFixture("status-large")
    let status = try await StatusClient.read(large.installation)
    #expect(status.presentation.titleKey == "ready")
    let oversized = try LocalEngineFixture("status-oversized")
    await #expect(throws: ConnectionProblem.invalidResponse) { try await StatusClient.read(oversized.installation) }
}

@Test func aStatusWithoutTheFieldsTheAppNeverReadsStillReads() throws {
    let full = try #require((try fixture()["cases"] as! [[String: Any]]).first)["wire"] as! [String: Any]
    var presentation = full
    presentation["observed_at"] = nil
    presentation["model"] = nil
    let status = try StatusClient.decode(wire(presentation), status: 200, installation: registration())
    let expected = try StatusClient.decode(wire(full), status: 200, installation: registration())
    #expect(status.presentation.titleKey == expected.presentation.titleKey)
    #expect(status.presentation.symbol == expected.presentation.symbol)
}

@Test func registrationRequiresPrivateOwnedRegularBoundedJSON() throws {
    let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    try FileManager.default.createDirectory(at: root, withIntermediateDirectories: false)
    defer { try? FileManager.default.removeItem(at: root) }
    let path = root.appendingPathComponent("installation.json")
    #expect(throws: ConnectionProblem.missingInstallation) { try Installation.load(path) }
    try JSONEncoder().encode(registration()).write(to: path)
    try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: path.path)
    #expect(try Installation.load(path) == registration())
    try FileManager.default.setAttributes([.posixPermissions: 0o644], ofItemAtPath: path.path)
    #expect(throws: ConnectionProblem.invalidInstallation) { try Installation.load(path) }
    try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: path.path)
    try Data(repeating: 0, count: 8193).write(to: path)
    #expect(throws: ConnectionProblem.invalidInstallation) { try Installation.load(path) }
    let link = root.appendingPathComponent("alias.json")
    try FileManager.default.createSymbolicLink(at: link, withDestinationURL: path)
    #expect(throws: ConnectionProblem.invalidInstallation) { try Installation.load(link) }
}

@Test func setupCannotAdvanceWithoutAConnectionAndLoginRemainsOptional() {
    #expect(SetupStep.welcome.next(connected: false, installed: false) == .installation)
    #expect(SetupStep.welcome.next(connected: false, installed: true) == .connection)
    #expect(SetupStep.installation.next(connected: false, installed: false) == .installation)
    #expect(SetupStep.installation.next(connected: false, installed: true) == .connection)
    #expect(SetupStep.connection.next(connected: false) == .connection)
    #expect(SetupStep.connection.next(connected: true) == .login)
    #expect(SetupStep.login.next(connected: true) == .done)
    #expect(SetupStep.done.next(connected: true) == .done)
    #expect(SetupStep.welcome.previous(installed: true) == .welcome)
}

@Test func theAppsLanguageKeepsThePersonsRegionAndClock() throws {
    let at = try #require(ISO8601DateFormatter().date(from: "2026-11-01T14:30:00Z"))
    func shown(_ language: String, _ regional: Locale) -> String {
        var style = Date.FormatStyle.dateTime.month(.abbreviated).day().hour().minute()
            .locale(LauncherCopy(language: language, regional: regional).locale)
        style.timeZone = TimeZone(identifier: "UTC")!
        return at.formatted(style)
    }
    let british = Locale(identifier: "en_GB")
    #expect(shown("en", british).hasPrefix("1 Nov") && shown("en", british).contains("14:30"))
    #expect(shown("es", british).contains("nov") && shown("es", british).contains("14:30"))
    var clock = Locale.Components(locale: Locale(identifier: "en_US"))
    clock.hourCycle = .zeroToTwentyThree
    #expect(shown("en", Locale(components: clock)).contains("14:30"))
    #expect(shown("en", Locale(identifier: "en_US")).contains("2:30"))
    #expect(LauncherCopy(language: "zh-Hans", regional: british).locale.language.languageCode == "zh")
    #expect(LauncherCopy(language: "zh-Hans", regional: british).locale.language.script == .hanSimplified)
}

/// The live picture parses about ten stamps a frame at 30 frames a second; building a parser per
/// stamp costs about a quarter of a millisecond each.
@Test func engineStampsParseInEveryShapeTheEngineWritesWithoutBuildingAParserEachTime() throws {
    #expect(Stamp.date("2026-10-31T11:57:32Z")?.timeIntervalSince1970 == 1_793_447_852)
    #expect(Stamp.date("2026-10-31T13:57:32+02:00")?.timeIntervalSince1970 == 1_793_447_852)
    #expect(Stamp.date("2026-10-31T11:57:32+00:00")?.timeIntervalSince1970 == 1_793_447_852)
    let fractional = try #require(Stamp.date("2026-10-31T11:57:32.123456Z")).timeIntervalSince1970
    #expect(abs(fractional - 1_793_447_852.123) < 0.001)
    for refused in ["2026-10-31T11:57:32", "2026-10-31", "2026-10-31 11:57:32Z", "", "garbage"] { #expect(Stamp.date(refused) == nil) }
    #expect(Stamp.date(nil) == nil)
    let start = ContinuousClock.now
    for index in 0..<3000 { _ = Stamp.date(index % 2 == 0 ? "2026-10-31T11:57:32Z" : "2026-10-31T11:57:32.123456Z") }
    #expect(ContinuousClock.now - start < .milliseconds(150))
}

@Test func aKeyMissingFromTheCatalogShowsAsItselfNeverAsAnotherMessage() {
    for language in ["en", "es", "zh-Hans"] {
        let copy = LauncherCopy(language: language)
        #expect(copy.text("no-such-message") == "no-such-message")
        #expect(copy.text("no-such-message", ["time": "6:00"]) == "no-such-message")
    }
}

/// Every kebab-case literal in the app's sources is a message, apart from the names below. A new
/// literal that is not copy (a file, an asset, a render argument) belongs in `notCopy`.
@Test func everyMessageTheAppNamesIsInEveryLanguage() throws {
    let notCopy: Set = ["failed-check", "failed-db", "failed-download", "failed-restart", "failed-space", "hand-off", "login-state",
                        "owned-engine", "read-first", "recovery-failed", "restore-db", "roleband-mark-bar-template",
                        "roleband-mark-master-template", "roleband-mark-mid-template", "roleband-menubar-18",
                        "rolled-back", "self-signed"]
    let sources = URL(fileURLWithPath: #filePath).deletingLastPathComponent().appendingPathComponent("../../Sources").standardized
    let files = try #require(FileManager.default.enumerator(at: sources, includingPropertiesForKeys: nil))
        .compactMap { $0 as? URL }.filter { $0.pathExtension == "swift" }
    let literal = try NSRegularExpression(pattern: #""([a-z][a-z0-9]*(?:-[a-z0-9]+)+)""#)
    var named: Set<String> = []
    for file in files {
        let text = try String(contentsOf: file, encoding: .utf8)
        for match in literal.matches(in: text, range: NSRange(text.startIndex..., in: text)) {
            named.insert(String(text[Range(match.range(at: 1), in: text)!]))
        }
    }
    // Control messages are built from a prefix and an outcome.
    for prefix in ["scan", "pause", "engine"] {
        for outcome in ["-state-changed", "-refused", "-unconfirmed"] { named.insert(prefix + outcome) }
    }
    #expect(files.count > 20 && named.count > 200)
    for language in ["en", "es", "zh-Hans"] {
        let catalog = try #require(LauncherCopy.load(language, from: .module))
        let missing = named.subtracting(notCopy).filter { catalog[$0] == nil }.sorted()
        #expect(missing.isEmpty, "\(language) has no message for \(missing)")
    }
    #expect(notCopy.subtracting(named).isEmpty, "notCopy names a literal the sources no longer use")
}

@Test func pollingAndNativeCopyAreBounded() {
    #expect(PollPolicy.delay(panelOpen: true, active: true, failures: 0) == 3)
    #expect(PollPolicy.delay(panelOpen: false, active: true, failures: 0) == 15)
    #expect(PollPolicy.delay(panelOpen: true, active: false, failures: 0) == 60)
    #expect(PollPolicy.delay(panelOpen: true, active: false, failures: 50) == 300)
    #expect(LauncherCopy(language: "es").text("continue") == "Continuar")
    #expect(LauncherCopy(language: "zh-Hans").text("continue") == "继续")
    #expect(LauncherCopy(language: "en").text("continue") == "Continue")
}

@Test func assembledAppReadsCopyFromItsResourcesFolderOnly() throws {
    let root = FileManager.default.temporaryDirectory.appendingPathComponent("copy-\(UUID().uuidString)")
    defer { try? FileManager.default.removeItem(at: root) }
    func app(_ name: String, bundleIn folder: String) throws -> Bundle {
        let app = root.appendingPathComponent("\(name).app")
        let resources = app.appendingPathComponent(folder).appendingPathComponent("\(LauncherCopy.resourceBundleName).bundle")
        try FileManager.default.createDirectory(at: resources, withIntermediateDirectories: true)
        try Data(#"{"continue": "Seguir"}"#.utf8).write(to: resources.appendingPathComponent("copy.es.json"))
        try FileManager.default.createDirectory(at: app.appendingPathComponent("Contents/Resources"), withIntermediateDirectories: true)
        return try #require(Bundle(url: app))
    }
    let installed = try app("Installed", bundleIn: "Contents/Resources")
    #expect(LauncherCopy.load("es", from: LauncherCopy.resources(in: installed)) == ["continue": "Seguir"])
    // Where the native build system's generated accessor looks: beside Contents, at the app root.
    let misplaced = try app("Misplaced", bundleIn: "")
    #expect(LauncherCopy.resources(in: misplaced) == nil)
    #expect(!LauncherCopy.appCarriesCatalogs(installed))
    #expect(LauncherCopy.load("es", from: nil) == nil)
}
