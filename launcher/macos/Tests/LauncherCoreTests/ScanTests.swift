import Foundation
import Testing
@testable import LauncherCore

final class LocalEngineFixture {
    let process = Process()
    let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    let installation: Installation
    var registration: URL { root.appendingPathComponent("installation.json") }
    init(_ mode: String) throws {
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: false)
        let fixture = URL(fileURLWithPath: #filePath).deletingLastPathComponent().appendingPathComponent("Fixtures/scan-server.py")
        let output = Pipe()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
        process.arguments = [fixture.path, mode, root.path]
        process.standardOutput = output
        try process.run()
        var data = Data()
        while let byte = try output.fileHandleForReading.read(upToCount: 1), !byte.isEmpty, byte != Data([10]) { data.append(byte) }
        let origin = try #require(String(data: data, encoding: .utf8))
        installation = try JSONDecoder().decode(Installation.self, from: JSONSerialization.data(withJSONObject: [
            "product": "roleband", "instance": "0123456789abcdef01234567", "api_origin": origin, "version": "0.1.0", "format": 1,
        ]))
        try JSONEncoder().encode(installation).write(to: registration)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: registration.path)
    }
    func requests() throws -> [[String: String]] {
        let path = root.appendingPathComponent("requests.jsonl")
        guard FileManager.default.fileExists(atPath: path.path) else { return [] }
        return try String(contentsOf: path, encoding: .utf8).split(separator: "\n").map {
            try JSONDecoder().decode([String: String].self, from: Data($0.utf8))
        }
    }
    deinit {
        process.stopAndReap()
        try? FileManager.default.removeItem(at: root)
    }
}

@Test(arguments: ["ready", "manual", "queued"])
func scanControlsUseTheVerifiedOriginJSONAndTheCorrectRoute(mode: String) async throws {
    let server = try LocalEngineFixture(mode)
    let action: ScanAction = mode == "ready" ? .start : .stop
    let outcome = try await ScanClient.perform(action, installation: server.installation, source: .registration(server.registration))
    #expect(outcome == (action == .start ? .requested : .stopRequested))
    let sent = try #require(server.requests().first)
    #expect(try server.requests().count == 1)
    #expect(sent["path"] == (action == .start ? "/api/sync" : "/api/sync/cancel"))
    #expect(sent["body"] == "{}")
    #expect(sent["content_type"] == "application/json")
    #expect(sent["origin"] == server.installation.apiOrigin)
}

@Test func aStopTheEngineAnswersOnlyAfterItsFullWaitIsStillConfirmed() async throws {
    let server = try LocalEngineFixture("stop_slow")
    let outcome = try await ScanClient.perform(.stop, installation: server.installation, source: .registration(server.registration))
    #expect(outcome == .stopRequested)
    #expect(try server.requests().map { $0["path"] } == ["/api/sync/cancel"])
}

@Test(arguments: ["held", "scheduled", "legacy", "mismatch", "replacement"])
func aFreshHoldScheduledRunMissingControlFactsOrWrongIdentityPreventsAllWrites(mode: String) async throws {
    let server = try LocalEngineFixture(mode)
    for action in [ScanAction.start, .stop] {
        await #expect(throws: (any Error).self) {
            try await ScanClient.perform(action, installation: server.installation, source: .registration(server.registration))
        }
    }
    #expect(try server.requests().isEmpty)
}

@Test(arguments: ["redirect", "stop_redirect", "refused", "invalid", "stop_error"])
func refusedRedirectedOrAmbiguousWritesNeverBecomeSuccessOrAutomaticRetries(mode: String) async throws {
    let server = try LocalEngineFixture(mode)
    let action: ScanAction = mode.hasPrefix("stop_") ? .stop : .start
    await #expect(throws: (any Error).self) {
        try await ScanClient.perform(action, installation: server.installation, source: .registration(server.registration))
    }
    let requests = try server.requests()
    #expect(requests.count == 1)
    #expect(!requests.contains { $0["path"] == "/unexpected" })
}

@Test func stoppingDoesNotClaimTheRunHasAlreadyEndedAndUnknownRepliesFailClosed() throws {
    #expect(try ScanClient.decode(Data(#"{"status":"cancelled"}"#.utf8), action: .stop) == .stopRequested)
    #expect(try ScanClient.decode(Data(#"{"status":"not_running"}"#.utf8), action: .stop) == .notRunning)
    #expect(try ScanClient.decode(Data(#"{"status":"already_running"}"#.utf8), action: .start) == .alreadyRunning)
    #expect(throws: ConnectionProblem.invalidResponse) {
        try ScanClient.decode(Data(#"{"status":"started"}"#.utf8), action: .stop)
    }
}

@Test func theAppsOwnEngineNeedsNoRegistrationFileAndAnotherIdentityIsRefused() async throws {
    let server = try LocalEngineFixture("ready")
    try FileManager.default.removeItem(at: server.registration)
    let other = try JSONDecoder().decode(Installation.self, from: JSONSerialization.data(withJSONObject: [
        "product": "roleband", "instance": "fedcba9876543210fedcba98", "api_origin": server.installation.apiOrigin,
        "version": "0.1.0", "format": 1,
    ]))
    await #expect(throws: ConnectionProblem.identityMismatch) {
        try await ScanClient.perform(.start, installation: server.installation, source: .fixed(other))
    }
    #expect(try server.requests().isEmpty)
    let outcome = try await ScanClient.perform(.start, installation: server.installation, source: .fixed(server.installation))
    #expect(outcome == .requested)
    #expect(try server.requests().count == 1)
}

@Test func theScanPhaseFollowsTheEngineAndOnlyARequestInFlightChangesIt() throws {
    func status(_ fields: [String: Any]) throws -> Presentation {
        let base: [String: Any] = ["observed_at": "2026-10-31T12:00:00Z", "activity": "idle", "attention": [], "model": "ready"]
        return try JSONDecoder().decode(Presentation.self, from: JSONSerialization.data(withJSONObject: base.merging(fields) { $1 }))
    }
    func picture(stopped: Bool) throws -> ScanPicture {
        try JSONDecoder().decode(ScanPicture.self, from: JSONSerialization.data(withJSONObject: [
            "in_flight": [], "last_companies": 16, "last_stopped": stopped,
        ]))
    }
    let scanning = try status(["activity": "scanning"])
    let idle = try status([:])
    let queued = try status(["queued": "scan"])
    #expect(ScanPhase.of(scanning, picture: nil, requested: nil) == .scanning)
    #expect(ScanPhase.of(scanning, picture: nil, requested: .stop) == .stopping)
    // A start request while a scan already runs does not say Stopping.
    #expect(ScanPhase.of(scanning, picture: nil, requested: .start) == .scanning)
    #expect(ScanPhase.of(idle, picture: nil, requested: .start) == .requesting)
    #expect(ScanPhase.of(queued, picture: nil, requested: nil) == .requesting)
    // A stop request that reaches an engine already at rest shows the rest state.
    #expect(ScanPhase.of(idle, picture: try picture(stopped: false), requested: .stop) == .idle)
    #expect(ScanPhase.of(idle, picture: try picture(stopped: true), requested: nil) == .stopped)
    #expect(ScanPhase.of(idle, picture: nil, requested: nil) == .idle)
}

@Test func aScanPastItsReadingSaysWhichClosingStepItIsInAsTheDashboardDoes() throws {
    func picture(_ phase: Any) throws -> ScanPicture {
        try JSONDecoder().decode(ScanPicture.self, from: JSONSerialization.data(withJSONObject: [
            "phase": phase, "percent": 100, "in_flight": [], "last_stopped": false,
        ]))
    }
    #expect(ScanPhase.scanning.titleKey(try picture("collecting")) == "scan-title-scanning")
    #expect(ScanPhase.scanning.titleKey(try picture("persisting")) == "scan-title-adding")
    #expect(ScanPhase.scanning.titleKey(try picture("finishing")) == "scan-title-finishing")
    #expect(try picture("finishing").everyCompanyRead && !(try picture("collecting").everyCompanyRead))
    // An engine without the field, or with a stage this app does not know, keeps the plain title.
    #expect(ScanPhase.scanning.titleKey(try picture(NSNull())) == "scan-title-scanning")
    #expect(ScanPhase.scanning.titleKey(try picture("tidying")) == "scan-title-scanning")
    #expect(ScanPhase.scanning.titleKey(nil) == "scan-title-scanning")
    // A stop says Stopping whatever step the scan is in.
    #expect(ScanPhase.stopping.titleKey(try picture("finishing")) == "scan-title-stopping")
}
