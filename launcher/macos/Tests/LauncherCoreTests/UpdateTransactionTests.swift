import Darwin
import Foundation
import Testing
@testable import LauncherCore

private enum FixtureFailure: Error { case injected }

private final class InstallFixture: @unchecked Sendable {
    let root: URL
    let home: URL
    let candidate: URL
    let paths: UpdateTransactionPaths
    private let lock = NSLock()
    private var events: [String] = []
    private var clock: TimeInterval = 0
    let failure: String

    init(failure: String = "none", database: Bool = true) throws {
        root = FileManager.default.temporaryDirectory.appendingPathComponent("update-install-" + UUID().uuidString)
        home = root.appendingPathComponent("home")
        candidate = root.appendingPathComponent("download/RoleBand.app")
        let installed = home.appendingPathComponent("Applications/RoleBand.app")
        paths = UpdateTransactionPaths(installed: installed, home: home)
        self.failure = failure
        try put("0.1.0", at: installed.appendingPathComponent("version"))
        try put("0.1.1", at: candidate.appendingPathComponent("version"))
        if database {
            try put("16\n", at: HomeLayout(home).database.appendingPathComponent("PG_VERSION"))
            try put("original observation history", at: HomeLayout(home).database.appendingPathComponent("base/history"))
            try put("{\"owner\":\"app\"}", at: HomeLayout(home).data.appendingPathComponent("db.owner.json"))
        }
    }
    func put(_ text: String, at url: URL) throws {
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true,
                                                attributes: [.posixPermissions: 0o700])
        try Data(text.utf8).write(to: url)
    }
    func text(_ path: URL) throws -> String { try String(contentsOf: path, encoding: .utf8) }
    func remove() { try? FileManager.default.removeItem(at: root) }
    func record(_ event: String) { lock.withLock { events.append(event) } }
    var allEvents: [String] { lock.withLock { events } }
    var elapsed: TimeInterval { lock.withLock { clock } }
    var operations: UpdateInstallOperations {
        UpdateInstallOperations(validate: { [self] app, version in
            guard try text(app.appendingPathComponent("version")) == version else { throw FixtureFailure.injected }
            if failure == "invalid-candidate" && version == "0.1.1" { throw FixtureFailure.injected }
        }, stop: { [self] in record("stop") }, launch: { [self] app in
            let version = try text(app.appendingPathComponent("version")); record("launch-" + version)
            if version == "0.1.1" {
                try put("migrated database", at: HomeLayout(home).database.appendingPathComponent("base/history"))
                try put("{\"owner\":\"app\"}", at: HomeLayout(home).data.appendingPathComponent("db.owner.json"))
                if failure == "launch" { throw FixtureFailure.injected }
            } else {
                if FileManager.default.fileExists(atPath: HomeLayout(home).database.path) {
                    #expect(try text(HomeLayout(home).database.appendingPathComponent("base/history")) == "original observation history")
                }
            }
        }, healthy: { [self] _ in
            record("health")
            if failure == "health" { return false }
            if failure == "health-transport" { throw FixtureFailure.injected }
            return true
        }, now: { [self] in lock.withLock { clock } }, pause: { [self] in lock.withLock { clock += 60 } })
    }
}

@Test func healthyUpdateKeepsTheStoppedDatabaseCopyAndPublishesTheNewApp() async throws {
    let f = try InstallFixture(); defer { f.remove() }
    let tx = UpdateTransaction(paths: f.paths, operations: f.operations)
    let result = try await tx.install(candidate: f.candidate, from: "0.1.0", to: "0.1.1")
    let journal = try f.text(f.paths.journal)
    #expect(result == .committed, Comment(rawValue: journal))
    #expect(try f.text(f.paths.installed.appendingPathComponent("version")) == "0.1.1")
    #expect(try f.text(f.paths.backup.appendingPathComponent("base/history")) == "original observation history")
    #expect(try f.text(HomeLayout(f.home).database.appendingPathComponent("base/history")) == "migrated database")
    #expect(f.allEvents == ["stop", "launch-0.1.1", "health"])
    #expect(try await tx.recover() == .committed)
}

@Test(arguments: ["launch", "health", "health-transport"])
func failedUpdateRestoresTheDatabaseBeforeTheOldAppRuns(failure: String) async throws {
    let f = try InstallFixture(failure: failure); defer { f.remove() }
    let tx = UpdateTransaction(paths: f.paths, operations: f.operations)
    #expect(try await tx.install(candidate: f.candidate, from: "0.1.0", to: "0.1.1") == .rolledBack)
    #expect(try f.text(f.paths.installed.appendingPathComponent("version")) == "0.1.0")
    #expect(try f.text(HomeLayout(f.home).database.appendingPathComponent("base/history")) == "original observation history")
    #expect(try f.text(f.paths.failedDatabase.appendingPathComponent("base/history")) == "migrated database")
    #expect(try f.text(f.paths.failedApp.appendingPathComponent("version")) == "0.1.1")
    #expect(f.allEvents.last == "launch-0.1.0")
    let prior = f.allEvents
    #expect(try await tx.recover() == .rolledBack)
    #expect(f.allEvents == prior)
}

@Test func aFailedFirstDatabaseCreationIsMovedAsideBeforeReopeningTheOldApp() async throws {
    let f = try InstallFixture(failure: "health", database: false); defer { f.remove() }
    let tx = UpdateTransaction(paths: f.paths, operations: f.operations)
    #expect(try await tx.install(candidate: f.candidate, from: "0.1.0", to: "0.1.1") == .rolledBack)
    #expect(!FileManager.default.fileExists(atPath: HomeLayout(f.home).database.path))
    #expect(try f.text(f.paths.failedDatabase.appendingPathComponent("base/history")) == "migrated database")
}

@Test(arguments: [InstallPhase.backingUp, .backupReady, .installing, .oldAppMoved, .checking])
func aFailureAtEachJournalBoundaryRestoresAnUsableOriginal(phase: InstallPhase) async throws {
    let f = try InstallFixture(); defer { f.remove() }
    let tx = UpdateTransaction(paths: f.paths, operations: f.operations, checkpoint: {
        if $0 == phase { throw FixtureFailure.injected }
    })
    #expect(try await tx.install(candidate: f.candidate, from: "0.1.0", to: "0.1.1") == .rolledBack)
    #expect(try f.text(f.paths.installed.appendingPathComponent("version")) == "0.1.0")
    #expect(try f.text(HomeLayout(f.home).database.appendingPathComponent("base/history")) == "original observation history")
}

@Test(arguments: ["source", "foreign", "running", "symlink", "downgrade", "invalid-candidate"])
func unsafeInstallationsAreRefusedWithoutRewritingTheirDatabase(problem: String) async throws {
    let f = try InstallFixture(failure: problem); defer { f.remove() }
    switch problem {
    case "source": try f.put("source install", at: HomeLayout(f.home).registration)
    case "foreign": try FileManager.default.removeItem(at: HomeLayout(f.home).data.appendingPathComponent("db.owner.json"))
    case "running": try f.put("123\n", at: HomeLayout(f.home).database.appendingPathComponent("postmaster.pid"))
    case "symlink":
        let link = HomeLayout(f.home).database.appendingPathComponent("external")
        try FileManager.default.createSymbolicLink(at: link, withDestinationURL: f.root)
    default: break
    }
    let tx = UpdateTransaction(paths: f.paths, operations: f.operations)
    if problem == "symlink" {
        #expect(try await tx.install(candidate: f.candidate, from: "0.1.0", to: "0.1.1") == .rolledBack)
    } else if problem == "running" {
        // A refused backup leaves the original installed app and data available.
        await #expect(throws: (any Error).self) { _ = try await tx.install(candidate: f.candidate, from: "0.1.0", to: "0.1.1") }
    } else {
        await #expect(throws: (any Error).self) {
            _ = try await tx.install(candidate: f.candidate, from: "0.1.0", to: problem == "downgrade" ? "0.0.9" : "0.1.1")
        }
    }
    #expect(try f.text(f.paths.installed.appendingPathComponent("version")) == "0.1.0")
    #expect(try f.text(HomeLayout(f.home).database.appendingPathComponent("base/history")) == "original observation history")
    #expect(!f.allEvents.contains("launch-0.1.1"))
}

@Test(arguments: [InstallPhase.oldAppMoved, .checking])
func aNewTransactionInstanceRecoversAnInterruptedReplacementFromItsJournal(phase: InstallPhase) async throws {
    let f = try InstallFixture(); defer { f.remove() }
    let interrupted = UpdateTransaction(paths: f.paths, operations: f.operations, checkpoint: {
        if $0 == phase || $0 == .restoring { throw FixtureFailure.injected }
    })
    await #expect(throws: FixtureFailure.self) {
        _ = try await interrupted.install(candidate: f.candidate, from: "0.1.0", to: "0.1.1")
    }
    let recovered = UpdateTransaction(paths: f.paths, operations: f.operations)
    #expect(try await recovered.recover() == .rolledBack)
    #expect(try f.text(f.paths.installed.appendingPathComponent("version")) == "0.1.0")
    #expect(try f.text(HomeLayout(f.home).database.appendingPathComponent("base/history")) == "original observation history")
}

@Test func aDamagedBackupCannotReplaceTheCurrentDatabaseOrReopenThePreviousApp() async throws {
    let f = try InstallFixture(failure: "health"); defer { f.remove() }
    let interrupted = UpdateTransaction(paths: f.paths, operations: f.operations, checkpoint: {
        if $0 == .restoring { throw FixtureFailure.injected }
    })
    await #expect(throws: FixtureFailure.self) {
        _ = try await interrupted.install(candidate: f.candidate, from: "0.1.0", to: "0.1.1")
    }
    try f.put("damaged backup", at: f.paths.backup.appendingPathComponent("base/history"))
    let recovered = UpdateTransaction(paths: f.paths, operations: f.operations)
    await #expect(throws: InstallProblem.self) { _ = try await recovered.recover() }
    #expect(try f.text(HomeLayout(f.home).database.appendingPathComponent("base/history")) == "migrated database")
    #expect(!f.allEvents.contains("launch-0.1.0"))
}

@Test func aPendingTransactionPreventsStartingAnotherReplacement() async throws {
    let f = try InstallFixture(failure: "health"); defer { f.remove() }
    let interrupted = UpdateTransaction(paths: f.paths, operations: f.operations, checkpoint: {
        if $0 == .restoring { throw FixtureFailure.injected }
    })
    await #expect(throws: FixtureFailure.self) {
        _ = try await interrupted.install(candidate: f.candidate, from: "0.1.0", to: "0.1.1")
    }
    let next = UpdateTransaction(paths: UpdateTransactionPaths(installed: f.paths.installed, home: f.home), operations: f.operations)
    try f.put("0.1.2", at: f.candidate.appendingPathComponent("version"))
    await #expect(throws: (any Error).self) {
        _ = try await next.install(candidate: f.candidate, from: "0.1.1", to: "0.1.2")
    }
    #expect(try f.text(HomeLayout(f.home).database.appendingPathComponent("base/history")) == "migrated database")
}

@Test(.enabled(if: ProcessInfo.processInfo.environment["ROLEBAND_HOST_TEST_RESOURCES"] != nil,
               "Requires the pinned bundled Postgres runtime"))
func rollbackRestoresARealStoppedPostgresSchemaAndItsObservationRows() async throws {
    let f = try InstallFixture(database: false)
    let resources = URL(fileURLWithPath: try #require(ProcessInfo.processInfo.environment["ROLEBAND_HOST_TEST_RESOURCES"]))
    let python = resources.appendingPathComponent("python/bin/python3.12")
    let engine = resources.appendingPathComponent("engine")
    let pgdata = HomeLayout(f.home).database
    let prefix = ["-i", "HOME=" + f.home.path, "PATH=/usr/bin:/bin", "LANG=en_US.UTF-8", "ROLEBAND_PACKAGED=1",
                  "ROLEBAND_DATABASE_URL=", "ROLEBAND_PGDATA=" + pgdata.path, "ROLEBAND_API_PORT=58439",
                  python.path, "-I", "-c"]
    let script = #"""
import pathlib,subprocess,sys
sys.dont_write_bytecode=True
sys.path.insert(0,sys.argv[1])
from tracker.platform.embedded_db import claim_cluster,ensure_server,stop_server
pgdata=pathlib.Path.home()/'.roleband/db'
claim_cluster(pgdata,'app')
server=ensure_server(pgdata,database='roleband',required_extensions=('vector','pg_trgm'))
try:
    result=subprocess.run([str(server.tool('psql')),server.dsn(),'-X','-v','ON_ERROR_STOP=1','-A','-t','-c',sys.argv[2]],check=True,capture_output=True,text=True)
    print(result.stdout)
finally:
    stop_server(pgdata)
"""#
    @Sendable func sql(_ statement: String) async throws -> String {
        let result = try await CommandRunner.run(executable: URL(fileURLWithPath: "/usr/bin/env"),
                                                arguments: prefix + [script, engine.path, statement], timeout: 45)
        #expect(result.exitCode == 0, Comment(rawValue: result.text))
        return result.text.trimmingCharacters(in: .whitespacesAndNewlines)
    }
    defer {
        if FileManager.default.fileExists(atPath: pgdata.appendingPathComponent("postmaster.pid").path) {
            let process = Process()
            process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
            process.arguments = prefix + ["import sys,pathlib;sys.path.insert(0,sys.argv[1]);from tracker.platform.embedded_db import stop_server;stop_server(pathlib.Path.home()/'.roleband/db')", engine.path]
            process.standardOutput = FileHandle.nullDevice; process.standardError = FileHandle.nullDevice
            try? process.run(); process.reap()
        }
        f.remove()
    }
    _ = try await sql("CREATE TABLE observations (id integer PRIMARY KEY, fact text); INSERT INTO observations VALUES (1, 'original');")
    let priorOperations = f.operations
    let operations = UpdateInstallOperations(validate: priorOperations.validate, stop: priorOperations.stop,
        launch: { app in
            if try f.text(app.appendingPathComponent("version")) == "0.1.1" {
                _ = try await sql("ALTER TABLE observations ADD COLUMN upgraded boolean; INSERT INTO observations VALUES (2, 'new', true);")
            } else {
                let rows = try await sql("SELECT string_agg(fact, ',') FROM observations;")
                #expect(rows == "original")
                let columns = try await sql("SELECT count(*) FROM information_schema.columns WHERE table_name='observations';")
                #expect(columns == "2")
            }
        }, healthy: { _ in false }, now: priorOperations.now, pause: priorOperations.pause)
    let transaction = UpdateTransaction(paths: f.paths, operations: operations)
    #expect(try await transaction.install(candidate: f.candidate, from: "0.1.0", to: "0.1.1") == .rolledBack)
    #expect(try await sql("SELECT count(*) FROM observations;") == "1")
    #expect(!FileManager.default.fileExists(atPath: pgdata.appendingPathComponent("postmaster.pid").path))
}

@Test func successfulUpdatesRetainTwoVerifiedBackupsAndPreserveUnmanagedArchives() async throws {
    let f = try InstallFixture(); defer { f.remove() }
    let archive = HomeLayout(f.home).data.appendingPathComponent("backups/unmanaged.dump")
    try f.put("Keep this archive", at: archive)
    let operations = UpdateInstallOperations(validate: f.operations.validate, stop: {}, launch: { _ in }, healthy: { _ in true })
    var from = "0.1.0"
    var copies: [URL] = []
    for to in ["0.1.1", "0.1.2", "0.1.3"] {
        try f.put(to, at: f.candidate.appendingPathComponent("version"))
        let paths = UpdateTransactionPaths(installed: f.paths.installed, home: f.home)
        let transaction = UpdateTransaction(paths: paths, operations: operations)
        #expect(try await transaction.install(candidate: f.candidate, from: from, to: to) == .committed)
        copies.append(paths.backup); from = to
    }
    #expect(!FileManager.default.fileExists(atPath: copies[0].path))
    #expect(FileManager.default.fileExists(atPath: copies[1].path))
    #expect(FileManager.default.fileExists(atPath: copies[2].path))
    #expect(try f.text(archive) == "Keep this archive")
}

@Test func launchTimeCountsAgainstTheTwoMinuteHealthDeadline() async throws {
    let f = try InstallFixture(); defer { f.remove() }
    var operations = f.operations
    let launch = operations.launch, pause = operations.pause
    operations.launch = { app in
        try await launch(app)
        if try f.text(app.appendingPathComponent("version")) == "0.1.1" { try await pause(); try await pause() }
    }
    let tx = UpdateTransaction(paths: f.paths, operations: operations)
    #expect(try await tx.install(candidate: f.candidate, from: "0.1.0", to: "0.1.1") == .rolledBack)
    #expect(!f.allEvents.contains("health"))
}

/// The engine reports that it is preparing its database until `until` seconds after launch, and is
/// healthy from `healthyAt` on.
private func preparingUpdate(until: TimeInterval, healthyAt: TimeInterval?) async throws -> (InstallPhase, TimeInterval) {
    let f = try InstallFixture(); defer { f.remove() }
    var operations = f.operations
    operations.healthy = { _ in healthyAt.map { f.elapsed >= $0 } ?? false }
    operations.preparing = { version in version == "0.1.1" && f.elapsed < until }
    let tx = UpdateTransaction(paths: f.paths, operations: operations)
    let phase = try await tx.install(candidate: f.candidate, from: "0.1.0", to: "0.1.1")
    return (phase, f.elapsed)
}

@Test func aLongDatabaseUpgradeThatReportsProgressIsCommittedNotRolledBack() async throws {
    let (phase, elapsed) = try await preparingUpdate(until: 600, healthyAt: 600)
    #expect(phase == .committed)
    #expect(elapsed == 600)
}

@Test func anUpgradeThatStopsReportingProgressIsRolledBackTwoMinutesAfterItsLastReport() async throws {
    let (phase, elapsed) = try await preparingUpdate(until: 300, healthyAt: nil)
    #expect(phase == .rolledBack)
    #expect(elapsed == 360)
}

@Test func anUpgradeThatNeverFinishesIsRolledBackAtTheCap() async throws {
    let (phase, elapsed) = try await preparingUpdate(until: 100_000, healthyAt: nil)
    #expect(phase == .rolledBack)
    #expect(elapsed >= UpdateTransaction.preparationCap && elapsed < UpdateTransaction.preparationCap + 60)
}

@Test func engineAndInstallationLocksExcludeOtherWritersAtReplacementBoundaries() async throws {
    let f = try InstallFixture(); defer { f.remove() }
    let transaction = UpdateTransaction(paths: f.paths, operations: f.operations, checkpoint: { phase in
        if [.backupReady, .installing, .oldAppMoved].contains(phase) {
            for file in [HomeLayout(f.home).data.appendingPathComponent("launcher/owned-engine.lock"),
                         HomeLayout(f.home).data.appendingPathComponent("updates/install.lock")] {
                let fd = open(file.path, O_RDWR | O_CLOEXEC)
                #expect(fd >= 0)
                if fd >= 0 { #expect(flock(fd, LOCK_EX | LOCK_NB) != 0); close(fd) }
            }
        }
    })
    #expect(try await transaction.install(candidate: f.candidate, from: "0.1.0", to: "0.1.1") == .committed)
}

private actor TransactionPause {
    var entered = false
    private var continuation: CheckedContinuation<Void, Never>?
    func wait() async {
        await withCheckedContinuation { continuation in self.continuation = continuation; entered = true }
    }
    func release() { continuation?.resume(); continuation = nil }
}

@Test func cancellationAfterReplacementFinishesRollbackBeforeReturning() async throws {
    let f = try InstallFixture(failure: "health"); defer { f.remove() }
    let pause = TransactionPause()
    var operations = f.operations
    operations.pause = { await pause.wait() }
    let tx = UpdateTransaction(paths: f.paths, operations: operations)
    let task = Task { try await tx.install(candidate: f.candidate, from: "0.1.0", to: "0.1.1") }
    let deadline = ContinuousClock.now.advanced(by: .seconds(5))
    while await !pause.entered && ContinuousClock.now < deadline { await Task.yield() }
    guard await pause.entered else {
        task.cancel(); await pause.release(); _ = try? await task.value
        Issue.record("The transaction never reached its health pause"); return
    }
    task.cancel(); await pause.release()
    #expect(try await task.value == .rolledBack)
    #expect(try f.text(HomeLayout(f.home).database.appendingPathComponent("base/history")) == "original observation history")
    #expect(f.allEvents.last == "launch-0.1.0")
}

@Test func theHelperOutwaitsTheEnginesOwnLimitOnPreparingItsDatabase() throws {
    let prepare = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
        .appendingPathComponent("../../../../backend/tracker/supervisor/prepare.py").standardizedFileURL
    let source = try String(contentsOf: prepare, encoding: .utf8)
    let line = try #require(source.split(separator: "\n").first { $0.hasPrefix("PREPARE_TIMEOUT_SECONDS = ") })
    let engineLimit = try #require(TimeInterval(line.dropFirst("PREPARE_TIMEOUT_SECONDS = ".count)))
    #expect(UpdateTransaction.preparationCap == engineLimit + UpdateTransaction.healthWait)
}
