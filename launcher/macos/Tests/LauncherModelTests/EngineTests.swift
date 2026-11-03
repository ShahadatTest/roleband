import CryptoKit
import Darwin
import Foundation
import Testing
@testable import LauncherCore
@testable import RoleBandLauncher

private actor EngineTransport {
    let output: CommandOutput
    var commands: [[String]] = []
    var connected = false
    init(_ output: CommandOutput) { self.output = output }
    func read(_ installation: Installation) throws -> VerifiedStatus {
        guard connected else { throw URLError(.cannotConnectToHost) }
        var identity = try JSONSerialization.jsonObject(with: JSONEncoder().encode(installation)) as! [String: Any]
        identity["status"] = ["observed_at": "2026-10-28T12:00:00Z", "activity": "idle", "attention": [], "model": "ready"]
        return try StatusClient.decode(JSONSerialization.data(withJSONObject: ["db": "ok", "launcher": identity]),
                                       status: 200, installation: installation)
    }
    func command(_ args: [String]) -> CommandOutput {
        commands.append(args)
        if args.first == "print" { return output }
        return CommandOutput(text: "", exitCode: 1)
    }
    func answer() { connected = true }
}

@MainActor
private func withEngineModel(state: String, body: (LauncherModel, EngineTransport) async throws -> Void) async throws {
    let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    defer { try? FileManager.default.removeItem(at: root) }
    let home = root.appendingPathComponent("home")
    let checkout = root.appendingPathComponent("checkout")
    let registration = home.appendingPathComponent(".roleband/launcher/installation.json")
    let plist = home.appendingPathComponent("Library/LaunchAgents/com.roleband.plist")
    let program = checkout.appendingPathComponent("deploy/roleband")
    let backend = checkout.appendingPathComponent("backend")
    for folder in [registration.deletingLastPathComponent(), plist.deletingLastPathComponent(), program.deletingLastPathComponent(), backend] {
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
    }
    try Data("#!/bin/sh\nexit 0\n".utf8).write(to: program)
    try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: program.path)
    let hash = SHA256.hash(data: Data(checkout.resolvingSymlinksInPath().path.utf8)).map { String(format: "%02x", $0) }.joined()
    try JSONSerialization.data(withJSONObject: ["product": "roleband", "format": 1, "version": "0.1.0", "instance": String(hash.prefix(24)), "api_origin": "http://127.0.0.1:58271"]).write(to: registration)
    try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: registration.path)
    try PropertyListSerialization.data(fromPropertyList: ["Label": "com.roleband", "ProgramArguments": [program.path], "WorkingDirectory": backend.path], format: .xml, options: 0).write(to: plist)
    try FileManager.default.setAttributes([.posixPermissions: 0o644], ofItemAtPath: plist.path)
    let output = CommandOutput(text: """
    gui/\(getuid())/com.roleband = {
    \tactive count = \(state == "running" ? 1 : 0)
    \tpath = \(plist.path)
    \ttype = LaunchAgent
    \tstate = \(state)
    \tprogram = \(program.path)
    \targuments = {
    \t\t\(program.path)
    \t}
    \tworking directory = \(backend.path)
    }
    """, exitCode: 0)
    let transport = EngineTransport(output)
    let engine = EngineClient(command: { await transport.command($0) }, readStatus: { try await transport.read($0) })
    let model = LauncherModel(registration: registration, mode: .attach, readStatus: { try await transport.read($0) }, engine: engine, homeURL: home)
    defer { model.stop() }
    try await body(model, transport)
}

@MainActor
@Test func aStoppedSourceEngineOffersLogsWithoutAStartOrRestartControl() async throws {
    try await withEngineModel(state: "not running") { model, transport in
        await model.refreshAndWait()
        #expect(!model.mayStartEngine && !model.mayRestartEngine && model.engineActionKey == nil)
        #expect(model.engineLogDirectory != nil && model.engineState == .stopped)
        #expect(model.titleKey == "attached-stopped-title")
        await model.startEngineAndWait()
        #expect(await transport.commands.allSatisfy { $0.first == "print" })
        #expect(!model.shouldShowSetupAtLaunch)
        await transport.answer()
        await model.refreshAndWait()
        #expect(model.verified != nil && !model.mayStartEngine && model.engineState == nil)
        #expect(await model.shutdown())
        #expect(await transport.commands.allSatisfy { $0.first == "print" })
    }
}

@MainActor
@Test(arguments: ["running", "waiting"])
func anHTTPTimeoutCannotEnableStartWhenTheServiceIsRunningOrUnknown(state: String) async throws {
    try await withEngineModel(state: state) { model, transport in
        await model.refreshAndWait()
        #expect(model.problem == .unavailable && !model.mayStartEngine)
        await model.startEngineAndWait()
        #expect(await transport.commands.allSatisfy { $0.first == "print" })
        #expect(model.controlMessage == nil)
    }
}
