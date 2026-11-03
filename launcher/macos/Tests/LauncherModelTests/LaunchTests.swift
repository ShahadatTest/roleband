import Combine
import Darwin
import Foundation
import Testing
@testable import LauncherCore
@testable import RoleBandLauncher

private struct LaunchFixture {
    let root = FileManager.default.temporaryDirectory.appendingPathComponent("launch \(UUID().uuidString)")
    var home: URL { root.appendingPathComponent("home") }
    var app: URL { home.appendingPathComponent("Applications/RoleBand.app") }
    var resources: URL { app.appendingPathComponent("Contents/Resources") }

    init() throws {
        try FileManager.default.createDirectory(at: resources, withIntermediateDirectories: true)
        try PropertyListSerialization.data(fromPropertyList: [
            "CFBundleIdentifier": "com.roleband.launcher", "CFBundlePackageType": "APPL",
            "RoleBandVersion": "0.1.0", "RoleBandPackagedEngine": true,
        ], format: .xml, options: 0).write(to: app.appendingPathComponent("Contents/Info.plist"))
    }
    func put(_ content: String, at path: URL) throws {
        try FileManager.default.createDirectory(at: path.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data(content.utf8).write(to: path)
    }
    func files() throws -> [String: Data] {
        let entries = try #require(FileManager.default.enumerator(at: root, includingPropertiesForKeys: [.isRegularFileKey]))
        var result: [String: Data] = [:]
        for case let url as URL in entries {
            let regular = try url.resourceValues(forKeys: [.isRegularFileKey]).isRegularFile == true
            result[String(url.path.dropFirst(root.path.count))] = regular ? try Data(contentsOf: url) : Data()
        }
        return result
    }
    func remove() {
        let layout = HomeLayout(home)
        let record = layout.data.appendingPathComponent("launcher/owned-engine.json")
        if let bytes = try? Data(contentsOf: record),
           let saved = try? JSONDecoder().decode([String: String].self, from: bytes)["token"],
           let remaining = try? OwnedProcess.marked(saved) {
            for process in remaining where !process.isPostgres { try? process.signal(SIGKILL, group: true) }
        }
        if let pid = LaunchMode.runningServer(layout.database), let server = OwnedProcess.read(pid),
           server.isPostgres, server.matchesDatabase(layout.database),
           let path = LaunchMode.executable(pid), LaunchMode.isInsideApp(path) {
            try? server.signal(SIGINT)
            let deadline = ProcessInfo.processInfo.systemUptime + 2
            while server.isAlive && ProcessInfo.processInfo.systemUptime < deadline { usleep(1000) }
            if server.isAlive { try? server.signal(SIGKILL) }
        }
        try? FileManager.default.removeItem(at: root)
    }
}

private func launchReply(_ installation: Installation) throws -> VerifiedStatus {
    var identity = try JSONSerialization.jsonObject(with: JSONEncoder().encode(installation)) as! [String: Any]
    identity["status"] = ["observed_at": "2026-10-30T12:00:00Z", "activity": "idle", "attention": [], "model": "ready"]
    return try StatusClient.decode(JSONSerialization.data(withJSONObject: ["db": "ok", "launcher": identity]),
                                   status: 200, installation: installation)
}

@MainActor
private func launchDependencies(_ fixture: LaunchFixture, preferences: UserDefaults,
                                host: OwnedEngineService? = nil) throws -> LauncherDependencies {
    let bundle = try #require(Bundle(url: fixture.app))
    let installation = try Installation.owned(bundle: bundle, port: 58319)
    return LauncherDependencies(ownedEngine: host, registration: HomeLayout(fixture.home).registration,
        installation: .fixed(installation), readStatus: launchReply,
        openBrowser: { _ in true }, preferences: preferences,
        loginService: LoginService(state: { .off }, setEnabled: { _ in Issue.record("Unexpected login registration") }, openSettings: {}),
        bundleURL: fixture.app, homeURL: fixture.home)
}

@MainActor
@Test(arguments: ["read-only", "unowned-database"])
func blockedLaunchesNeverCreateDependenciesOrChangeFiles(caseName: String) async throws {
    let fixture = try LaunchFixture()
    defer { fixture.remove() }
    let layout = HomeLayout(fixture.home)
    let bundle: URL
    let expected: LaunchMode
    if caseName == "read-only" {
        bundle = fixture.root.appendingPathComponent("Mounted/RoleBand.app")
        try fixture.put("read-only app", at: bundle.appendingPathComponent("Contents/MacOS/app"))
        try FileManager.default.setAttributes([.posixPermissions: 0o555], ofItemAtPath: bundle.path)
        expected = .moveToApplications
    } else {
        bundle = fixture.app
        try fixture.put("17\n", at: layout.database.appendingPathComponent("PG_VERSION"))
        try fixture.put("irreplaceable history", at: layout.database.appendingPathComponent("history"))
        expected = .databaseOwnedElsewhere
    }
    defer { try? FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: bundle.path) }
    let before = try fixture.files()
    var factories = 0
    let session = LauncherMain.session(bundle: bundle, home: fixture.home) { _ in
        factories += 1
        preconditionFailure("A blocked launch must not construct live dependencies")
    }
    let mode = session.mode
    #expect(mode == expected)
    session.launch()
    #expect(await session.shutdown())
    #expect(session.model == nil && factories == 0)
    #expect(try fixture.files() == before)
    #expect(!FileManager.default.fileExists(atPath: layout.registration.path))
    #expect(!FileManager.default.fileExists(atPath: layout.launchAgent.path))
    let block = LaunchBlock(mode: mode, bundle: bundle, home: fixture.home)
    var selected: [URL] = []
    var opened: [URL] = []
    block.reveal(select: { selected.append($0) }, open: { opened.append($0) })
    #expect(selected == (caseName == "read-only" ? [bundle] : []))
    #expect(opened == [caseName == "read-only" ? URL(fileURLWithPath: "/Applications") : layout.data])
    #expect(try fixture.files() == before)
}

@MainActor
@Test func anUpdateThatStoppedShowsItsLogAndOnlyARecoverableOneOffersAnotherTry() throws {
    let fixture = try LaunchFixture()
    defer { fixture.remove() }
    let id = UUID()
    let log = HomeLayout(fixture.home).data.appendingPathComponent("logs/update-helper.log")
    for retry in [true, false] {
        let block = LaunchBlock(mode: .owned(leftover: nil), bundle: fixture.app, home: fixture.home,
                                update: .init(id: id, retry: retry))
        #expect(block.titleKey == "update-stopped-title" && !block.moving)
        var selected: [URL] = []
        var opened: [URL] = []
        block.reveal(select: { selected.append($0) }, open: { opened.append($0) })
        #expect(selected == [log] && opened.isEmpty)
        let copy = LauncherCopy(language: "en")
        for key in ["update-stopped-title", "update-stopped-body", "update-stopped-finder-help",
                    retry ? "update-stopped-retry-body" : "update-stopped-unreadable-body"] {
            #expect(copy.text(key) != copy.text("reason-other"), "\(key) is missing")
        }
    }
    let moving = LaunchBlock(mode: .moveToApplications, bundle: fixture.app, home: fixture.home)
    #expect(moving.titleKey == "installer-copy" && moving.update == nil)
}

private actor HostBoundary {
    var calls: [String] = []
    var current = OwnedEngineSnapshot(state: .stopped)
    var holdStart = false
    var holdStop = false
    var failStop = false
    var startWaiter: CheckedContinuation<Void, Never>?
    var stopWaiter: CheckedContinuation<Void, Never>?
    let entered: AsyncStream<String>.Continuation
    init(_ entered: AsyncStream<String>.Continuation) { self.entered = entered }
    func hold(start: Bool = false, stop: Bool = false) { holdStart = start; holdStop = stop }
    func start() async {
        calls.append("start")
        current.state = .starting
        entered.yield("start")
        if holdStart { await withCheckedContinuation { startWaiter = $0 } }
        current = OwnedEngineSnapshot(state: .running)
    }
    func releaseStart() { startWaiter?.resume(); startWaiter = nil }
    func releaseStop() { stopWaiter?.resume(); stopWaiter = nil }
    func restart() { calls.append("restart"); current = OwnedEngineSnapshot(state: .running) }
    func stop() async throws {
        calls.append("stop")
        entered.yield("stop")
        if holdStop { await withCheckedContinuation { stopWaiter = $0 } }
        if failStop { throw HostProblem.stopFailed }
        current = OwnedEngineSnapshot(state: .stopped)
    }
    func set(_ state: HostState, diagnostics: String = "", failStop: Bool = false) {
        current = OwnedEngineSnapshot(state: state, diagnostics: diagnostics)
        self.failStop = failStop
    }
    func snapshot() -> OwnedEngineSnapshot { current }
    nonisolated var service: OwnedEngineService {
        OwnedEngineService(start: { await self.start() }, restart: { await self.restart() },
                           stop: { try await self.stop() }, snapshot: { await self.snapshot() })
    }
}

@MainActor
@Test(arguments: ["registration", "launch-agent"])
func sourceEvidenceLaunchesOnlyTheAttachedModelAndQuitLeavesItsEngineAlone(evidence: String) async throws {
    let fixture = try LaunchFixture()
    defer { fixture.remove() }
    let layout = HomeLayout(fixture.home)
    try fixture.put("source install", at: evidence == "registration" ? layout.registration : layout.launchAgent)
    let preferences = UserDefaults.scratch("launch-test")
    let (_, signal) = AsyncStream<String>.makeStream()
    let host = HostBoundary(signal)
    let dependencies = try launchDependencies(fixture, preferences: preferences, host: host.service)
    let session = LauncherMain.session(bundle: fixture.app, home: fixture.home) { _ in dependencies }
    #expect(session.mode == .attach)
    let model = try #require(session.model)
    session.launch()
    await model.refreshAndWait()
    #expect(model.attached && !model.shouldShowSetupAtLaunch)
    #expect(model.verified?.installation == (try dependencies.installation.current()))
    #expect(model.engineActionKey == nil)
    model.prepareSetup()
    #expect(!preferences.bool(forKey: "setupCompleted"))
    #expect(preferences.object(forKey: "setupDeferred") == nil)
    await model.startEngineAndWait()
    #expect(await session.shutdown())
    #expect(await host.calls.isEmpty)
}

@MainActor
@Test(.timeLimit(.minutes(1)))
func ownedLaunchStartsOnceAndQuitWaitsForCleanupWithoutAcceptingMoreControls() async throws {
    let fixture = try LaunchFixture()
    defer { fixture.remove() }
    let preferences = UserDefaults.scratch("launch-test")
    preferences.set(SetupStep.connection.id, forKey: "setupStep")
    let (events, signal) = AsyncStream<String>.makeStream()
    let host = HostBoundary(signal)
    await host.hold(start: true, stop: true)
    let dependencies = try launchDependencies(fixture, preferences: preferences, host: host.service)
    let session = LauncherMain.session(bundle: fixture.app, home: fixture.home) { _ in dependencies }
    let model = try #require(session.model)
    #expect(session.mode == .owned(leftover: nil))
    var next = events.makeAsyncIterator()
    session.launch()
    session.launch()
    #expect(await next.next() == "start")
    await model.refreshHost()
    #expect(model.hostState == .starting && model.controlBusy && model.verified == nil)
    model.startEngine()
    #expect(await host.calls == ["start"])
    await host.releaseStart()
    await model.launchAndWait()
    #expect(model.hostState == .running && model.verified != nil)
    // The engine answered, so the start request no longer waits for a response.
    #expect(model.controlMessage == nil)
    #expect(model.engineActionKey == "engine-restart")
    #expect(!FileManager.default.fileExists(atPath: model.registrationURL.path))
    var quitReturned = false
    let quit = Task { let result = await session.shutdown(); quitReturned = true; return result }
    #expect(await next.next() == "stop")
    #expect(!quitReturned)
    model.startEngine()
    await model.setLogin(true)
    #expect(await host.calls == ["start", "stop"])
    await host.releaseStop()
    #expect(await quit.value)
    #expect(await session.shutdown())
    #expect(await host.calls == ["start", "stop"])
}

private actor Tally {
    private var counts: [String: Int] = [:]
    func add(_ key: String) { counts[key, default: 0] += 1 }
    func count(_ key: String) -> Int { counts[key] ?? 0 }
}

@MainActor private final class HandedOff {
    var plans: [UpdatePlan] = []
}

@MainActor
@Test(.timeLimit(.minutes(1)))
func aRefusedQuitOffersTheSameUpdateAgainAndKeepsCheckingForUpdates() async throws {
    let fixture = try LaunchFixture()
    defer { fixture.remove() }
    let preferences = UserDefaults.scratch("launch-test")
    preferences.set(SetupStep.connection.id, forKey: "setupStep")
    preferences.set(UpdateConsent.daily.rawValue, forKey: "updateConsent")
    let (_, signal) = AsyncStream<String>.makeStream()
    let host = HostBoundary(signal)
    let tally = Tally()
    let handedOff = HandedOff()
    let home = fixture.home
    var dependencies = try launchDependencies(fixture, preferences: preferences, host: host.service)
    let updates = LauncherUpdates(preferences: preferences, fetch: {
        await tally.add("check")
        throw URLError(.notConnectedToInternet)
    }, automaticInterval: 1, authenticate: { _ in nil })
    dependencies.updates = updates
    dependencies.installOperations = UpdateInstallerOperations(reserve: { 0 }, download: { version, _, _ in
        await tally.add("download")
        let artifact = VerifiedArtifact(version: version, commit: String(repeating: "b", count: 40),
                                        imageName: "RoleBand-\(version)-macOS-arm64.dmg", bytes: 1, sha256: String(repeating: "d", count: 64))
        return DownloadedUpdate(artifact: artifact, image: home.appendingPathComponent(artifact.imageName))
    }, prepare: { _ in
        let trust = InstalledUpdateIdentity(version: "0.1.0", commit: String(repeating: "a", count: 40),
                                            publicKey: Data(repeating: 7, count: 32), certificateSHA256: String(repeating: "c", count: 64))
        return try UpdatePlan(id: UUID(), installed: home.appendingPathComponent("Applications/RoleBand.app"), home: home,
                              trust: trust, to: "0.1.1", toCommit: String(repeating: "b", count: 40), parent: getpid())
    }, discard: { _ in }, handOff: { handedOff.plans.append($0) })
    let session = LauncherMain.session(bundle: fixture.app, home: fixture.home) { _ in dependencies }
    let model = try #require(session.model)
    defer { updates.stop(); model.stop() }
    session.launch()
    await model.launchAndWait()
    let installer = try #require(model.installer)
    await installer.installAndWait("0.1.1")
    #expect(installer.activity == .restarting && handedOff.plans.count == 1)

    await host.set(.running, failStop: true)
    #expect(await session.shutdown() == false)
    #expect(installer.activity == .failed(.restart))
    let checks = await tally.count("check")
    var resumed = false
    for _ in 0..<300 where !resumed {
        try await Task.sleep(for: .milliseconds(10))
        resumed = await tally.count("check") > checks
    }
    #expect(resumed, "automatic update checks stay off after the refused quit")

    await host.set(.running)
    installer.install("0.1.1")
    #expect(installer.activity == .restarting)
    #expect(handedOff.plans.count == 2 && Set(handedOff.plans.map(\.id)).count == 1)
    #expect(await tally.count("download") == 1)
}

@MainActor
@Test func anUnchangedHostRedrawsNothingAtItsEverySecondPoll() async throws {
    let fixture = try LaunchFixture()
    defer { fixture.remove() }
    let preferences = UserDefaults.scratch("launch-test")
    let (_, signal) = AsyncStream<String>.makeStream()
    let host = HostBoundary(signal)
    var dependencies = try launchDependencies(fixture, preferences: preferences, host: host.service)
    dependencies.mode = .owned(leftover: nil)
    let model = LauncherModel(dependencies)
    defer { model.stop() }
    await host.set(.needsAttention, diagnostics: "api: last useful error")
    await model.refreshHost()
    #expect(model.hostState == .needsAttention && model.diagnosticLines == "api: last useful error")
    var redraws = 0
    let watch = model.objectWillChange.sink { redraws += 1 }
    defer { watch.cancel() }
    for _ in 0..<5 { await model.refreshHost() }
    #expect(redraws == 0)
    await host.set(.needsAttention, diagnostics: "api: a newer error")
    await model.refreshHost()
    #expect(redraws > 0 && model.diagnosticLines == "api: a newer error")
}

@Test func theLogTailsAreReadOnceEachTimeTheHostNeedsAttention() async {
    let tally = Tally()
    let tails = DiagnosticTails { await tally.add("read"); return "api: last useful error" }
    for state in [HostState.running, .needsAttention, .needsAttention, .needsAttention] { _ = await tails.lines(for: state) }
    #expect(await tally.count("read") == 1)
    #expect(await tails.lines(for: .stopped) == "")
    #expect(await tails.lines(for: .needsAttention) == "api: last useful error")
    #expect(await tally.count("read") == 2)
}

@MainActor
@Test func aCrashLoopShowsItsTailAndRestartRecoversWithoutARegistration() async throws {
    let fixture = try LaunchFixture()
    defer { fixture.remove() }
    let preferences = UserDefaults.scratch("launch-test")
    preferences.set(SetupStep.connection.id, forKey: "setupStep")
    let (_, signal) = AsyncStream<String>.makeStream()
    let host = HostBoundary(signal)
    var dependencies = try launchDependencies(fixture, preferences: preferences, host: host.service)
    dependencies.mode = .owned(leftover: nil)
    dependencies.readSchedule = { _, _, _ in
        try ScheduleState.decode(Data(#"{"generated_at":"2026-10-30T12:00:00Z","enabled":true,"plan":{"enabled":true,"paused_until":null}}"#.utf8))
    }
    let model = LauncherModel(dependencies)
    model.panelOpen = true
    await model.launchAndWait()
    #expect(model.scheduleState?.enabled == true)
    await host.set(.backingOff(until: 10))
    await model.refreshHost()
    #expect(model.titleKey == "host-recovering" && model.verified == nil && model.engineActionKey == nil)
    await host.set(.needsAttention, diagnostics: "api: last useful error")
    await model.refreshHost()
    #expect(model.titleKey == "host-attention" && model.menuBarBadge == "exclamationmark.triangle.fill")
    #expect(model.diagnosticLines == "api: last useful error" && model.engineActionKey == "engine-restart")
    await model.refreshAndWait()
    #expect(model.verified == nil)
    await model.startEngineAndWait()
    #expect(model.hostState == .running && model.verified != nil && model.diagnosticLines.isEmpty)
    #expect(model.symbol == "checkmark.circle" && model.menuBarBadge == nil)
    #expect(model.scheduleState?.enabled == true)
    #expect(await host.calls == ["start", "restart"])
    await host.set(.needsAttention, diagnostics: "jobs: couldn't stop", failStop: true)
    #expect(await model.shutdown() == false)
    #expect(model.controlMessage == "host-stop-failed" && model.mayRestartEngine)
    await host.set(.needsAttention)
    #expect(await model.shutdown())
}

@MainActor
@Test func ownedAppWiringStartsARealChildInAScratchHomeAndReapsItOnQuit() async throws {
    let fixture = try LaunchFixture()
    defer { fixture.remove() }
    let python = try await CommandRunner.run(executable: URL(fileURLWithPath: "/usr/bin/python3"),
        arguments: ["-I", "-c", "import sys; print(sys.executable)"])
    try FileManager.default.createDirectory(at: fixture.resources.appendingPathComponent("python/bin"), withIntermediateDirectories: true)
    try FileManager.default.createSymbolicLink(atPath: fixture.resources.appendingPathComponent("python/bin/python3.12").path,
        withDestinationPath: python.text.trimmingCharacters(in: .whitespacesAndNewlines))
    try fixture.put("""
    import json, os, pathlib, time
    home = pathlib.Path.home()
    assert os.environ['ROLEBAND_DATABASE_URL'] == ''
    assert pathlib.Path(os.environ['ROLEBAND_PGDATA']) == home / '.roleband/db'
    (home / '.roleband/child.json').write_text(json.dumps({'pid': os.getpid(), 'port': os.environ['ROLEBAND_API_PORT']}))
    time.sleep(3600)
    """, at: fixture.resources.appendingPathComponent("engine/packaged.py"))
    let preferences = UserDefaults.scratch("launch-test")
    preferences.set(SetupStep.connection.id, forKey: "setupStep")
    let bundle = try #require(Bundle(url: fixture.app))
    let configuration = try HostConfiguration(bundle: bundle, home: fixture.home, port: 58319)
    let dependencies = try launchDependencies(fixture, preferences: preferences, host: .live(configuration))
    let session = LauncherMain.session(bundle: fixture.app, home: fixture.home) { _ in dependencies }
    do {
        await session.model?.launchAndWait()
        let childFile = HomeLayout(fixture.home).data.appendingPathComponent("child.json")
        let deadline = ProcessInfo.processInfo.systemUptime + 5
        while !FileManager.default.fileExists(atPath: childFile.path), ProcessInfo.processInfo.systemUptime < deadline {
            try await Task.sleep(for: .milliseconds(10))
        }
        let child = try JSONSerialization.jsonObject(with: Data(contentsOf: childFile)) as! [String: Any]
        let pid = try #require(child["pid"] as? Int32)
        #expect(child["port"] as? String == "58319")
        #expect(kill(pid, 0) == 0)
        #expect(await session.shutdown())
        #expect(kill(pid, 0) != 0)
        #expect(!FileManager.default.fileExists(atPath: HomeLayout(fixture.home).data.appendingPathComponent("launcher/owned-engine.json").path))
    } catch { _ = await session.shutdown(); throw error }
}

@MainActor
@Test(.enabled(if: ProcessInfo.processInfo.environment["ROLEBAND_HOST_TEST_RESOURCES"] != nil,
               "Requires a packaged runtime for the migrated scratch-database launch proof"), .timeLimit(.minutes(2)))
func ownedAppUsesTheBundledAPIOnAMigratedScratchDatabaseAndStopsItsLeftover() async throws {
    let fixture = try LaunchFixture()
    defer { fixture.remove() }
    let resources = URL(fileURLWithPath: try #require(ProcessInfo.processInfo.environment["ROLEBAND_HOST_TEST_RESOURCES"]))
    try FileManager.default.createSymbolicLink(at: fixture.resources.appendingPathComponent("python"),
        withDestinationURL: resources.appendingPathComponent("python"))
    try FileManager.default.copyItem(at: resources.appendingPathComponent("engine"), to: fixture.resources.appendingPathComponent("engine"))
    let bootstrap = fixture.resources.appendingPathComponent("engine/packaged.py")
    let script = try String(contentsOf: bootstrap, encoding: .utf8)
    try script.replacingOccurrences(of: "    args = sys.argv[1:]", with: """
        if sys.argv[1:3] == ['supervisor', 'run']:
            sys.argv.append('--dry-run-network')
        args = sys.argv[1:]
    """).write(to: bootstrap, atomically: true, encoding: .utf8)
    let preferences = UserDefaults.scratch("launch-test")
    let bundle = try #require(Bundle(url: fixture.app))
    let configuration = try HostConfiguration(bundle: bundle, home: fixture.home, port: 58319)
    let encoder = JSONEncoder()
    encoder.outputFormatting = [.withoutEscapingSlashes]
    func literal(_ url: URL) throws -> String { String(decoding: try encoder.encode(url.path), as: UTF8.self) }
    let initialize = """
    import os, sys
    from pathlib import Path
    sys.dont_write_bytecode = True
    sys.path.insert(0, \(try literal(fixture.resources.appendingPathComponent("engine"))))
    from alembic import command
    from alembic.config import Config
    from tracker.platform.embedded_db import claim_cluster
    claim_cluster(Path(os.environ['ROLEBAND_PGDATA']), 'app')
    config = Config(\(try literal(fixture.resources.appendingPathComponent("engine/alembic.ini"))))
    config.set_main_option('script_location', \(try literal(fixture.resources.appendingPathComponent("engine/alembic"))))
    command.upgrade(config, 'head')
    """
    var dependencies = try launchDependencies(fixture, preferences: preferences, host: .live(configuration))
    dependencies.readStatus = StatusClient.read
    var session: LauncherSession?
    do {
        let migrate = Process()
        migrate.executableURL = configuration.python
        migrate.arguments = ["-I", "-c", initialize]
        migrate.environment = configuration.environment(token: UUID().uuidString)
        migrate.standardInput = FileHandle.nullDevice
        let log = fixture.root.appendingPathComponent("migration.log")
        FileManager.default.createFile(atPath: log.path, contents: nil)
        let output = try FileHandle(forWritingTo: log)
        defer { try? output.close() }
        migrate.standardOutput = output
        migrate.standardError = output
        try migrate.run()
        let migrationDeadline = ProcessInfo.processInfo.systemUptime + 30
        while migrate.isRunning && ProcessInfo.processInfo.systemUptime < migrationDeadline {
            try await Task.sleep(for: .milliseconds(20))
        }
        if migrate.isRunning { migrate.terminate() }
        while migrate.isRunning { try await Task.sleep(for: .milliseconds(20)) }
        let migrationLog = try String(contentsOf: log, encoding: .utf8)
        try #require(migrate.terminationStatus == 0, Comment(rawValue: migrationLog))
        let oldServer = LaunchMode.runningServer(configuration.pgdata).flatMap(OwnedProcess.read)
        let mode = LaunchMode.decide(bundle: fixture.app, home: fixture.home)
        if let oldServer { #expect(mode == .owned(leftover: oldServer.pid)) }
        else { #expect(mode == .owned(leftover: nil)) }
        let running = LauncherMain.session(bundle: fixture.app, home: fixture.home) { _ in dependencies }
        session = running
        let model = try #require(running.model)
        await model.launchAndWait()
        let deadline = ProcessInfo.processInfo.systemUptime + 30
        while model.verified == nil && ProcessInfo.processInfo.systemUptime < deadline {
            await model.refreshAndWait()
            try await Task.sleep(for: .milliseconds(100))
        }
        try #require(model.verified?.installation == configuration.installation, Comment(rawValue: model.diagnosticLines))
        #expect(oldServer?.isAlive != true)
        let record = try JSONSerialization.jsonObject(with: Data(contentsOf: configuration.record)) as! [String: String]
        let token = try #require(record["token"])
        #expect(!FileManager.default.fileExists(atPath: model.registrationURL.path))
        #expect(await running.shutdown())
        #expect(try OwnedProcess.marked(token).isEmpty)
        #expect(LaunchMode.runningServer(configuration.pgdata) == nil)
    } catch {
        _ = await session?.shutdown()
        // A migration can leave Postgres running before the app has claimed it.
        if let pid = LaunchMode.runningServer(configuration.pgdata), let server = OwnedProcess.read(pid),
           server.isPostgres, server.matchesDatabase(configuration.pgdata) {
            try? server.signal(SIGINT)
            let deadline = ProcessInfo.processInfo.systemUptime + 5
            while server.isAlive && ProcessInfo.processInfo.systemUptime < deadline { try? await Task.sleep(for: .milliseconds(20)) }
            if server.isAlive { try? server.signal(SIGKILL) }
        }
        throw error
    }
}

@MainActor
@Test(.enabled(if: ProcessInfo.processInfo.environment["ROLEBAND_HOST_TEST_RESOURCES"] != nil,
               "Requires a packaged runtime for fresh-home preparation"), .timeLimit(.minutes(2)))
func freshHomeCanQuitDuringPreparationThenResumeToAUsableOfflineRadar() async throws {
    let fixture = try LaunchFixture()
    defer { fixture.remove() }
    let resources = URL(fileURLWithPath: try #require(ProcessInfo.processInfo.environment["ROLEBAND_HOST_TEST_RESOURCES"]))
    try FileManager.default.createSymbolicLink(at: fixture.resources.appendingPathComponent("python"),
        withDestinationURL: resources.appendingPathComponent("python"))
    try FileManager.default.copyItem(at: resources.appendingPathComponent("engine"), to: fixture.resources.appendingPathComponent("engine"))
    try FileManager.default.createSymbolicLink(at: fixture.resources.appendingPathComponent("dashboard"),
        withDestinationURL: resources.appendingPathComponent("dashboard"))
    let downloader = fixture.resources.appendingPathComponent("engine/tracker/semantic/provision.py")
    var downloading = try String(contentsOf: downloader, encoding: .utf8)
    downloading = downloading.replacingOccurrences(of: "https://huggingface.co/{repo}/resolve/{revision}/{path}",
        with: "http://127.0.0.1:58339/{path}").replacingOccurrences(of: "time.sleep(min(2**attempt * 2, 30))", with: "time.sleep(0)")
    try downloading.write(to: downloader, atomically: true, encoding: .utf8)
    let bootstrap = fixture.resources.appendingPathComponent("engine/packaged.py")
    let original = try String(contentsOf: bootstrap, encoding: .utf8)
    let script = original.replacingOccurrences(of: "    args = sys.argv[1:]", with: """
        args = sys.argv[1:]
        if args[:2] == ['supervisor', 'run']:
            sys.argv.append('--dry-run-network')
            args = sys.argv[1:]
        if args == ['prepare-database'] and (Path.home() / '.roleband/pause-preparation').exists():
            import time
            (Path.home() / '.roleband/preparing-child').write_text(str(os.getpid()))
            time.sleep(3600)
    """)
    try script.write(to: bootstrap, atomically: true, encoding: .utf8)
    let pause = HomeLayout(fixture.home).data.appendingPathComponent("pause-preparation")
    try fixture.put("pause", at: pause)
    let preferences = UserDefaults.scratch("fresh-home")
    let bundle = try #require(Bundle(url: fixture.app))
    let configuration = try HostConfiguration(bundle: bundle, home: fixture.home, port: 58329)
    var session: LauncherSession?
    func makeSession() -> LauncherSession {
        LauncherMain.session(bundle: fixture.app, home: fixture.home) { mode in
            var dependencies = LauncherDependencies.live(mode: mode, bundle: bundle, home: fixture.home,
                                                        port: 58329, preferences: preferences)
            dependencies.loginService = LoginService(state: { .off }, setEnabled: { _ in Issue.record("Unexpected login change") }, openSettings: {})
            dependencies.openBrowser = { _ in Issue.record("Unexpected browser open"); return false }
            return dependencies
        }
    }
    do {
        let first = makeSession()
        session = first
        let model = try #require(first.model)
        #expect(first.mode == .owned(leftover: nil))
        model.step = .connection
        await model.launchAndWait()
        let preparingDeadline = ProcessInfo.processInfo.systemUptime + 15
        while model.preparation?.database != "creating" && ProcessInfo.processInfo.systemUptime < preparingDeadline {
            await model.refreshHost()
            try await Task.sleep(for: .milliseconds(50))
        }
        try #require(model.preparation?.database == "creating")
        #expect(!model.preparationReady && model.hostState == .starting)
        model.dismissSetup()
        let firstRecord = try JSONSerialization.jsonObject(with: Data(contentsOf: configuration.record)) as! [String: String]
        let firstToken = try #require(firstRecord["token"])
        #expect(await first.shutdown())
        #expect(try OwnedProcess.marked(firstToken).isEmpty)
        #expect(LaunchMode.runningServer(configuration.pgdata) == nil)
        try FileManager.default.removeItem(at: pause)
        let resumed = makeSession()
        session = resumed
        let ready = try #require(resumed.model)
        #expect(ready.step == .connection && !ready.shouldShowSetupAtLaunch)
        await ready.launchAndWait()
        let readyDeadline = ProcessInfo.processInfo.systemUptime + 40
        while (!ready.preparationReady || ready.preparation?.reason != "offline") && ProcessInfo.processInfo.systemUptime < readyDeadline {
            await ready.refreshHost()
            await ready.refreshAndWait()
            try await Task.sleep(for: .milliseconds(100))
        }
        try #require(ready.preparationReady, Comment(rawValue: ready.diagnosticLines))
        #expect(ready.preparation?.database == "ready" && ready.preparation?.service == "ready")
        #expect(ready.preparation?.model == "waiting" && ready.preparation?.reason == "offline")
        #expect((ready.preparation?.totalBytes ?? 0) > 0)
        #expect(ready.hostState == .running && !ready.setupCompleted && ready.step == .connection)
        let dashboard = try await URLSession.shared.data(from: BrowserRoute.radar.url(for: configuration.installation))
        #expect((dashboard.1 as? HTTPURLResponse)?.statusCode == 200 && !dashboard.0.isEmpty)
        let record = try JSONSerialization.jsonObject(with: Data(contentsOf: configuration.record)) as! [String: String]
        let finalToken = try #require(record["token"])
        #expect(await resumed.shutdown())
        #expect(try OwnedProcess.marked(finalToken).isEmpty)
        #expect(LaunchMode.runningServer(configuration.pgdata) == nil)
    } catch { _ = await session?.shutdown(); throw error }
}
