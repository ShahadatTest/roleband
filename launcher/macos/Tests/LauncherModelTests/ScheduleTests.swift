import Foundation
import LauncherCore
import Testing
@testable import RoleBandLauncher

private actor ScheduleTransport {
    var statusReads = 0
    var planReads = 0
    var pauseWrites = 0
    var scanWrites = 0
    var failed = false
    var pausedUntil: Date?
    let entered: AsyncStream<Void>.Continuation
    var waiting: CheckedContinuation<ScheduleState, Error>?
    /// How the status's scan picture says scans start; nil sends no picture, as an older engine does.
    var scheduling: [String: Any]?
    private var holding = false
    private var held: CheckedContinuation<Void, Never>?
    init(_ entered: AsyncStream<Void>.Continuation) { self.entered = entered }
    func sendScheduling(_ value: [String: Any]?) { scheduling = value }
    /// Holds the next status reads open, as a slow background poll does.
    func holdReads() { holding = true }
    func releaseReads() { holding = false; held?.resume(); held = nil }
    var readHeld: Bool { held != nil }
    func read(_ installation: Installation) async throws -> VerifiedStatus {
        if holding { await withCheckedContinuation { held = $0 } }
        statusReads += 1
        var identity = try JSONSerialization.jsonObject(with: JSONEncoder().encode(installation)) as! [String: Any]
        identity["status"] = ["observed_at": "2026-10-28T12:00:00Z", "activity": "idle", "attention": [], "model": "ready"]
        if let scheduling {
            identity["scan"] = (["in_flight": [], "last_stopped": false, "next_scan_at": "2026-10-28T15:00:00Z"] as [String: Any])
                .merging(scheduling) { $1 }
        }
        return try StatusClient.decode(JSONSerialization.data(withJSONObject: [
            "db": "ok", "launcher": identity, "running": false, "manual_sync_running": false, "manual_queued": [],
        ]), status: 200, installation: installation)
    }
    func plan() throws -> ScheduleState {
        let formatter = ISO8601DateFormatter()
        return try ScheduleState.decode(JSONSerialization.data(withJSONObject: [
            "generated_at": formatter.string(from: Date()), "enabled": true,
            "plan": ["enabled": true, "paused_until": pausedUntil.map { formatter.string(from: $0) } as Any? ?? NSNull()],
        ]))
    }
    func readPlan() throws -> ScheduleState {
        planReads += 1
        if failed { throw ConnectionProblem.invalidResponse }
        return try plan()
    }
    func failReads() { failed = true }
    func writeScan() -> ScanOutcome { scanWrites += 1; return .requested }
    func writePause() async throws -> ScheduleState {
        pauseWrites += 1
        return try await withCheckedThrowingContinuation { next in waiting = next; entered.yield(()) }
    }
    func answer(uncertain: Bool) throws {
        pausedUntil = Date().addingTimeInterval(3600)
        if uncertain { waiting?.resume(throwing: ConnectionProblem.unavailable) }
        else { waiting?.resume(returning: try plan()) }
        waiting = nil
    }
}

@MainActor
private func withScheduleModel(_ body: (LauncherModel, ScheduleTransport, AsyncStream<Void>) async throws -> Void) async throws {
    let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    try FileManager.default.createDirectory(at: root, withIntermediateDirectories: false)
    defer { try? FileManager.default.removeItem(at: root) }
    let path = root.appendingPathComponent("installation.json")
    try Data(#"{"product":"roleband","instance":"0123456789abcdef01234567","api_origin":"http://127.0.0.1:58241","version":"0.1.0","format":1}"#.utf8).write(to: path)
    try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: path.path)
    let (requests, entered) = AsyncStream<Void>.makeStream()
    let transport = ScheduleTransport(entered)
    let model = LauncherModel(registration: path, readStatus: { try await transport.read($0) },
                              performScan: { _, _, _ in await transport.writeScan() },
                              readSchedule: { _, _, _ in try await transport.readPlan() },
                              performPause: { _, _, _, _ in try await transport.writePause() }, timezone: { "Europe/Stockholm" })
    defer { model.stop() }
    try await body(model, transport, requests)
}

@MainActor
@Test(arguments: [false, true])
func pauseSharesTheMutationGateAndAnUncertainWriteIsReconciledWithoutRepeatingIt(uncertain: Bool) async throws {
    try await withScheduleModel { model, transport, requests in
        model.panelOpen = true
        await model.refreshAndWait()
        #expect(model.scheduleState?.isPaused() == false)
        var next = requests.makeAsyncIterator()
        model.pause(.hour)
        await next.next()
        #expect(model.controlBusy)
        #expect(model.scheduleState?.isPaused() == false)
        #expect(model.controlMessage == nil)
        model.pause(.threeHours)
        model.scan(.start)
        model.refresh()
        #expect(await transport.pauseWrites == 1)
        #expect(await transport.scanWrites == 0)
        #expect(await transport.statusReads == 1)
        try await transport.answer(uncertain: uncertain)
        await model.pauseAndWait(.hour)
        #expect(!model.controlBusy)
        #expect(model.controlMessage == (uncertain ? "pause-unconfirmed" : "pause-confirmed"))
        #expect(model.scheduleState?.isPaused() == true)
        #expect(await transport.statusReads == 2)
        #expect(await transport.planReads == 2)
        #expect(await transport.pauseWrites == 1)
    }
}

@MainActor
@Test func aPausePressDuringABackgroundReadIsSent() async throws {
    try await withScheduleModel { model, transport, requests in
        model.panelOpen = true
        await model.refreshAndWait()
        #expect(model.scheduleState?.pausable == true && model.scheduleState?.isPaused() == false)
        await transport.holdReads()
        model.refresh()
        while await !transport.readHeld { await Task.yield() }
        #expect(model.checking)
        model.pause(.hour)
        #expect(model.controlBusy, "a press during a background read was dropped")
        guard model.controlBusy else { return await transport.releaseReads() }
        var next = requests.makeAsyncIterator()
        await next.next()
        await transport.releaseReads()
        try await transport.answer(uncertain: false)
        for _ in 0..<500 where model.controlBusy || model.checking { try await Task.sleep(for: .milliseconds(10)) }
        #expect(model.controlMessage == "pause-confirmed" && model.scheduleState?.isPaused() == true)
        #expect(await transport.pauseWrites == 1)
    }
}

@MainActor
@Test func backgroundPollingSkipsTheRosterAndOpenPanelReadsAreThrottledEvenWhenScheduleReadFails() async throws {
    try await withScheduleModel { model, transport, _ in
        await model.refreshAndWait()
        #expect(await transport.planReads == 0)
        await transport.failReads()
        model.panelOpen = true
        await model.refreshAndWait()
        #expect(await transport.planReads == 1)
        #expect(model.verified != nil && model.scheduleFailed && model.scheduleState == nil)
        #expect(model.scanAction == .start)
        await model.refreshAndWait()
        #expect(await transport.planReads == 1)
        await model.refreshAndWait(includeSchedule: true)
        #expect(await transport.planReads == 2)
        model.pause(.hour)
        #expect(await transport.pauseWrites == 0)
        model.panelOpen = false
        await model.refreshAndWait()
        #expect(await transport.planReads == 2)
    }
}

@MainActor
@Test func showingThePanelAndTheActivationItCausesReadTheScheduleOnceAMinute() async throws {
    try await withScheduleModel { model, transport, _ in
        @MainActor func settle() async throws { while model.checking { try await Task.sleep(for: .milliseconds(5)) } }
        model.panelShown()
        model.becameActive()
        try await settle()
        #expect(await transport.statusReads == 1)
        #expect(await transport.planReads == 1)
        model.panelOpen = false
        model.panelShown()
        try await settle()
        model.becameActive()
        try await settle()
        #expect(await transport.statusReads == 3)
        #expect(await transport.planReads == 1)
        await model.refreshAndWait(includeSchedule: true)
        #expect(await transport.planReads == 2)
    }
}

@MainActor
@Test func aStatusThatSaysHowScansStartIsTheScheduleAndTheRosterIsNeverRead() async throws {
    try await withScheduleModel { model, transport, _ in
        let until = ISO8601DateFormatter().string(from: Date().addingTimeInterval(3_600))
        await transport.sendScheduling(["scheduling": "plan", "paused_until": until])
        model.panelOpen = true
        await model.refreshAndWait()
        #expect(model.scheduleState?.isPaused() == true)
        #expect(await transport.planReads == 0)

        // Each company on its own timer: scans start on their own, and there is no plan to pause.
        await transport.sendScheduling(["scheduling": "timers", "paused_until": NSNull()])
        await model.refreshAndWait(includeSchedule: true)
        #expect(model.scheduleState?.enabled == true && model.scheduleState?.isPaused() == false)
        model.pause(.hour)
        #expect(!model.controlBusy)
        await transport.sendScheduling(["scheduling": "off", "paused_until": NSNull()])
        await model.refreshAndWait()
        #expect(model.scheduleState?.enabled == false)
        #expect(await transport.planReads == 0)
        #expect(await transport.pauseWrites == 0)

        // An engine that sends no picture is still read, as before.
        await transport.sendScheduling(nil)
        await model.refreshAndWait(includeSchedule: true)
        #expect(await transport.planReads == 1)
    }
}
