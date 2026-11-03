import Foundation
import LauncherCore
import Testing
@testable import RoleBandLauncher

private actor TransportGate {
    let entered: AsyncStream<Installation>.Continuation
    var waiting: [CheckedContinuation<VerifiedStatus, Error>] = []
    var calls = 0
    var maximum = 0
    init(_ entered: AsyncStream<Installation>.Continuation) { self.entered = entered }
    func read(_ installation: Installation) async throws -> VerifiedStatus {
        calls += 1
        return try await withCheckedThrowingContinuation { next in
            waiting.append(next)
            maximum = max(maximum, waiting.count)
            entered.yield(installation)
        }
    }
    func answer(_ result: Result<VerifiedStatus, Error>) { waiting.removeFirst().resume(with: result) }
}

@MainActor
@Test func aRegistrationReplacementDiscardsTheOldReplyAndNeverOpensItsBrowser() async throws {
    let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    try FileManager.default.createDirectory(at: root, withIntermediateDirectories: false)
    defer { try? FileManager.default.removeItem(at: root) }
    let path = root.appendingPathComponent("installation.json")
    func install(_ port: Int) throws -> Installation {
        let json: [String: Any] = ["product": "roleband", "instance": "0123456789abcdef01234567", "api_origin": "http://127.0.0.1:\(port)", "version": "0.1.0", "format": 1]
        try JSONSerialization.data(withJSONObject: json).write(to: path)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: path.path)
        return try Installation.load(path)
    }
    func reply(_ install: Installation) throws -> VerifiedStatus {
        let status: [String: Any] = ["observed_at": "2026-10-27T18:00:00Z", "activity": "idle", "attention": [], "model": "ready"]
        var identity = try JSONSerialization.jsonObject(with: JSONEncoder().encode(install)) as! [String: Any]
        identity["status"] = status
        let bytes = try JSONSerialization.data(withJSONObject: ["db": "ok", "launcher": identity])
        return try StatusClient.decode(bytes, status: 200, installation: install)
    }
    let first = try install(58231)
    let (requests, entered) = AsyncStream<Installation>.makeStream()
    let gate = TransportGate(entered)
    var opened: [URL] = []
    let model = LauncherModel(registration: path, readStatus: { try await gate.read($0) }, openBrowser: { opened.append($0); return true })
    defer { model.stop() }
    let (updates, changed) = AsyncStream<Void>.makeStream()
    model.changed = { changed.yield(()) }
    var request = requests.makeAsyncIterator()
    var update = updates.makeAsyncIterator()
    model.refresh(open: .radar)
    _ = await update.next()
    #expect(await request.next() == first)
    model.refresh()
    model.refresh()
    let second = try install(58232)
    await gate.answer(.success(try reply(first)))
    _ = await update.next()
    #expect(opened.isEmpty)
    #expect(model.problem == .identityMismatch)
    #expect(await request.next() == second)
    await gate.answer(.success(try reply(second)))
    _ = await update.next()
    _ = await update.next()
    #expect(model.verified?.installation == second)
    #expect(await gate.maximum == 1)
    #expect(await gate.calls == 2)
    #expect(opened.isEmpty)
    model.refresh(open: .settings)
    #expect(await request.next() == second)
    await gate.answer(.success(try reply(second)))
    _ = await update.next()
    _ = await update.next()
    #expect(opened.map(\.absoluteString) == ["http://127.0.0.1:58232/settings"])
}
