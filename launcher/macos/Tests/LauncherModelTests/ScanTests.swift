import Foundation
import LauncherCore
import Testing
@testable import RoleBandLauncher

private actor ScanTransport {
    var manual = false
    var reads = 0
    var writes = 0
    let entered: AsyncStream<Void>.Continuation
    var waiting: CheckedContinuation<ScanOutcome, Error>?
    private var holding = false
    private var held: CheckedContinuation<Void, Never>?
    init(_ entered: AsyncStream<Void>.Continuation) { self.entered = entered }
    /// Holds the next reads open after they took their answer, as a slow background poll does.
    func holdReads() { holding = true }
    func releaseReads() { holding = false; held?.resume(); held = nil }
    var readHeld: Bool { held != nil }
    func read(_ installation: Installation) async throws -> VerifiedStatus {
        reads += 1
        var identity = try JSONSerialization.jsonObject(with: JSONEncoder().encode(installation)) as! [String: Any]
        identity["status"] = ["observed_at": "2026-10-28T12:00:00Z", "activity": manual ? "scanning" : "idle",
                              "attention": [], "model": "ready"]
        let reply = try JSONSerialization.data(withJSONObject: [
            "db": "ok", "launcher": identity, "running": manual, "manual_sync_running": manual, "manual_queued": [],
        ])
        if holding { await withCheckedContinuation { held = $0 } }
        return try StatusClient.decode(reply, status: 200, installation: installation)
    }
    func write() async throws -> ScanOutcome {
        writes += 1
        return try await withCheckedThrowingContinuation { next in waiting = next; entered.yield(()) }
    }
    func answer(_ result: Result<ScanOutcome, Error>) { manual = true; waiting?.resume(with: result); waiting = nil }
}

@MainActor
private func withScanModel(_ body: (LauncherModel, ScanTransport, AsyncStream<Void>) async throws -> Void) async throws {
    let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    try FileManager.default.createDirectory(at: root, withIntermediateDirectories: false)
    defer { try? FileManager.default.removeItem(at: root) }
    let path = root.appendingPathComponent("installation.json")
    try Data(#"{"product":"roleband","instance":"0123456789abcdef01234567","api_origin":"http://127.0.0.1:58241","version":"0.1.0","format":1}"#.utf8).write(to: path)
    try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: path.path)
    let (requests, entered) = AsyncStream<Void>.makeStream()
    let transport = ScanTransport(entered)
    let model = LauncherModel(registration: path, readStatus: { try await transport.read($0) },
                              performScan: { _, _, _ in try await transport.write() })
    defer { model.stop() }
    try await body(model, transport, requests)
}

@MainActor
@Test func rapidClicksCannotDuplicateScanWritesAndThePanelWaitsForActualStatus() async throws {
    try await withScanModel { model, transport, requests in
        model.scan(.start)
        #expect(await transport.writes == 0)
        await model.refreshAndWait()
        #expect(model.scanAction == .start)
        var next = requests.makeAsyncIterator()
        model.scan(.start)
        await next.next()
        #expect(model.controlBusy && model.controlMessage == nil)
        #expect(model.verified?.presentation.activity == .idle)
        model.scan(.start)
        model.scan(.stop)
        model.refresh()
        #expect(await transport.writes == 1)
        #expect(await transport.reads == 1)
        await transport.answer(.success(.requested))
        await model.scanAndWait(.start)
        #expect(!model.controlBusy)
        #expect(model.controlMessage == nil)
        #expect(model.scanAction == .stop)
        #expect(await transport.reads == 2)
    }
}

/// A background poll never takes a press away, and its older answer never undoes the press.
@MainActor
@Test func aScanPressDuringABackgroundReadIsSent() async throws {
    try await withScanModel { model, transport, requests in
        await model.refreshAndWait()
        await transport.holdReads()
        model.refresh()
        while await !transport.readHeld { await Task.yield() }
        #expect(model.checking && model.scanAction == .start)
        model.scan(.start)
        #expect(model.controlBusy, "a press during a background read was dropped")
        guard model.controlBusy else { return await transport.releaseReads() }
        var next = requests.makeAsyncIterator()
        await next.next()
        await transport.releaseReads()
        await transport.answer(.success(.requested))
        for _ in 0..<500 where model.controlBusy || model.scanAction != .stop { try await Task.sleep(for: .milliseconds(10)) }
        #expect(model.scanAction == .stop && model.controlMessage == nil)
        #expect(await transport.writes == 1)
    }
}

/// A scan that started leaves no line under the buttons: the picture shows it. A press that
/// changed nothing still says why.
@MainActor
@Test func onlyAPressThatChangedNothingLeavesALine() async throws {
    for (outcome, line) in [(ScanOutcome.requested, nil), (.alreadyRunning, "scan-already-running")] as [(ScanOutcome, String?)] {
        try await withScanModel { model, transport, requests in
            await model.refreshAndWait()
            var next = requests.makeAsyncIterator()
            model.scan(.start)
            await next.next()
            await transport.answer(.success(outcome))
            await model.scanAndWait(.start)
            #expect(model.controlMessage == line)
        }
    }
}

@MainActor
@Test func refusalAndUncertainTransportErrorsDoNotInventSuccessOrRetryTheWrite() async throws {
    for error in [ControlProblem.refused as any Error, ConnectionProblem.unavailable as any Error] {
        try await withScanModel { model, transport, requests in
            await model.refreshAndWait()
            var next = requests.makeAsyncIterator()
            model.scan(.start)
            await next.next()
            await transport.answer(.failure(error))
            await model.scanAndWait(.start)
            #expect(model.controlMessage == (error is ControlProblem ? "scan-refused" : "scan-unconfirmed"))
            #expect(!model.controlBusy)
            #expect(await transport.writes == 1)
            #expect(await transport.reads == 2)
        }
    }
}
