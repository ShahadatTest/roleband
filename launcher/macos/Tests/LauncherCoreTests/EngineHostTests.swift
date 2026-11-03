import Darwin
import Foundation
import Testing
@testable import LauncherCore

private final class HostClock: @unchecked Sendable {
    private let lock = NSLock()
    private var value: TimeInterval = 0
    func read() -> TimeInterval { lock.withLock { value } }
    func advance(_ seconds: TimeInterval) { lock.withLock { value += seconds } }
}

private struct HostFixture: Sendable {
    let root: URL
    let configuration: HostConfiguration
    var data: URL { configuration.data }

    init(script: String = "import os,pathlib,time\n(pathlib.Path.home() / '.roleband/engine-ready').write_text(os.environ['ROLEBAND_ENGINE_OWNER'])\ntime.sleep(3600)\n") throws {
        root = FileManager.default.temporaryDirectory.appendingPathComponent("host \(UUID().uuidString)")
        let home = root.appendingPathComponent("home")
        let resources = home.appendingPathComponent("Applications/RoleBand.app/Contents/Resources")
        for folder in [resources.appendingPathComponent("python/bin"), resources.appendingPathComponent("engine")] {
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        }
        try PropertyListSerialization.data(fromPropertyList: ["CFBundleIdentifier": "com.roleband.launcher"], format: .xml, options: 0)
            .write(to: resources.deletingLastPathComponent().appendingPathComponent("Info.plist"))
        let probe = Process()
        let output = Pipe()
        probe.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
        probe.arguments = ["-I", "-c", "import sys; print(sys.executable)"]
        probe.standardOutput = output
        try probe.run()
        let executable = String(decoding: output.fileHandleForReading.readDataToEndOfFile(), as: UTF8.self)
            .trimmingCharacters(in: .whitespacesAndNewlines)
        probe.reap()
        guard probe.terminationStatus == 0, executable.hasPrefix("/") else { throw HostProblem.invalidConfiguration }
        try FileManager.default.createSymbolicLink(atPath: resources.appendingPathComponent("python/bin/python3.12").path,
                                                 withDestinationPath: executable)
        try Data(script.utf8).write(to: resources.appendingPathComponent("engine/packaged.py"))
        let identity: [String: Any] = ["product": "roleband", "format": 1, "version": "0.1.0", "api_origin": "http://127.0.0.1:58271",
                                      "instance": "0123456789abcdef01234567"]
        let installation = try JSONDecoder().decode(Installation.self, from: JSONSerialization.data(withJSONObject: identity))
        configuration = try HostConfiguration(resources: resources, home: home, installation: installation)
    }

    func host(clock: HostClock = HostClock(), healthy: Bool = false, grace: TimeInterval = 0.1) -> EngineHost {
        EngineHost(configuration: configuration, now: { clock.read() }, readStatus: { installation in
            if !healthy { throw ConnectionProblem.unavailable }
            var identity = try JSONSerialization.jsonObject(with: JSONEncoder().encode(installation)) as! [String: Any]
            identity["status"] = ["observed_at": "2026-10-29T12:00:00Z", "activity": "idle", "attention": [], "model": "ready"]
            return try StatusClient.decode(JSONSerialization.data(withJSONObject: ["db": "ok", "launcher": identity]),
                                           status: 200, installation: installation)
        }, automatic: false, stopGrace: grace)
    }

    func token() throws -> String {
        let raw = try JSONSerialization.jsonObject(with: Data(contentsOf: configuration.record)) as! [String: String]
        return try #require(raw["token"])
    }

    /// Python's `write_text` creates the file empty before it writes, so an empty file is not there yet.
    func waitFor(_ name: String) async throws -> Data {
        let url = data.appendingPathComponent(name)
        let deadline = ProcessInfo.processInfo.systemUptime + 5
        while ProcessInfo.processInfo.systemUptime < deadline {
            if let bytes = try? Data(contentsOf: url), !bytes.isEmpty { return bytes }
            try await Task.sleep(for: .milliseconds(10))
        }
        if let log = try? String(contentsOf: configuration.log, encoding: .utf8) { print(log) }
        throw HostProblem.stopFailed
    }

    func remove() {
        if let saved = try? token(), let remaining = try? OwnedProcess.marked(saved) {
            for process in remaining where !process.isPostgres { try? process.signal(SIGKILL, group: true) }
        }
        if let pid = LaunchMode.runningServer(configuration.pgdata), let server = OwnedProcess.read(pid),
           server.isPostgres, server.matchesDatabase(configuration.pgdata),
           let path = LaunchMode.executable(pid), LaunchMode.isInsideApp(path) {
            try? server.signal(SIGINT)
            let deadline = ProcessInfo.processInfo.systemUptime + 2
            while server.isAlive && ProcessInfo.processInfo.systemUptime < deadline { usleep(1000) }
            if server.isAlive { try? server.signal(SIGKILL) }
        }
        try? FileManager.default.removeItem(at: root)
    }

    func waitForEngine() async throws {
        let expected = try token()
        let deadline = ProcessInfo.processInfo.systemUptime + 5
        while ProcessInfo.processInfo.systemUptime < deadline {
            if (try? String(contentsOf: data.appendingPathComponent("engine-ready"), encoding: .utf8)) == expected,
               try OwnedProcess.marked(expected).count == 1 { return }
            try await Task.sleep(for: .milliseconds(10))
        }
        if let log = try? String(contentsOf: configuration.log, encoding: .utf8) { print("readiness log: \(log)") }
        throw HostProblem.stopFailed
    }
}

private actor PreparationHealth {
    var service = "starting"
    func answer() -> EngineHealth {
        EngineHealth(preparation: EnginePreparation(database: service == "starting" ? "creating" : "ready",
            model: "waiting", service: service, downloadedBytes: 0, totalBytes: 100,
            tier: "fp32", reason: "offline", format: 1))
    }
    func finish(_ value: String) { service = value }
}

@Test(arguments: ["ready", "failed"])
func preparingForLongerThanTheStartupGraceKeepsTheSameChildUntilARealResult(result: String) async throws {
    let fixture = try HostFixture()
    defer { fixture.remove() }
    let clock = HostClock()
    let health = PreparationHealth()
    let host = EngineHost(configuration: fixture.configuration, now: clock.read,
                          readHealth: { _ in await health.answer() }, automatic: false, stopGrace: 0.1)
    try await host.start()
    do {
        try await fixture.waitForEngine()
        let token = try fixture.token()
        clock.advance(180)
        try await host.check()
        #expect(await host.state == .starting)
        #expect(try fixture.token() == token)
        clock.advance(180)
        try await host.check()
        #expect(await host.state == .starting)
        await health.finish(result)
        try await host.check()
        #expect(await host.state == (result == "ready" ? .running : .needsAttention))
        #expect(try fixture.token() == token)
    } catch { try? await host.stop(); throw error }
    try await host.stop()
}

@Test(.enabled(if: ProcessInfo.processInfo.environment["ROLEBAND_HOST_TEST_RESOURCES"] != nil,
               "Requires an assembled standalone bundle for the real Postgres lifecycle test"))
func bundledPostgresStopsAfterClientsAndALeftoverStopsBeforeTheNextEngine() async throws {
    let resources = URL(fileURLWithPath: try #require(ProcessInfo.processInfo.environment["ROLEBAND_HOST_TEST_RESOURCES"]))
    let encoder = JSONEncoder()
    encoder.outputFormatting = [.withoutEscapingSlashes]
    let enginePath = String(decoding: try encoder.encode(resources.appendingPathComponent("engine").path), as: UTF8.self)
    let fixture = try HostFixture(script: """
    import json, os, pathlib, subprocess, sys, time
    sys.dont_write_bytecode = True
    sys.path.insert(0, \(enginePath))
    from tracker.platform.embedded_db import ensure_server
    server = ensure_server(pathlib.Path(os.environ['ROLEBAND_PGDATA']), database='host_fixture')
    job_code = '''
    import os, pathlib, signal, sys, time
    import psycopg2
    connection = psycopg2.connect(os.environ['FIXTURE_DSN'])
    def stopped(*args):
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            assert cursor.fetchone()[0] == 1
        connection.close()
        (pathlib.Path.home() / '.roleband/client-stopped').write_text('database still answered')
        sys.exit(0)
    signal.signal(signal.SIGTERM, stopped)
    print('ready', flush=True)
    time.sleep(3600)
    '''
    job = subprocess.Popen([sys.executable, '-I', '-c', job_code], start_new_session=True,
                           env=dict(os.environ, FIXTURE_DSN=server.dsn()), stdout=subprocess.PIPE)
    assert job.stdout.readline().strip() == b'ready'
    (pathlib.Path.home() / '.roleband/ready.json').write_text(json.dumps({'job': job.pid}))
    time.sleep(3600)
    """)
    defer { fixture.remove() }
    try FileManager.default.removeItem(at: fixture.configuration.python)
    try FileManager.default.createSymbolicLink(at: fixture.configuration.python, withDestinationURL: resources.appendingPathComponent("python/bin/python3.12"))
    try FileManager.default.createDirectory(at: fixture.configuration.log.deletingLastPathComponent(), withIntermediateDirectories: true)
    let initialize = "import pathlib,sys; sys.dont_write_bytecode=True; sys.path.insert(0, \(enginePath)); from tracker.platform.embedded_db import claim_cluster,ensure_server; pgdata=pathlib.Path(\(String(decoding: try encoder.encode(fixture.configuration.pgdata.path), as: UTF8.self))); claim_cluster(pgdata,'app'); ensure_server(pgdata,database='host_fixture')"
    let setup = try OwnedChild(executable: fixture.configuration.python, arguments: ["-I", "-c", initialize],
                               environment: fixture.configuration.environment(token: UUID().uuidString), log: fixture.configuration.log)
    let deadline = ProcessInfo.processInfo.systemUptime + 15
    while setup.running() && ProcessInfo.processInfo.systemUptime < deadline { try await Task.sleep(for: .milliseconds(10)) }
    #expect(!setup.running())
    if LaunchMode.runningServer(fixture.configuration.pgdata) == nil {
        print(try String(contentsOf: fixture.configuration.log, encoding: .utf8))
    }
    let leftover = try #require(LaunchMode.runningServer(fixture.configuration.pgdata))
    let oldServer = try #require(OwnedProcess.read(leftover))
    #expect(oldServer.isPostgres)
    let other = try HostFixture()
    defer { other.remove() }
    try FileManager.default.createDirectory(at: other.configuration.pgdata, withIntermediateDirectories: true)
    try Data(contentsOf: fixture.configuration.pgdata.appendingPathComponent("postmaster.pid"))
        .write(to: other.configuration.pgdata.appendingPathComponent("postmaster.pid"))
    let wrongDatabase = other.host()
    await #expect(throws: HostProblem.processInspection) { try await wrongDatabase.start() }
    #expect(oldServer.isAlive)
    try? await wrongDatabase.stop()
    let host = fixture.host(grace: 10)
    do {
        try await host.start()
        _ = try await fixture.waitFor("ready.json")
        let server = try #require(LaunchMode.runningServer(fixture.configuration.pgdata))
        #expect(server != leftover && !oldServer.isAlive)
        let current = try #require(OwnedProcess.read(server))
        let token = try fixture.token()
        try await host.stop()
        #expect(!current.isAlive)
        #expect(LaunchMode.runningServer(fixture.configuration.pgdata) == nil)
        #expect(try OwnedProcess.marked(token).isEmpty)
        #expect(try String(contentsOf: fixture.data.appendingPathComponent("client-stopped"), encoding: .utf8) == "database still answered")
    } catch { try? await host.stop(); throw error }
}

@Test func ownedEngineStartsIsolatedInItsOwnGroupAndIgnoresAmbientSettings() async throws {
    let fixture = try HostFixture(script: """
    import json, os, pathlib, sys, time
    folder = pathlib.Path.home() / '.roleband'
    (folder / 'observed.json').write_text(json.dumps({'pid': os.getpid(), 'group': os.getpgrp(),
        'env': dict(os.environ), 'isolated': sys.flags.isolated, 'argv': sys.argv[1:]}))
    time.sleep(3600)
    """)
    defer { fixture.remove() }
    let host = fixture.host(healthy: true)
    try await host.start()
    do {
        let bytes = try await fixture.waitFor("observed.json")
        let observed = try JSONSerialization.jsonObject(with: bytes) as! [String: Any]
        let env = try #require(observed["env"] as? [String: String])
        #expect(observed["pid"] as? Int == observed["group"] as? Int)
        #expect(observed["group"] as? Int != Int(getpgrp()))
        #expect(observed["isolated"] as? Int == 1)
        #expect(observed["argv"] as? [String] == ["supervisor", "run"])
        #expect(env["HOME"] == fixture.configuration.home.path)
        #expect(env["ROLEBAND_PGDATA"] == fixture.configuration.pgdata.path)
        #expect(env["ROLEBAND_DATABASE_URL"] == "")
        #expect(env["ROLEBAND_PACKAGED"] == "1" && env["PYTHONDONTWRITEBYTECODE"] == "1" && env["PYTHONNOUSERSITE"] == "1")
        #expect(env["ROLEBAND_API_HOST"] == "127.0.0.1" && env["ROLEBAND_API_PORT"] == "58271")
        #expect(env["PYTHONPATH"] == nil && env["ROLEBAND_SKIP_PREFLIGHT"] == nil)
        #expect(try OwnedProcess.marked(fixture.token()).count == 1)
        try await host.check()
        #expect(await host.state == .running)
    } catch { try? await host.stop(); throw error }
    let token = try fixture.token()
    try await host.stop()
    #expect(await host.state == .stopped)
    #expect(try OwnedProcess.marked(token).isEmpty)
    #expect(!FileManager.default.fileExists(atPath: fixture.configuration.record.path))
}

@Test func unansweringEnginesBackOffThreeTimesThenRequireAnExplicitRestart() async throws {
    let fixture = try HostFixture()
    defer { fixture.remove() }
    let clock = HostClock()
    let host = fixture.host(clock: clock)
    try await host.start()
    do {
        for restart in 0..<3 {
            clock.advance(60)
            try await host.check()
            let failureAt = clock.read()
            #expect(await host.state == .backingOff(until: failureAt + pow(2, Double(restart))))
            let old = try? fixture.token()
            try await host.check()
            #expect((try? fixture.token()) == old)
            clock.advance(pow(2, Double(restart)))
            try await host.check()
            #expect(await host.state == .starting)
        }
        clock.advance(60)
        try await host.check()
        #expect(await host.state == .needsAttention)
        #expect(await host.lastFailure == "engine_unhealthy")
        clock.advance(1000)
        try await host.check()
        #expect(await host.state == .needsAttention)
        try await host.restart()
        #expect(await host.state == .starting)
    } catch { try? await host.stop(); throw error }
    try await host.stop()
}

@Test func healthyReadingsDoNotEraseTheRollingRestartBudget() async throws {
    let fixture = try HostFixture()
    defer { fixture.remove() }
    let clock = HostClock()
    let host = fixture.host(clock: clock, healthy: true)
    try await host.start()
    do {
        for restart in 0...3 {
            try await fixture.waitForEngine()
            try await host.check()
            #expect(await host.state == .running)
            let processes = try OwnedProcess.marked(fixture.token())
            #expect(processes.count == 1)
            for process in processes { try process.signal(SIGKILL) }
            while processes.contains(where: \.isAlive) { try await Task.sleep(for: .milliseconds(10)) }
            // The kernel can stop reporting the process before waitpid returns its status,
            // so the host may need another look before it sees the exit.
            for _ in 0..<500 {
                try await host.check()
                if await host.state != .running { break }
                try await Task.sleep(for: .milliseconds(10))
            }
            #expect(await host.state != .running)
            if restart < 3 {
                clock.advance(pow(2, Double(restart)))
                try await host.check()
            }
        }
        #expect(await host.state == .needsAttention)
    } catch { try? await host.stop(); throw error }
    try await host.stop()
}

@Test func restartAttemptsAgeOutOfTheTenMinuteWindow() async throws {
    let fixture = try HostFixture()
    defer { fixture.remove() }
    let clock = HostClock()
    let host = fixture.host(clock: clock)
    try await host.start()
    do {
        for _ in 0..<5 {
            clock.advance(601)
            try await host.check()
            clock.advance(1)
            try await host.check()
            #expect(await host.state == .starting)
        }
    } catch { try? await host.stop(); throw error }
    try await host.stop()
}

@Test func quitReapsStubbornJobsInSeparateSessionsWithoutSignallingAnUnrelatedProcess() async throws {
    let fixture = try HostFixture(script: """
    import json, os, pathlib, signal, subprocess, sys, time
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    job = subprocess.Popen([sys.executable, '-c', 'import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); print("job ready", flush=True); time.sleep(3600)'], start_new_session=True, stdout=subprocess.PIPE)
    job.stdout.readline()
    (pathlib.Path.home() / '.roleband/ready.json').write_text(json.dumps({'parent': os.getpid(), 'job': job.pid}))
    time.sleep(3600)
    """)
    defer { fixture.remove() }
    let unrelated = Process()
    unrelated.executableURL = URL(fileURLWithPath: "/bin/sleep")
    unrelated.arguments = ["3600"]
    try unrelated.run()
    defer { unrelated.stopAndReap() }
    let host = fixture.host()
    try await host.start()
    do {
        _ = try await fixture.waitFor("ready.json")
        let owned = try OwnedProcess.marked(fixture.token())
        #expect(owned.count == 2)
        #expect(Set(owned.map(\.group)).count == 2)
        let began = ProcessInfo.processInfo.systemUptime
        try await host.stop()
        #expect(ProcessInfo.processInfo.systemUptime - began >= 0.1)
        #expect(owned.allSatisfy { !$0.isAlive })
        #expect(unrelated.isRunning)
    } catch { try? await host.stop(); throw error }
}

@Test func aSavedMarkerRecoversAnOrphanBeforeLaunchingAReplacement() async throws {
    let fixture = try HostFixture()
    defer { fixture.remove() }
    let host = fixture.host()
    let saved = UUID().uuidString
    try FileManager.default.createDirectory(at: fixture.configuration.record.deletingLastPathComponent(), withIntermediateDirectories: true)
    try FileManager.default.createDirectory(at: fixture.configuration.log.deletingLastPathComponent(), withIntermediateDirectories: true)
    try JSONSerialization.data(withJSONObject: ["token": saved]).write(to: fixture.configuration.record)
    try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: fixture.configuration.record.path)
    let orphan = try OwnedChild(executable: fixture.configuration.python, arguments: ["-c", "import time; time.sleep(3600)"],
                                environment: fixture.configuration.environment(token: saved), log: fixture.configuration.log)
    try await host.start()
    do {
        #expect(!orphan.running())
        #expect(try OwnedProcess.marked(saved).isEmpty)
        #expect(try fixture.token() != saved)
    } catch { try? await host.stop(); throw error }
    try await host.stop()
}

@Test func reclaimStopsAnOrphanAndReleasesOwnershipWithoutStartingAnEngine() async throws {
    let fixture = try HostFixture()
    defer { fixture.remove() }
    let saved = UUID().uuidString
    try FileManager.default.createDirectory(at: fixture.configuration.record.deletingLastPathComponent(), withIntermediateDirectories: true)
    try FileManager.default.createDirectory(at: fixture.configuration.log.deletingLastPathComponent(), withIntermediateDirectories: true)
    try JSONSerialization.data(withJSONObject: ["token": saved]).write(to: fixture.configuration.record)
    try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: fixture.configuration.record.path)
    let orphan = try OwnedChild(executable: fixture.configuration.python, arguments: ["-c", "import time; time.sleep(3600)"],
                                environment: fixture.configuration.environment(token: saved), log: fixture.configuration.log)
    defer { if orphan.running() { kill(orphan.pid, SIGKILL); _ = orphan.running() } }
    let lock = fixture.configuration.record.deletingLastPathComponent().appendingPathComponent("owned-engine.lock")
    let owner = open(lock.path, O_CREAT | O_RDWR | O_CLOEXEC, 0o600)
    #expect(flock(owner, LOCK_EX | LOCK_NB) == 0)
    await #expect(throws: HostProblem.alreadyOwned) { try await fixture.host().reclaim() }
    #expect(orphan.running())
    close(owner)
    try await fixture.host().reclaim()
    #expect(!orphan.running())
    #expect(try OwnedProcess.marked(saved).isEmpty)
    #expect(!FileManager.default.fileExists(atPath: fixture.configuration.record.path))
    #expect(!FileManager.default.fileExists(atPath: fixture.data.appendingPathComponent("engine-ready").path))
    let next = open(lock.path, O_RDWR | O_CLOEXEC)
    defer { close(next) }
    #expect(flock(next, LOCK_EX | LOCK_NB) == 0)
}

@Test func sourceEvidenceAndASecondOwnerCannotStartOrStopAnOwnedEngine() async throws {
    let fixture = try HostFixture()
    defer { fixture.remove() }
    let host = fixture.host()
    try await host.start()
    do {
        try await fixture.waitForEngine()
        let second = fixture.host()
        await #expect(throws: HostProblem.alreadyOwned) { try await second.start() }
        try await second.stop()
        #expect(try OwnedProcess.marked(fixture.token()).count == 1)
        try await host.stop()
        let registration = fixture.data.appendingPathComponent("launcher/installation.json")
        try Data("{}".utf8).write(to: registration)
        await #expect(throws: HostProblem.sourceInstallation) { try await host.start() }
        #expect(!FileManager.default.fileExists(atPath: fixture.configuration.record.path))
    } catch { try? await host.stop(); throw error }
}

@Test func aDatabaseTheAppDidNotMakeIsNeverStarted() async throws {
    let fixture = try HostFixture()
    defer { fixture.remove() }
    try FileManager.default.createDirectory(at: fixture.configuration.pgdata, withIntermediateDirectories: true)
    try Data("17\n".utf8).write(to: fixture.configuration.pgdata.appendingPathComponent("PG_VERSION"))
    let host = fixture.host()
    await #expect(throws: HostProblem.databaseOwnedElsewhere) { try await host.start() }
    #expect(!FileManager.default.fileExists(atPath: fixture.data.appendingPathComponent("engine-ready").path))
    #expect(!FileManager.default.fileExists(atPath: fixture.configuration.record.path))
    try await host.stop()
}

@Test func crashDiagnosticsReadOnlyBoundedLogTails() async throws {
    let fixture = try HostFixture()
    defer { fixture.remove() }
    try FileManager.default.createDirectory(at: fixture.configuration.log.deletingLastPathComponent(), withIntermediateDirectories: true)
    try Data((String(repeating: "old line\n", count: 100000) + "last useful error\n").utf8).write(to: fixture.configuration.log)
    let host = fixture.host()
    let lines = await host.diagnosticLines()
    #expect(lines.contains("last useful error"))
    #expect(lines.split(separator: "\n").count == 41)
    #expect(lines.utf8.count < 16384)
}

@Test(.enabled(if: ProcessInfo.processInfo.environment["ROLEBAND_HOST_TEST_RESOURCES"] != nil,
               "Requires an assembled standalone bundle for the real supervisor and API test"))
func bundledSupervisorServesVerifiedStatusAndQuitLeavesNoEngineProcesses() async throws {
    let resources = URL(fileURLWithPath: try #require(ProcessInfo.processInfo.environment["ROLEBAND_HOST_TEST_RESOURCES"]))
    let encoder = JSONEncoder()
    encoder.outputFormatting = [.withoutEscapingSlashes]
    func literal(_ path: URL) throws -> String { String(decoding: try encoder.encode(path.path), as: UTF8.self) }
    let fixture = try HostFixture(script: """
    import os, runpy, sys
    sys.dont_write_bytecode = True
    os.environ['ROLEBAND_SEARCH_WARM_MODEL_ON_STARTUP'] = '0'
    sys.argv.append('--dry-run-network')
    runpy.run_path(\(try literal(resources.appendingPathComponent("engine/packaged.py"))), run_name='__main__')
    """)
    defer { fixture.remove() }
    try FileManager.default.removeItem(at: fixture.configuration.python)
    try FileManager.default.createSymbolicLink(at: fixture.configuration.python, withDestinationURL: resources.appendingPathComponent("python/bin/python3.12"))
    try FileManager.default.createDirectory(at: fixture.configuration.log.deletingLastPathComponent(), withIntermediateDirectories: true)
    let initialize = """
    import pathlib, sys
    sys.dont_write_bytecode = True
    sys.path.insert(0, \(try literal(resources.appendingPathComponent("engine"))))
    from alembic import command
    from alembic.config import Config
    config = Config(\(try literal(resources.appendingPathComponent("engine/alembic.ini"))))
    config.set_main_option('script_location', \(try literal(resources.appendingPathComponent("engine/alembic"))))
    command.upgrade(config, 'head')
    (pathlib.Path.home() / '.roleband/migrated').write_text('ready')
    """
    let bundle = try #require(Bundle(url: resources.deletingLastPathComponent().deletingLastPathComponent()))
    let installation = try Installation.owned(bundle: bundle, port: 58271)
    let configuration = try HostConfiguration(resources: fixture.configuration.resources, home: fixture.configuration.home, installation: installation)
    let host = EngineHost(configuration: configuration, now: { ProcessInfo.processInfo.systemUptime }, readStatus: StatusClient.read, automatic: false)
    do {
        let setup = try OwnedChild(executable: configuration.python, arguments: ["-I", "-c", initialize],
                                   environment: configuration.environment(token: UUID().uuidString), log: configuration.log)
        let setupDeadline = ProcessInfo.processInfo.systemUptime + 30
        while setup.running() && ProcessInfo.processInfo.systemUptime < setupDeadline { try await Task.sleep(for: .milliseconds(10)) }
        #expect(!setup.running())
        _ = try await fixture.waitFor("migrated")
        try await host.start()
        let deadline = ProcessInfo.processInfo.systemUptime + 20
        while await host.state != .running && ProcessInfo.processInfo.systemUptime < deadline {
            try await host.check()
            try await Task.sleep(for: .milliseconds(100))
        }
        let diagnostics = await host.diagnosticLines()
        if await host.state != .running {
            let bytes = try await LocalHTTP.read(URLRequest(url: installation.target().url))
            let reply = try JSONSerialization.jsonObject(with: bytes) as! [String: Any]
            print("expected identity: \(installation); received: \(String(describing: reply["launcher"]))")
        }
        #expect(await host.state == .running, Comment(rawValue: diagnostics))
        let reply = try await StatusClient.read(installation)
        #expect(reply.installation == installation)
        let token = try fixture.token()
        try await host.stop()
        #expect(try OwnedProcess.marked(token).isEmpty)
        #expect(LaunchMode.runningServer(configuration.pgdata) == nil)
    } catch { try? await host.stop(); throw error }
}

@Test func repeatedStartAndStopAreIdempotentAndReleaseOwnershipForTheNextHost() async throws {
    let fixture = try HostFixture()
    defer { fixture.remove() }
    let host = fixture.host()
    try await host.start()
    do {
        let token = try fixture.token()
        try await host.start()
        #expect(try fixture.token() == token)
        try await host.stop()
        try await host.stop()
        let next = fixture.host()
        try await next.start()
        try await next.stop()
    } catch { try? await host.stop(); throw error }
}

@Test func aReusedPidOrForeignProcessGroupNeverReceivesASignal() throws {
    let own = try #require(OwnedProcess.read(getpid()))
    let stale = OwnedProcess(pid: own.pid, group: own.group, seconds: own.seconds - 1, microseconds: own.microseconds)
    try stale.signal(SIGTERM, group: true)
    #expect(own.isAlive)
    #expect(throws: HostProblem.processInspection) { try own.signal(SIGTERM, group: true) }
}

@Test func anInvalidRecoveryRecordCannotBeBypassedByRetryingOrKeepTheOwnershipLock() async throws {
    let fixture = try HostFixture()
    defer { fixture.remove() }
    try FileManager.default.createDirectory(at: fixture.configuration.record.deletingLastPathComponent(), withIntermediateDirectories: true)
    let bytes = Data("{\"token\":\"not-a-process-owner\"}".utf8)
    try bytes.write(to: fixture.configuration.record)
    try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: fixture.configuration.record.path)
    let host = fixture.host()
    for _ in 0..<2 {
        await #expect(throws: HostProblem.processInspection) { try await host.start() }
    }
    let second = fixture.host()
    await #expect(throws: HostProblem.processInspection) { try await second.start() }
    try await host.stop()
    #expect(try Data(contentsOf: fixture.configuration.record) == bytes)
}

private actor HealthSequence {
    var answers = [true, false, false, true, false, false, false]
    func next(_ installation: Installation) throws -> VerifiedStatus {
        guard answers.removeFirst() else { throw ConnectionProblem.unavailable }
        var identity = try JSONSerialization.jsonObject(with: JSONEncoder().encode(installation)) as! [String: Any]
        identity["status"] = ["observed_at": "2026-10-29T12:00:00Z", "activity": "idle", "attention": [], "model": "ready"]
        return try StatusClient.decode(JSONSerialization.data(withJSONObject: ["db": "ok", "launcher": identity]),
                                       status: 200, installation: installation)
    }
}

@Test func aRunningEngineRequiresThreeConsecutiveFailedHealthReadsBeforeRestarting() async throws {
    let fixture = try HostFixture()
    defer { fixture.remove() }
    let health = HealthSequence()
    let host = EngineHost(configuration: fixture.configuration, now: { 0 }, readStatus: { try await health.next($0) }, automatic: false)
    try await host.start()
    do {
        for _ in 0..<6 {
            try await host.check()
            #expect(await host.state == .running)
        }
        try await host.check()
        #expect(await host.state == .backingOff(until: 1))
        #expect(await host.lastFailure == "engine_unhealthy")
    } catch { try? await host.stop(); throw error }
    try await host.stop()
}

@Test func waitingForAnEngineFileSkipsTheMomentItIsCreatedEmpty() async throws {
    let fixture = try HostFixture(); defer { fixture.remove() }
    try FileManager.default.createDirectory(at: fixture.data, withIntermediateDirectories: true)
    let file = fixture.data.appendingPathComponent("ready.json")
    try Data().write(to: file)
    let writer = Task {
        try await Task.sleep(for: .milliseconds(100))
        try Data("{\"job\": 1}".utf8).write(to: file)
    }
    #expect(try await fixture.waitFor("ready.json") == Data("{\"job\": 1}".utf8))
    try await writer.value
}
