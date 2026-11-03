import AppKit
import Foundation
import LauncherCore
import Testing
@testable import RoleBandLauncher

private func installation(port: Int = 58241) throws -> Installation {
    try JSONDecoder().decode(Installation.self, from: JSONSerialization.data(withJSONObject: [
        "product": "roleband", "instance": "0123456789abcdef01234567", "api_origin": "http://127.0.0.1:\(port)",
        "version": "0.1.0", "format": 1,
    ]))
}

private func reply(_ install: Installation) throws -> VerifiedStatus {
    var identity = try JSONSerialization.jsonObject(with: JSONEncoder().encode(install)) as! [String: Any]
    identity["status"] = ["observed_at": "2026-10-27T18:00:00Z", "activity": "idle", "attention": [], "model": "ready"]
    let bytes = try JSONSerialization.data(withJSONObject: ["db": "ok", "launcher": identity, "running": false,
                                                            "manual_sync_running": false, "manual_queued": [String]()])
    return try StatusClient.decode(bytes, status: 200, installation: install)
}

private actor FirstReadHangs {
    var calls = 0
    let entered: AsyncStream<Void>.Continuation
    init(_ entered: AsyncStream<Void>.Continuation) { self.entered = entered }
    func read(_ install: Installation) async throws -> VerifiedStatus {
        calls += 1
        if calls == 1 {
            entered.yield(())
            try await Task.sleep(for: .seconds(60))
        }
        return try reply(install)
    }
}

@MainActor
@Test(.timeLimit(.minutes(1))) func aStoppedReadLeavesTheModelReadyToReadAgain() async throws {
    let install = try installation()
    let (entered, signal) = AsyncStream<Void>.makeStream()
    let reader = FirstReadHangs(signal)
    let model = LauncherModel(installation: .fixed(install), readStatus: { try await reader.read($0) })
    defer { model.stop() }
    model.refresh(open: .radar)
    var started = entered.makeAsyncIterator()
    _ = await started.next()
    model.stop()
    for _ in 0..<200 where model.checking { try await Task.sleep(for: .milliseconds(10)) }
    #expect(!model.checking)
    await model.refreshAndWait()
    #expect(model.verified?.installation == install)
    #expect(await reader.calls == 2)
}

@MainActor
@Test func aBrowserThatDoesNotOpenIsReportedWithoutDisconnectingTheEngine() async throws {
    let install = try installation()
    var attempts: [URL] = []
    let model = LauncherModel(installation: .fixed(install), readStatus: { try reply($0) },
                              openBrowser: { attempts.append($0); return false })
    defer { model.stop() }
    model.refresh(open: .radar)
    await model.refreshAndWait()
    #expect(attempts.map(\.absoluteString) == ["http://127.0.0.1:58241/"])
    #expect(model.verified?.installation == install)
    #expect(model.problem == nil)
    #expect(model.controlMessage == "setup-browser-error")
}

@MainActor
@Test func theAppsOwnEngineIsReadAndControlledWithoutARegistrationFile() async throws {
    let install = try installation()
    let sources = Sources()
    let model = LauncherModel(installation: .fixed(install), readStatus: { try reply($0) },
                              performScan: { _, scanned, source in
                                  try source.confirm(scanned)
                                  await sources.record(scanned)
                                  return .requested
                              })
    defer { model.stop() }
    #expect(!FileManager.default.fileExists(atPath: model.registrationURL.path))
    await model.refreshAndWait()
    #expect(model.verified?.installation == install && model.problem == nil)
    await model.scanAndWait(.start)
    #expect(await sources.scanned == [install])
    #expect(model.controlMessage == nil && !model.controlBusy)
}

private actor Sources {
    var scanned: [Installation] = []
    func record(_ install: Installation) { scanned.append(install) }
}

@MainActor
@Test func aSavedSetupStepIsItsNameAndAnUnknownNameStartsAtWelcome() throws {
    let preferences = UserDefaults.scratch("setup-step")
    let first = LauncherModel(preferences: preferences)
    first.step = .login
    #expect(preferences.string(forKey: "setupStep") == "login")
    #expect(LauncherModel(preferences: preferences).step == .login)
    preferences.set("a-step-no-longer-shipped", forKey: "setupStep")
    #expect(LauncherModel(preferences: preferences).step == .welcome)
    for step in SetupStep.allCases { #expect(SetupStep(id: step.id) == step) }
}

/// Answers a quit the way the app does, `.terminateLater` with the reply from a main actor task,
/// and cancels it. A timer cancels it instead when that task cannot run: the hang.
@MainActor private final class RefusingDelegate: NSObject, NSApplicationDelegate {
    var repliedBy: String?
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        Task { @MainActor in self.reply("shutdown", sender) }
        let timer = Timer(timeInterval: 1, repeats: false) { _ in MainActor.assumeIsolated { self.reply("timeout", sender) } }
        RunLoop.main.add(timer, forMode: .common)
        return .terminateLater
    }
    private func reply(_ by: String, _ sender: NSApplication) {
        guard repliedBy == nil else { return }
        repliedBy = by
        sender.reply(toApplicationShouldTerminate: false)
    }
}

/// Starts a real AppKit quit from `start` and says what let it finish.
@MainActor private func quit(_ start: @escaping @MainActor (@escaping @MainActor () -> Void) -> Void) async -> String? {
    let app = NSApplication.shared
    let previous = app.delegate
    let delegate = RefusingDelegate()
    app.delegate = delegate
    defer { app.delegate = previous }
    await withCheckedContinuation { done in
        start { app.terminate(nil); done.resume() }
    }
    return delegate.repliedBy
}

@MainActor
@Test(.timeLimit(.minutes(1))) func aQuitAskedForFromATaskOrASignalLetsTheShutdownItWaitsForRun() async {
    let direct = await quit { body in Task { @MainActor in body() } }
    #expect(direct == "timeout", "a quit straight from a task, as the update hand-off made it, must reproduce the hang")
    #expect(await quit { body in Task { @MainActor in AppQuit.request(body) } } == "shutdown")
    #expect(await quit { body in DispatchQueue.main.async { MainActor.assumeIsolated { AppQuit.request(body) } } } == "shutdown")
}
