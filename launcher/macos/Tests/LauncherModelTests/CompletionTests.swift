import Foundation
import LauncherCore
import Testing
@testable import RoleBandLauncher

private actor CompletionReader {
    let entered: AsyncStream<Installation>.Continuation
    var paused = false
    var calls = 0
    var waiting: (Installation, CheckedContinuation<VerifiedStatus, Error>)?
    init(_ entered: AsyncStream<Installation>.Continuation) { self.entered = entered }
    func read(_ installation: Installation) async throws -> VerifiedStatus {
        calls += 1
        if paused {
            return try await withCheckedThrowingContinuation { next in
                waiting = (installation, next)
                entered.yield(installation)
            }
        }
        return try reply(installation)
    }
    func pause() { paused = true }
    func answer(failed: Bool = false) throws {
        let (installation, next) = waiting!
        waiting = nil
        paused = false
        if failed { next.resume(throwing: ConnectionProblem.unavailable) }
        else { next.resume(returning: try reply(installation)) }
    }
    private func reply(_ installation: Installation) throws -> VerifiedStatus {
        var identity = try JSONSerialization.jsonObject(with: JSONEncoder().encode(installation)) as! [String: Any]
        identity["status"] = ["observed_at": "2026-10-28T12:00:00Z", "activity": "idle", "attention": [], "model": "ready"]
        return try StatusClient.decode(JSONSerialization.data(withJSONObject: ["db": "ok", "launcher": identity]),
                                       status: 200, installation: installation)
    }
}

@MainActor
private func withCompletionModel(installed: Bool = true,
    open: @escaping @MainActor (URL, UserDefaults) -> Bool = { _, _ in true },
    body: @MainActor (LauncherModel, CompletionReader, AsyncStream<Installation>, URL, UserDefaults) async throws -> Void) async throws {
    let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    try FileManager.default.createDirectory(at: root, withIntermediateDirectories: false)
    defer { try? FileManager.default.removeItem(at: root) }
    let preferences = UserDefaults.scratch("completion-test")
    let registration = root.appendingPathComponent("installation.json")
    try JSONSerialization.data(withJSONObject: ["product": "roleband", "format": 1, "version": "0.1.0",
        "instance": "0123456789abcdef01234567", "api_origin": "http://127.0.0.1:58272"]).write(to: registration)
    try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: registration.path)
    let (requests, entered) = AsyncStream<Installation>.makeStream()
    let reader = CompletionReader(entered)
    let bundle = (installed ? URL(fileURLWithPath: "/Applications") : root).appendingPathComponent("RoleBand.app")
    let model = LauncherModel(registration: registration, readStatus: { try await reader.read($0) },
        openBrowser: { open($0, preferences) }, preferences: preferences, bundleURL: bundle, homeURL: root)
    defer { model.stop() }
    try await body(model, reader, requests, registration, preferences)
}

@MainActor
@Test func completionVerifiesAgainAndSavesBeforeOneBrowserHandoff() async throws {
    var urls: [URL] = []
    var completedAtOpen: [Bool] = []
    try await withCompletionModel(open: { url, preferences in
        urls.append(url); completedAtOpen.append(preferences.bool(forKey: "setupCompleted")); return true
    }) { model, reader, requests, _, preferences in
        await model.refreshAndWait()
        model.step = .done
        await reader.pause()
        var next = requests.makeAsyncIterator()
        let launch = Task { await model.completeAndOpen() }
        _ = await next.next()
        #expect(model.completingSetup && !model.setupCompleted && urls.isEmpty)
        #expect(!preferences.bool(forKey: "setupCompleted"))
        #expect(await model.completeAndOpen() == false)
        try await reader.answer()
        #expect(await launch.value)
        #expect(await reader.calls == 2)
        #expect(urls.map(\.absoluteString) == ["http://127.0.0.1:58272/"])
        #expect(completedAtOpen == [true])
        #expect(!model.completingSetup && model.setupCompleted && !model.shouldShowSetupAtLaunch)
    }
}

@MainActor
@Test func browserFailureKeepsSetupCompleteAndConnectionValidForRetry() async throws {
    var attempts = 0
    try await withCompletionModel(open: { _, _ in attempts += 1; return attempts > 1 }) { model, reader, _, _, preferences in
        await model.refreshAndWait()
        model.step = .done
        #expect(await model.completeAndOpen() == false)
        #expect(model.setupCompleted && preferences.bool(forKey: "setupCompleted"))
        #expect(model.verified != nil && model.problem == nil && model.setupOpenFailed)
        #expect(model.step == .done && !model.shouldShowSetupAtLaunch)
        #expect(await model.completeAndOpen())
        #expect(!model.setupOpenFailed && attempts == 2)
        #expect(await reader.calls == 3)
    }
}

@MainActor
@Test(arguments: [false, true])
func completionRefusesAStaleConnectionOrReplacedRegistration(replace: Bool) async throws {
    var opens = 0
    try await withCompletionModel(open: { _, _ in opens += 1; return true }) { model, reader, requests, registration, preferences in
        await model.refreshAndWait()
        model.step = .done
        await reader.pause()
        var next = requests.makeAsyncIterator()
        let launch = Task { await model.completeAndOpen() }
        _ = await next.next()
        if replace {
            var value = try JSONSerialization.jsonObject(with: Data(contentsOf: registration)) as! [String: Any]
            value["instance"] = "ffffffffffffffffffffffff"
            try JSONSerialization.data(withJSONObject: value).write(to: registration)
        }
        try await reader.answer(failed: !replace)
        #expect(await launch.value == false)
        #expect(opens == 0 && !model.setupCompleted && !preferences.bool(forKey: "setupCompleted"))
        #expect(model.step == .connection && model.verified == nil)
        #expect(!model.setupOpenFailed && !model.completingSetup)
    }
}

@MainActor
@Test func dismissingReadyFinishesWithoutOpeningButEarlierDismissalDefers() async throws {
    var opens = 0
    try await withCompletionModel(open: { _, _ in opens += 1; return true }) { model, _, _, _, preferences in
        model.step = .login
        model.dismissSetup()
        #expect(!model.setupCompleted && preferences.bool(forKey: "setupDeferred"))
        #expect(model.step == .login)
        await model.refreshAndWait()
        model.step = .done
        model.dismissSetup()
        #expect(model.setupCompleted && !model.shouldShowSetupAtLaunch && opens == 0)
    }
}

@MainActor
@Test func aCopyOutsideApplicationsCannotCompleteAndOpen() async throws {
    var opens = 0
    try await withCompletionModel(installed: false, open: { _, _ in opens += 1; return true }) { model, reader, _, _, _ in
        model.step = .done
        #expect(await model.completeAndOpen() == false)
        #expect(!model.setupCompleted && model.step == .installation && opens == 0)
        #expect(await reader.calls == 0)
    }
}
