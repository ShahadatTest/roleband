import CryptoKit
import Darwin
import Foundation
import Testing
@testable import LauncherCore

struct EngineFixture: Sendable {
    let root: URL
    let home: URL
    let checkout: URL
    let registration: URL
    let plist: URL
    let installation: Installation
    static func make() throws -> Self {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let home = root.appendingPathComponent("home")
        let checkout = root.appendingPathComponent("RoleBand checkout")
        let registration = home.appendingPathComponent(".roleband/launcher/installation.json")
        let plist = home.appendingPathComponent("Library/LaunchAgents/com.roleband.plist")
        for folder in [registration.deletingLastPathComponent(), plist.deletingLastPathComponent(), checkout.appendingPathComponent("deploy"), checkout.appendingPathComponent("backend")] {
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        }
        let program = checkout.appendingPathComponent("deploy/roleband")
        try Data("#!/bin/sh\nexit 0\n".utf8).write(to: program)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: program.path)
        let identity: [String: Any] = ["product": "roleband", "format": 1, "version": "0.1.0", "api_origin": "http://127.0.0.1:58261",
                                      "instance": String(SHA256.hash(data: Data(checkout.resolvingSymlinksInPath().path.utf8)).map { String(format: "%02x", $0) }.joined().prefix(24))]
        let data = try JSONSerialization.data(withJSONObject: identity)
        try data.write(to: registration)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: registration.path)
        let item: [String: Any] = ["Label": "com.roleband", "ProgramArguments": [program.path], "WorkingDirectory": checkout.appendingPathComponent("backend").path]
        try PropertyListSerialization.data(fromPropertyList: item, format: .xml, options: 0).write(to: plist)
        try FileManager.default.setAttributes([.posixPermissions: 0o644], ofItemAtPath: plist.path)
        return Self(root: root, home: home, checkout: checkout, registration: registration, plist: plist,
                    installation: try JSONDecoder().decode(Installation.self, from: data))
    }
    func output(_ state: String = "not running", pid: Int? = nil) -> CommandOutput {
        CommandOutput(text: """
        gui/\(getuid())/com.roleband = {
        \tactive count = \(state == "running" ? 1 : 0)
        \tpath = \(plist.path)
        \ttype = LaunchAgent
        \tstate = \(state)
        \tprogram = \(checkout.appendingPathComponent("deploy/roleband").path)
        \targuments = {
        \t\t\(checkout.appendingPathComponent("deploy/roleband").path)
        \t}
        \tworking directory = \(checkout.appendingPathComponent("backend").path)
        \(pid.map { "\tpid = \($0)\n" } ?? "")}
        """, exitCode: 0)
    }
    func remove() { try? FileManager.default.removeItem(at: root) }
}

private actor CommandLog {
    var calls: [[String]] = []
    let output: CommandOutput
    init(_ output: CommandOutput) { self.output = output }
    func run(_ args: [String]) -> CommandOutput {
        calls.append(args)
        return args.first == "print" ? output : CommandOutput(text: "", exitCode: 0)
    }
}

@Test func onlyAMatchedStoppedServiceCanBeStartedWithoutAnyForceFlag() async throws {
    let fixture = try EngineFixture.make()
    defer { fixture.remove() }
    let log = CommandLog(fixture.output())
    let engine = EngineClient(command: { await log.run($0) }, readStatus: { _ in throw URLError(.cannotConnectToHost) })
    #expect(await engine.inspect(fixture.installation, registration: fixture.registration, home: fixture.home) == .stopped)
    try await engine.start(fixture.installation, registration: fixture.registration, home: fixture.home)
    #expect(await log.calls == [["print", "gui/\(getuid())/com.roleband"], ["print", "gui/\(getuid())/com.roleband"], ["kickstart", "gui/\(getuid())/com.roleband"]])
}

@Test(arguments: ["running", "pid", "missing", "unmatched", "nested", "duplicate", "unknown"])
func staleMissingAmbiguousOrMismatchedServiceEvidenceNeverEnablesStart(mode: String) async throws {
    let fixture = try EngineFixture.make()
    defer { fixture.remove() }
    var output = fixture.output()
    switch mode {
    case "running": output = fixture.output("running", pid: 123)
    case "pid": output = fixture.output(pid: 123)
    case "missing": output = CommandOutput(text: "Could not find service", exitCode: 113)
    case "unmatched": output = CommandOutput(text: output.text.replacingOccurrences(of: "\tprogram = ", with: "\tprogram = /other"), exitCode: 0)
    case "nested": output = CommandOutput(text: output.text.replacingOccurrences(of: "\tstate = not running", with: "\tenvironment = {\n\t\tstate = not running\n\t}"), exitCode: 0)
    case "duplicate": output = CommandOutput(text: output.text.replacingOccurrences(of: "\tstate = not running", with: "\tstate = not running\n\tstate = running"), exitCode: 0)
    default: output = fixture.output("waiting")
    }
    let log = CommandLog(output)
    let engine = EngineClient(command: { await log.run($0) }, readStatus: { _ in throw URLError(.cannotConnectToHost) })
    #expect(await engine.inspect(fixture.installation, registration: fixture.registration, home: fixture.home) != .stopped)
    await #expect(throws: (any Error).self) {
        try await engine.start(fixture.installation, registration: fixture.registration, home: fixture.home)
    }
    // Inspect printed once and start once more: start read the service before it refused.
    #expect(await log.calls.count == 2)
    #expect(await log.calls.allSatisfy { $0.first == "print" })
}

@Test(arguments: ["override", "writable", "wrong-instance", "replacement", "changed-plist"])
func privateRegistrationAndDiskConfigurationAreRecheckedBeforeEveryStart(mode: String) async throws {
    let fixture = try EngineFixture.make()
    defer { fixture.remove() }
    if mode == "writable" { try FileManager.default.setAttributes([.posixPermissions: 0o666], ofItemAtPath: fixture.plist.path) }
    if mode == "wrong-instance" {
        var registration = try JSONSerialization.jsonObject(with: Data(contentsOf: fixture.registration)) as! [String: Any]
        registration["instance"] = "0123456789abcdef01234567"
        try JSONSerialization.data(withJSONObject: registration).write(to: fixture.registration)
    }
    let log = CommandLog(fixture.output())
    let engine = EngineClient(command: { args in
        if mode == "replacement" { try Data("{}".utf8).write(to: fixture.registration) }
        if mode == "changed-plist" { try Data("{}".utf8).write(to: fixture.plist) }
        return await log.run(args)
    }, readStatus: { _ in throw URLError(.cannotConnectToHost) })
    let candidate = mode == "wrong-instance" ? try Installation.load(fixture.registration) : fixture.installation
    await #expect(throws: (any Error).self) {
        try await engine.start(candidate, registration: fixture.registration,
                               home: mode == "override" ? fixture.root : fixture.home)
    }
    if mode == "replacement" || mode == "changed-plist" { #expect(await !log.calls.isEmpty) }
    #expect(await log.calls.allSatisfy { $0.first == "print" })
}

@Test(arguments: [ConnectionProblem.identityMismatch, .invalidResponse, .upgradeRequired])
func anAnsweringButIncorrectHTTPServiceIsNeverAReasonToStartAnEngine(problem: ConnectionProblem) async throws {
    let fixture = try EngineFixture.make()
    defer { fixture.remove() }
    let log = CommandLog(fixture.output())
    let engine = EngineClient(command: { await log.run($0) }, readStatus: { _ in throw problem })
    await #expect(throws: problem) { try await engine.start(fixture.installation, registration: fixture.registration, home: fixture.home) }
    #expect(await log.calls.isEmpty)
}

@Test func commandExecutionBoundsTimeAndOutputAndPreservesArgumentBoundaries() async throws {
    let result = try await CommandRunner.run(executable: URL(fileURLWithPath: "/usr/bin/printf"), arguments: ["%s", "a space; $(literal)"])
    #expect(result.text == "a space; $(literal)" && result.exitCode == 0)
    await #expect(throws: ConnectionProblem.unavailable) {
        try await CommandRunner.run(executable: URL(fileURLWithPath: "/bin/sleep"), arguments: ["10"], timeout: 0.02)
    }
    await #expect(throws: ConnectionProblem.invalidResponse) {
        try await CommandRunner.run(executable: URL(fileURLWithPath: "/usr/bin/printf"), arguments: ["%s", String(repeating: "x", count: 65537)])
    }
}

@Test func waitingCommandsLeaveSwiftsSharedThreadsFree() async throws {
    // Four times as many waits as the shared pool has threads. Blocking waits would hold
    // every thread and take four rounds (12 s); suspended waits all end after one (3 s).
    // The limit leaves room for other tests holding threads briefly in a parallel run.
    let waits = ProcessInfo.processInfo.activeProcessorCount * 4
    let clock = ContinuousClock()
    let began = clock.now
    try await withThrowingTaskGroup(of: Int32.self) { group in
        for _ in 0..<waits {
            group.addTask { try await CommandRunner.run(executable: URL(fileURLWithPath: "/bin/sleep"), arguments: ["3"], timeout: 30).exitCode }
        }
        for try await code in group { #expect(code == 0) }
    }
    #expect(clock.now - began < .seconds(9))
}

@Test func anEngineThatAnswersBeforeTheClickNeverReceivesAStartCommand() async throws {
    let fixture = try EngineFixture.make()
    defer { fixture.remove() }
    let log = CommandLog(fixture.output())
    let engine = EngineClient(command: { await log.run($0) }, readStatus: { installation in
        var identity = try JSONSerialization.jsonObject(with: JSONEncoder().encode(installation)) as! [String: Any]
        identity["status"] = ["observed_at": "2026-10-28T12:00:00Z", "activity": "idle", "attention": [], "model": "ready"]
        return try StatusClient.decode(JSONSerialization.data(withJSONObject: ["db": "ok", "launcher": identity]),
                                       status: 200, installation: installation)
    })
    await #expect(throws: ControlProblem.stateChanged) {
        try await engine.start(fixture.installation, registration: fixture.registration, home: fixture.home)
    }
    #expect(await log.calls.isEmpty)
}

@Test func diagnosticLogsComeOnlyFromTheValidatedRegisteredCheckout() throws {
    let fixture = try EngineFixture.make()
    defer { fixture.remove() }
    let logs = fixture.checkout.appendingPathComponent("data/logs")
    try FileManager.default.createDirectory(at: logs, withIntermediateDirectories: true)
    let actual = try #require(EngineClient().logDirectory(fixture.installation, registration: fixture.registration, home: fixture.home))
    #expect(actual.resolvingSymlinksInPath().path == logs.resolvingSymlinksInPath().path)
    #expect(EngineClient().logDirectory(fixture.installation, registration: fixture.registration, home: fixture.root) == nil)
}
