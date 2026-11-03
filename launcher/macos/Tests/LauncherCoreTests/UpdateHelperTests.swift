import Darwin
import Foundation
import Testing
@testable import LauncherCore

private enum HelperFailure: Error { case injected }

private actor Gate {
    private(set) var entered = false
    private var continuation: CheckedContinuation<Void, Never>?
    func wait() async {
        await withCheckedContinuation { continuation in self.continuation = continuation; entered = true }
    }
    func open() { continuation?.resume(); continuation = nil }
}

/// A scratch home with an installed app, a staged candidate and a plan whose parent is a real process.
private final class HelperFixture: @unchecked Sendable {
    let root: URL
    let home: URL
    let installed: URL
    let parent: Process
    let plan: UpdatePlan
    private let lock = NSLock()
    private var events: [String] = []
    private var clock: TimeInterval = 0
    var healthy = true
    var refuseCandidate = false
    var watchLease = false
    var health: Gate?

    init(parentSeconds: String = "0.3") throws {
        root = FileManager.default.temporaryDirectory.appendingPathComponent("update-helper-" + UUID().uuidString)
        home = root.appendingPathComponent("home")
        installed = home.appendingPathComponent("Applications/RoleBand.app")
        parent = Process()
        parent.executableURL = URL(fileURLWithPath: "/bin/sleep")
        parent.arguments = [parentSeconds]
        try parent.run()
        let trust = InstalledUpdateIdentity(version: "0.1.0", commit: String(repeating: "a", count: 40),
                                            publicKey: Data(repeating: 7, count: 32), certificateSHA256: String(repeating: "c", count: 64))
        plan = try UpdatePlan(id: UUID(), installed: installed, home: home, trust: trust, to: "0.1.1",
                              toCommit: String(repeating: "b", count: 40), parent: parent.processIdentifier)
        try put("0.1.0", at: installed.appendingPathComponent("version"))
        try put("0.1.1", at: plan.candidate.appendingPathComponent("version"))
        try put("16\n", at: database.appendingPathComponent("PG_VERSION"))
        try put("original observation history", at: database.appendingPathComponent("base/history"))
        try put("{\"owner\":\"app\"}", at: HomeLayout(home).data.appendingPathComponent("db.owner.json"))
        try plan.save()
    }

    var database: URL { HomeLayout(home).database }
    var allEvents: [String] { lock.withLock { events } }
    func record(_ event: String) { lock.withLock { events.append(event) } }
    func put(_ text: String, at url: URL) throws {
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true,
                                                attributes: [.posixPermissions: 0o700])
        try Data(text.utf8).write(to: url)
    }
    func text(_ url: URL) throws -> String { try String(contentsOf: url, encoding: .utf8) }
    func exists(_ url: URL) -> Bool { FileManager.default.fileExists(atPath: url.path) }
    func remove() {
        parent.stopAndReap()
        try? FileManager.default.removeItem(at: root)
    }

    var operations: UpdateInstallOperations {
        UpdateInstallOperations(validate: { [self] app, version in
            guard try text(app.appendingPathComponent("version")) == version else { throw HelperFailure.injected }
            if refuseCandidate && version == "0.1.1" { throw HelperFailure.injected }
        }, stop: { [self] in
            record(parent.isRunning ? "stop-while-parent-runs" : "stop")
        }, launch: { [self] app in
            let version = try text(app.appendingPathComponent("version"))
            if watchLease && HelperLease.held(plan.paths.directory) { record("launch-under-lease") }
            record("launch-" + version)
            if version == "0.1.1" { try put("migrated database", at: database.appendingPathComponent("base/history")) }
        }, healthy: { [self] _ in
            if let health { await health.wait() }
            return healthy
        }, now: { [self] in lock.withLock { clock } }, pause: { [self] in lock.withLock { clock += 60 } })
    }

    func helper(timeout: TimeInterval = 10) -> UpdateHelper {
        UpdateHelper(plan: plan, operations: operations, parentTimeout: timeout, pause: { try await Task.sleep(for: .milliseconds(20)) })
    }
}

@Test func theHelperWaitsForTheQuittingAppThenCommitsAndDropsOnlyAppCopies() async throws {
    let f = try HelperFixture(parentSeconds: "0.5"); defer { f.remove() }
    #expect(await f.helper().apply() == .committed)
    #expect(f.allEvents == ["stop", "launch-0.1.1"])
    #expect(try f.text(f.installed.appendingPathComponent("version")) == "0.1.1")
    #expect(try f.text(f.plan.paths.backup.appendingPathComponent("base/history")) == "original observation history")
    #expect(!f.exists(f.plan.paths.stage))
    #expect(!f.exists(f.plan.candidate.deletingLastPathComponent()))
    #expect(try UpdateTransaction.journal(f.plan.paths)?.phase == .committed)
}

@Test func anAppThatNeverQuitsIsLeftExactlyAsItWas() async throws {
    let f = try HelperFixture(parentSeconds: "30"); defer { f.remove() }
    #expect(await f.helper(timeout: 0.3).apply() == .parentRunning)
    #expect(f.allEvents.isEmpty)
    #expect(try f.text(f.installed.appendingPathComponent("version")) == "0.1.0")
    #expect(try UpdateTransaction.journal(f.plan.paths) == nil)
}

@Test func anUnhealthyVersionIsRolledBackAndOnlyItsAppCopyIsDropped() async throws {
    let f = try HelperFixture(); defer { f.remove() }
    f.healthy = false
    #expect(await f.helper().apply() == .rolledBack)
    #expect(f.allEvents.last == "launch-0.1.0")
    let journal = try JSONSerialization.jsonObject(with: Data(contentsOf: f.plan.paths.journal)) as? [String: Any]
    #expect(journal?["failure"] as? String == "healthTimeout")
    #expect(try f.text(f.installed.appendingPathComponent("version")) == "0.1.0")
    #expect(try f.text(f.database.appendingPathComponent("base/history")) == "original observation history")
    #expect(try f.text(f.plan.paths.failedDatabase.appendingPathComponent("base/history")) == "migrated database")
    #expect(!f.exists(f.plan.paths.stage))
    #expect(!f.exists(f.plan.candidate.deletingLastPathComponent()))
}

@Test func aCandidateRefusedBeforeReplacementReopensTheUntouchedApp() async throws {
    let f = try HelperFixture(); defer { f.remove() }
    f.refuseCandidate = true
    #expect(await f.helper().apply() == .unchanged)
    #expect(f.allEvents == ["launch-0.1.0"])
    #expect(try f.text(f.installed.appendingPathComponent("version")) == "0.1.0")
    #expect(try f.text(f.database.appendingPathComponent("base/history")) == "original observation history")
    #expect(try UpdateTransaction.journal(f.plan.paths) == nil)
    #expect(!f.exists(f.plan.paths.stage))
}

@Test func recoveryFinishesAnUpdateWhoseHelperDiedMidReplacement() async throws {
    let f = try HelperFixture(); defer { f.remove() }
    let interrupted = UpdateTransaction(paths: f.plan.paths, operations: f.operations, checkpoint: {
        if $0 == .oldAppMoved || $0 == .restoring { throw HelperFailure.injected }
    })
    await #expect(throws: HelperFailure.self) {
        _ = try await interrupted.install(candidate: f.plan.candidate, from: "0.1.0", to: "0.1.1")
    }
    #expect(!f.exists(f.installed))
    #expect(UpdateStartup.decide(installed: f.installed, home: f.home, version: "0.1.0") == .recover(f.plan.id))
    #expect(await f.helper().recover() == .rolledBack)
    #expect(f.allEvents.last == "launch-0.1.0")
    #expect(try f.text(f.installed.appendingPathComponent("version")) == "0.1.0")
    #expect(try f.text(f.database.appendingPathComponent("base/history")) == "original observation history")
    #expect(!f.exists(f.plan.paths.stage))
    #expect(UpdateStartup.decide(installed: f.installed, home: f.home, version: "0.1.0") == .proceed)
}

@Test func aRecoveryThatCannotTrustItsBackupLeavesTheDataAndReopensTheAppOnlyToSaySo() async throws {
    let f = try HelperFixture(); defer { f.remove() }
    f.healthy = false
    let interrupted = UpdateTransaction(paths: f.plan.paths, operations: f.operations, checkpoint: {
        if $0 == .restoring { throw HelperFailure.injected }
    })
    await #expect(throws: HelperFailure.self) {
        _ = try await interrupted.install(candidate: f.plan.candidate, from: "0.1.0", to: "0.1.1")
    }
    try f.put("damaged backup", at: f.plan.paths.backup.appendingPathComponent("base/history"))
    let before = f.allEvents
    f.watchLease = true
    #expect(await f.helper().recover() == .needsAttention)
    let after = Array(f.allEvents.dropFirst(before.count))
    #expect(after.filter { $0.hasPrefix("launch") } == ["launch-0.1.1"])
    #expect(after.last == "launch-0.1.1")
    #expect(try f.text(f.database.appendingPathComponent("base/history")) == "migrated database")
    // The reopened app finds the recorded failure, so it shows the stopped update and starts no engine.
    #expect(UpdateStartup.decide(installed: f.installed, home: f.home, version: "0.1.0") == .recoveryFailed(f.plan.id))
}

@Test func aRecoveryThatFailedIsShownAtTheNextOpenUntilATryFinishesIt() async throws {
    let f = try HelperFixture(); defer { f.remove() }
    f.healthy = false
    let interrupted = UpdateTransaction(paths: f.plan.paths, operations: f.operations, checkpoint: {
        if $0 == .restoring { throw HelperFailure.injected }
    })
    await #expect(throws: HelperFailure.self) {
        _ = try await interrupted.install(candidate: f.plan.candidate, from: "0.1.0", to: "0.1.1")
    }
    #expect(UpdateStartup.decide(installed: f.installed, home: f.home, version: "0.1.0") == .recover(f.plan.id))
    let backup = f.plan.paths.backup.appendingPathComponent("base/history")
    let kept = try f.text(backup)
    try f.put("damaged backup", at: backup)
    #expect(await f.helper().recover() == .needsAttention)
    #expect(UpdateStartup.decide(installed: f.installed, home: f.home, version: "0.1.0") == .recoveryFailed(f.plan.id))
    #expect(UpdateStartup.decide(installed: f.installed, home: f.home, version: "0.1.1") == .recoveryFailed(f.plan.id))

    try f.put(kept, at: backup)
    #expect(await f.helper().recover() == .rolledBack)
    #expect(try f.text(f.database.appendingPathComponent("base/history")) == "original observation history")
    #expect(!f.exists(f.plan.paths.recoveryFailed))
    #expect(UpdateStartup.decide(installed: f.installed, home: f.home, version: "0.1.0") == .proceed)
}

@Test func aSecondHelperForTheSameUpdateStandsAside() async throws {
    let f = try HelperFixture(); defer { f.remove() }
    let first = try HelperLease(f.plan.paths.directory)
    #expect(await f.helper().apply() == .busy)
    #expect(f.allEvents.isEmpty)
    withExtendedLifetime(first) {}
}

@Test func aLaunchDuringAHealthCheckLeavesTheUpdateToItsHelper() async throws {
    let f = try HelperFixture(); defer { f.remove() }
    let gate = Gate()
    f.health = gate
    let lease = try HelperLease(f.plan.paths.directory)
    let transaction = UpdateTransaction(paths: f.plan.paths, operations: f.operations)
    let update = Task { try await transaction.install(candidate: f.plan.candidate, from: "0.1.0", to: "0.1.1") }
    let deadline = ContinuousClock.now.advanced(by: .seconds(5))
    while await !gate.entered && ContinuousClock.now < deadline { try await Task.sleep(for: .milliseconds(10)) }
    guard await gate.entered else { update.cancel(); await gate.open(); _ = try? await update.value; Issue.record("No health check"); return }
    // The version under check starts its engine; anything else waits for the helper.
    #expect(UpdateStartup.decide(installed: f.installed, home: f.home, version: "0.1.1") == .proceed)
    #expect(UpdateStartup.decide(installed: f.installed, home: f.home, version: "0.1.0") == .helperAtWork)
    #expect(UpdateStartup.decide(installed: f.home.appendingPathComponent("Applications/Other.app"), home: f.home,
                                 version: "0.1.1") == .helperAtWork)
    withExtendedLifetime(lease) {}
    await gate.open()
    #expect(try await update.value == .committed)
    #expect(UpdateStartup.decide(installed: f.installed, home: f.home, version: "0.1.1") == .proceed)
}

@Test func aPendingUpdateWithoutAHelperIsRecoveredBeforeAnyEngineStarts() async throws {
    let f = try HelperFixture(); defer { f.remove() }
    let gate = Gate()
    f.health = gate
    let transaction = UpdateTransaction(paths: f.plan.paths, operations: f.operations)
    let update = Task { try await transaction.install(candidate: f.plan.candidate, from: "0.1.0", to: "0.1.1") }
    let deadline = ContinuousClock.now.advanced(by: .seconds(5))
    while await !gate.entered && ContinuousClock.now < deadline { try await Task.sleep(for: .milliseconds(10)) }
    // The same journal phase, but no helper holds its lease: even the new version must not start.
    #expect(UpdateStartup.decide(installed: f.installed, home: f.home, version: "0.1.1") == .recover(f.plan.id))
    await gate.open()
    _ = try await update.value
}

@Test func aPlanNobodyRunsIsIgnoredButAWaitingHelperIsNot() async throws {
    let f = try HelperFixture(); defer { f.remove() }
    let elsewhere = FileManager.default.temporaryDirectory.appendingPathComponent("update-empty-" + UUID().uuidString)
    #expect(UpdateStartup.decide(installed: f.installed, home: elsewhere, version: "0.1.0") == .proceed)
    #expect(UpdateStartup.decide(installed: f.installed, home: f.home, version: "0.1.0") == .proceed)
    let lease = try HelperLease(f.plan.paths.directory)
    #expect(UpdateStartup.decide(installed: f.installed, home: f.home, version: "0.1.0") == .helperAtWork)
    withExtendedLifetime(lease) {}
}

@Test func anUnfinishedJournalForAnotherAppLocationStartsNothing() async throws {
    let f = try HelperFixture(); defer { f.remove() }
    let other = URL(fileURLWithPath: "/Applications/RoleBand.app")
    #expect(await f.helper().apply() == .committed)
    // A finished update recorded for another app location does not block this one.
    #expect(UpdateStartup.decide(installed: other, home: f.home, version: "0.1.1") == .proceed)
    let paths = UpdateTransactionPaths(installed: f.installed, home: f.home)
    let interrupted = UpdateTransaction(paths: paths, operations: f.operations,
                                        checkpoint: { if $0 == .oldAppMoved || $0 == .restoring { throw HelperFailure.injected } })
    try f.put("0.1.2", at: f.plan.candidate.appendingPathComponent("version"))
    await #expect(throws: HelperFailure.self) {
        _ = try await interrupted.install(candidate: f.plan.candidate, from: "0.1.1", to: "0.1.2")
    }
    #expect(UpdateStartup.decide(installed: other, home: f.home, version: "0.1.1") == .untrustedJournal(paths.id))
    #expect(UpdateStartup.decide(installed: f.installed, home: f.home, version: "0.1.1") == .recover(paths.id))
}

@Test func anUnreadableJournalStartsNothing() async throws {
    let f = try HelperFixture(); defer { f.remove() }
    let journal = f.plan.paths.journal
    try f.put("{not json", at: journal)
    try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: journal.path)
    #expect(UpdateStartup.decide(installed: f.installed, home: f.home, version: "0.1.0") == .untrustedJournal(f.plan.id))
    try FileManager.default.setAttributes([.posixPermissions: 0o644], ofItemAtPath: journal.path)
    try f.put("{}", at: journal)
    #expect(UpdateStartup.decide(installed: f.installed, home: f.home, version: "0.1.0") == .untrustedJournal(f.plan.id))
}

@Test func plansLoadOnlyFromTheirOwnPrivateFolder() async throws {
    let f = try HelperFixture(); defer { f.remove() }
    #expect(try UpdatePlan.load(home: f.home, id: f.plan.id) == f.plan)
    #expect(throws: UpdateHelperProblem.self) { try UpdatePlan.load(home: f.home, id: UUID()) }
    let copied = UpdateTransactionPaths(installed: f.installed, home: f.home, id: UUID()).directory
    try FileManager.default.createDirectory(at: copied, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
    try FileManager.default.copyItem(at: f.plan.file, to: copied.appendingPathComponent("plan.json"))
    #expect(throws: UpdateHelperProblem.self) { try UpdatePlan.load(home: f.home, id: UUID(uuidString: copied.lastPathComponent)!) }
    try FileManager.default.setAttributes([.posixPermissions: 0o644], ofItemAtPath: f.plan.file.path)
    #expect(throws: UpdateHelperProblem.self) { try UpdatePlan.load(home: f.home, id: f.plan.id) }
    let outside = f.root.appendingPathComponent("Downloads/RoleBand.app")
    #expect(throws: UpdateHelperProblem.self) {
        _ = try UpdatePlan(id: UUID(), installed: outside, home: f.home, trust: f.plan.trust, to: "0.1.1",
                           toCommit: f.plan.toCommit, parent: getpid())
    }
    #expect(throws: UpdateHelperProblem.self) {
        _ = try UpdatePlan(id: UUID(), installed: f.installed, home: f.home, trust: f.plan.trust, to: "0.0.9",
                           toCommit: f.plan.toCommit, parent: getpid())
    }
}

@Test func aLaunchedAppIsAskedToQuitThenKilledWhenItIgnoresTheRequest() async throws {
    let polite = Process()
    polite.executableURL = URL(fileURLWithPath: "/bin/sleep"); polite.arguments = ["30"]
    try polite.run()
    let stubborn = Process()
    stubborn.executableURL = URL(fileURLWithPath: "/usr/bin/perl")
    stubborn.arguments = ["-e", "$SIG{TERM}='IGNORE'; sleep 30"]
    try stubborn.run()
    defer { for process in [polite, stubborn] where process.isRunning { kill(process.processIdentifier, SIGKILL) } }
    try await Task.sleep(for: .milliseconds(300))
    let app = LaunchedApp(grace: 0.5)
    await app.track(polite.processIdentifier)
    let started = ContinuousClock.now
    try await app.stop()
    polite.reap()
    #expect(polite.terminationReason == .uncaughtSignal && polite.terminationStatus == SIGTERM)
    #expect(ContinuousClock.now - started < .milliseconds(450))
    await app.track(stubborn.processIdentifier)
    try await app.stop()
    stubborn.reap()
    #expect(stubborn.terminationStatus == SIGKILL)
}

@Test func theHelperRunsInItsOwnSessionWithOnlyTheEnvironmentItIsGiven() async throws {
    let root = FileManager.default.temporaryDirectory.appendingPathComponent("helper-spawn-" + UUID().uuidString)
    let home = root.appendingPathComponent("home")
    try FileManager.default.createDirectory(at: home, withIntermediateDirectories: true)
    defer { try? FileManager.default.removeItem(at: root) }
    let script = root.appendingPathComponent("helper.sh")
    try Data("#!/bin/sh\necho \"$1 $2\" > \"$HOME/args\"\nenv > \"$HOME/env\"\nps -o pgid= -p $$ | tr -d ' ' > \"$HOME/group\"\necho $$ > \"$HOME/pid\"\n".utf8)
        .write(to: script)
    try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: script.path)
    setenv(OwnedProcess.marker, "inherited", 1)
    defer { unsetenv(OwnedProcess.marker) }
    let id = UUID()
    try UpdateHelperProcess.spawn(executable: script, recovering: true, id: id, home: home)
    let deadline = ContinuousClock.now.advanced(by: .seconds(5))
    while !FileManager.default.fileExists(atPath: home.appendingPathComponent("pid").path) && ContinuousClock.now < deadline {
        try await Task.sleep(for: .milliseconds(20))
    }
    let read = { (name: String) in try String(contentsOf: home.appendingPathComponent(name), encoding: .utf8).trimmingCharacters(in: .whitespacesAndNewlines) }
    #expect(try read("args") == "--recover-update \(id.uuidString)")
    #expect(try read("group") == read("pid"))
    let environment = try read("env")
    #expect(environment.contains("HOME=\(home.path)"))
    #expect(!environment.contains(OwnedProcess.marker))
    #expect(FileManager.default.fileExists(atPath: HomeLayout(home).data.appendingPathComponent("logs/update-helper.log").path))
}

@Test func aPreparationThatFailsItsImageCheckLeavesNoUpdateFolder() async throws {
    let f = try HelperFixture(); defer { f.remove() }
    let image = f.root.appendingPathComponent("RoleBand-0.1.1-macOS-arm64.dmg")
    try f.put("not the signed image", at: image)
    let artifact = VerifiedArtifact(version: "0.1.1", commit: String(repeating: "b", count: 40), imageName: image.lastPathComponent,
                                    bytes: 20, sha256: String(repeating: "0", count: 64))
    let updates = HomeLayout(f.home).data.appendingPathComponent("updates")
    let before = Set(try FileManager.default.contentsOfDirectory(atPath: updates.path))
    await #expect(throws: ArtifactProblem.invalidImage) {
        _ = try await UpdatePlan.prepare(DownloadedUpdate(artifact: artifact, image: image), installed: f.installed, home: f.home)
    }
    #expect(Set(try FileManager.default.contentsOfDirectory(atPath: updates.path)) == before)
    #expect(try f.text(f.installed.appendingPathComponent("version")) == "0.1.0")
}

@Test func theFirstOpenAfterwardsLearnsWhetherItsUpdateCommittedOrRolledBack() async throws {
    let updated = try HelperFixture(); defer { updated.remove() }
    #expect(UpdateNotice.latest(installed: updated.installed, home: updated.home, version: "0.1.1") == nil)
    #expect(await updated.helper().apply() == .committed)
    #expect(UpdateNotice.latest(installed: updated.installed, home: updated.home, version: "0.1.1")
            == UpdateNotice(id: updated.plan.id, kind: .updated, from: "0.1.0", to: "0.1.1"))
    #expect(UpdateNotice.latest(installed: updated.installed, home: updated.home, version: "0.1.0") == nil)
    let other = updated.home.appendingPathComponent("Applications/Other.app")
    #expect(UpdateNotice.latest(installed: other, home: updated.home, version: "0.1.1") == nil)

    let failed = try HelperFixture(); defer { failed.remove() }
    failed.healthy = false
    #expect(await failed.helper().apply() == .rolledBack)
    #expect(UpdateNotice.latest(installed: failed.installed, home: failed.home, version: "0.1.0")
            == UpdateNotice(id: failed.plan.id, kind: .rolledBack, from: "0.1.0", to: "0.1.1"))
    #expect(UpdateNotice.latest(installed: failed.installed, home: failed.home, version: "0.1.1") == nil)
}

@Test func onlyPlansNoHelperEverTouchedAreDiscardedOnceTheyAreOld() async throws {
    let f = try HelperFixture(); defer { f.remove() }
    let later = Date().addingTimeInterval(3600)
    UpdatePlan.discardAbandoned(home: f.home, now: Date())
    #expect(f.exists(f.plan.candidate))
    do {
        let lease = try HelperLease(f.plan.paths.directory)
        UpdatePlan.discardAbandoned(home: f.home, now: later)
        #expect(f.exists(f.plan.candidate))
        withExtendedLifetime(lease) {}
    }
    UpdatePlan.discardAbandoned(home: f.home, now: later)
    #expect(!f.exists(f.plan.paths.directory))
    #expect(try f.text(f.installed.appendingPathComponent("version")) == "0.1.0")

    let failed = try HelperFixture(); defer { failed.remove() }
    failed.healthy = false
    #expect(await failed.helper().apply() == .rolledBack)
    UpdatePlan.discardAbandoned(home: failed.home, now: later)
    #expect(try failed.text(failed.plan.paths.failedDatabase.appendingPathComponent("base/history")) == "migrated database")
    #expect(try UpdateTransaction.journal(failed.plan.paths)?.phase == .rolledBack)
}

@Test func aRetryHandOffKeepsTheWaitingHelperWaitingPastItsOwnDeadline() async throws {
    // The helper alone gives up 0.5 s in. A Retry hands the same plan over again at 0.3 s and the app
    // quits at 0.6 s, so only a helper whose wait restarted at the Retry is still there to install.
    // Both happen inside the helper's own pauses, so a busy machine cannot reorder them.
    let f = try HelperFixture(parentSeconds: "30"); defer { f.remove() }
    try f.plan.markHandOff()
    let step = Steps()
    let start = ProcessInfo.processInfo.systemUptime
    let helper = UpdateHelper(plan: f.plan, operations: f.operations, parentTimeout: 0.5, pause: {
        try await Task.sleep(for: .milliseconds(20))
        let elapsed = ProcessInfo.processInfo.systemUptime - start
        if step.next(when: elapsed >= 0.3, from: 0) { try f.plan.markHandOff() }
        else if step.next(when: elapsed >= 0.6, from: 1) { f.parent.terminate(); f.parent.waitUntilExit() }
    })
    #expect(await helper.apply() == .committed)
    #expect(step.count == 2)
    #expect(try f.text(f.installed.appendingPathComponent("version")) == "0.1.1")
}

private final class Steps: @unchecked Sendable {
    private let lock = NSLock()
    private var taken = 0
    var count: Int { lock.withLock { taken } }
    /// Takes step `from` once `ready` holds, so each step runs in its own pause, in order.
    func next(when ready: Bool, from: Int) -> Bool {
        lock.withLock {
            guard ready, taken == from else { return false }
            taken += 1; return true
        }
    }
}

@Test func withoutAnotherHandOffTheHelperStillGivesUpOnAnAppThatNeverQuits() async throws {
    let f = try HelperFixture(parentSeconds: "30"); defer { f.remove() }
    try f.plan.markHandOff()
    #expect(await f.helper(timeout: 0.3).apply() == .parentRunning)
    #expect(try f.text(f.installed.appendingPathComponent("version")) == "0.1.0")
}

@Test func aPlanFromBeforeSpareKeysStillLoadsAndARecordedSpareMustDifferFromTheCurrentKey() throws {
    let f = try HelperFixture(); defer { f.remove() }
    let file = f.plan.paths.directory.appendingPathComponent("plan.json")
    var object = try JSONSerialization.jsonObject(with: Data(contentsOf: file)) as! [String: Any]
    #expect(object["spareKey"] == nil)
    #expect(try UpdatePlan.load(home: f.home, id: f.plan.id).spareKey == nil)
    #expect(try UpdatePlan.load(home: f.home, id: f.plan.id).signingRule == nil)
    object["signingRule"] = "certificate leaf = H\"A1\""
    try PrivateFiles.write(try JSONSerialization.data(withJSONObject: object), to: file)
    #expect(try UpdatePlan.load(home: f.home, id: f.plan.id).trust.signingRule == "certificate leaf = H\"A1\"")
    object["signingRule"] = ""
    try PrivateFiles.write(try JSONSerialization.data(withJSONObject: object), to: file)
    #expect(throws: UpdateHelperProblem.invalidPlan) { _ = try UpdatePlan.load(home: f.home, id: f.plan.id) }
    object.removeValue(forKey: "signingRule")
    for (spare, accepted) in [(Data(repeating: 8, count: 32), true), (Data(repeating: 7, count: 32), false)] {
        object["spareKey"] = spare.base64EncodedString()
        try PrivateFiles.write(try JSONSerialization.data(withJSONObject: object), to: file)
        if accepted { #expect(try UpdatePlan.load(home: f.home, id: f.plan.id).trust.trustedKeys.last == spare) }
        else { #expect(throws: UpdateHelperProblem.invalidPlan) { _ = try UpdatePlan.load(home: f.home, id: f.plan.id) } }
    }
}
