import Foundation
import LauncherCore
import Testing
@testable import RoleBandLauncher

/// The engine's reply, changed between reads: its status fields and its scan picture.
private actor PictureEngine {
    var status = Data(#"{"activity":"idle"}"#.utf8)
    var scan = Data("null".utf8)
    var manual = false
    var stops = 0
    var waiting: CheckedContinuation<ScanOutcome, Error>?
    let entered: AsyncStream<Void>.Continuation
    init(_ entered: AsyncStream<Void>.Continuation) { self.entered = entered }
    func set(_ status: Data, scan: Data, manual: Bool = false) {
        self.status = status
        self.scan = scan
        self.manual = manual
    }
    func read(_ installation: Installation) throws -> VerifiedStatus {
        var identity = try JSONSerialization.jsonObject(with: JSONEncoder().encode(installation)) as! [String: Any]
        let fields = try JSONSerialization.jsonObject(with: status) as! [String: Any]
        identity["status"] = ["observed_at": "2026-10-31T12:00:00Z", "attention": [], "model": "ready"]
            .merging(fields) { $1 }
        identity["scan"] = try JSONSerialization.jsonObject(with: scan, options: .fragmentsAllowed)
        return try StatusClient.decode(JSONSerialization.data(withJSONObject: [
            "db": "ok", "launcher": identity, "running": manual, "manual_sync_running": manual, "manual_queued": [],
        ]), status: 200, installation: installation)
    }
    func write() async throws -> ScanOutcome {
        stops += 1
        return try await withCheckedThrowingContinuation { waiting = $0; entered.yield(()) }
    }
    func answer(_ result: Result<ScanOutcome, Error>) { waiting?.resume(with: result); waiting = nil }
}

private var rest: [String: Any] { ["in_flight": [], "last_companies": 42, "last_new_roles": 18, "last_postings": 712,
                                   "last_stopped": false, "next_scan_at": "2026-10-31T15:00:00Z"] }
private var live: [String: Any] { rest.merging([
    "percent": 38, "companies_total": 42, "roles_pending": 214, "roles_recorded": 498,
    "in_flight": [["name": "Nvidia", "since": "2026-10-31T11:57:32Z"]],
]) { $1 } }

private func json(_ value: Any) throws -> Data { try JSONSerialization.data(withJSONObject: value, options: .fragmentsAllowed) }

@MainActor
private func withPictureModel(_ body: (LauncherModel, PictureEngine, AsyncStream<Void>) async throws -> Void) async throws {
    let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    try FileManager.default.createDirectory(at: root, withIntermediateDirectories: false)
    defer { try? FileManager.default.removeItem(at: root) }
    let path = root.appendingPathComponent("installation.json")
    try Data(#"{"product":"roleband","instance":"0123456789abcdef01234567","api_origin":"http://127.0.0.1:58241","version":"0.1.0","format":1}"#.utf8).write(to: path)
    try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: path.path)
    let (requests, entered) = AsyncStream<Void>.makeStream()
    let engine = PictureEngine(entered)
    let model = LauncherModel(registration: path, readStatus: { try await engine.read($0) },
                              performScan: { _, _, _ in try await engine.write() })
    defer { model.stop() }
    try await body(model, engine, requests)
}

@MainActor
@Test func theScanPictureReplacesTheCardOnlyWhileTheEngineIsHealthyAndHasAScanToDraw() async throws {
    try await withPictureModel { model, engine, _ in
        let never: [String: Any] = ["in_flight": [], "last_stopped": false]
        let cases: [(status: [String: Any], scan: Any, phase: ScanPhase?)] = [
            (["activity": "idle"], rest, .idle),
            (["activity": "idle"], rest.merging(["last_companies": 16, "last_stopped": true]) { $1 }, .stopped),
            (["activity": "scanning"], live, .scanning),
            // A first scan before its first heartbeat still draws the scanning picture.
            (["activity": "scanning"], never, .scanning),
            // An engine without the field, or with nothing scanned yet, keeps the card.
            (["activity": "idle"], NSNull(), nil),
            (["activity": "idle"], never, nil),
            // The engine's company attention list is not the panel's to show; it never hides the picture.
            (["activity": "idle", "attention": ["coverage", "stuck_scan"]], rest, .idle),
            // Holds and updates keep the card, which says why.
            (["activity": "idle", "hold": ["kind": "waiting", "reason": "update_queued"]], rest, nil),
            (["activity": "updating"], rest, nil),
        ]
        for item in cases {
            await engine.set(try json(item.status), scan: try json(item.scan))
            await model.refreshAndWait()
            #expect(model.verified != nil)
            #expect((model.scanPicture != nil ? model.scanPhase : nil) == item.phase, "\(item.status) \(item.scan)")
        }
        await engine.set(try json(["activity": "idle", "attention": ["coverage", "stuck_scan"]]), scan: try json(rest))
        await model.refreshAndWait()
        #expect(model.symbol == "checkmark.circle" && model.menuBarBadge == nil && model.titleKey == "ready")
        await engine.set(try json(["activity": "idle", "hold": ["kind": "attention", "reason": "schema_pending"]]), scan: try json(rest))
        await model.refreshAndWait()
        #expect(model.symbol == "exclamationmark.circle" && model.menuBarBadge != nil, "an engine hold still marks the card and the menu bar")
        await engine.set(try json(["activity": "scanning"]), scan: try json(live))
        await model.refreshAndWait()
        #expect(model.scanPicture?.inFlight.map(\.name) == ["Nvidia"])
        #expect(model.scanPicture?.rolesPending == 214 && model.scanPicture?.percent == 38)
    }
}

@MainActor
@Test func stoppingLastsExactlyAsLongAsTheStopRequest() async throws {
    for outcome in [Result<ScanOutcome, Error>.success(.stopRequested), .failure(ControlProblem.refused)] {
        try await withPictureModel { model, engine, requests in
            await engine.set(try json(["activity": "scanning"]), scan: try json(live), manual: true)
            await model.refreshAndWait()
            #expect(model.scanPhase == .scanning && model.scanAction == .stop)
            var next = requests.makeAsyncIterator()
            model.scan(.stop)
            await next.next()
            #expect(model.requestedScan == .stop && model.scanPhase == .stopping)
            if case .success = outcome {
                await engine.set(try json(["activity": "idle"]), scan: try json(rest.merging(["last_companies": 16, "last_stopped": true]) { $1 }))
            }
            await engine.answer(outcome)
            await model.scanAndWait(.stop)
            #expect(model.requestedScan == nil)
            #expect(model.scanPhase == (outcome.isSuccess ? .stopped : .scanning))
            #expect(await engine.stops == 1)
        }
    }
}

private extension Result {
    var isSuccess: Bool { if case .success = self { true } else { false } }
}
