import Foundation
import Testing
@testable import LauncherCore
@testable import RoleBandLauncher

private actor PreparationHost {
    var current = OwnedEngineSnapshot(state: .starting,
        preparation: EnginePreparation(database: "creating", model: "waiting", service: "starting",
            downloadedBytes: 0, totalBytes: 100, tier: "fp32", reason: nil, format: 1))
    var starts = 0
    var stops = 0
    func start() { starts += 1 }
    func stop() { stops += 1 }
    func ready() {
        current = OwnedEngineSnapshot(state: .running,
            preparation: EnginePreparation(database: "ready", model: "waiting", service: "ready",
                downloadedBytes: 39, totalBytes: 100, tier: "fp32", reason: "offline", format: 1))
    }
    func snapshot() -> OwnedEngineSnapshot { current }
    nonisolated var service: OwnedEngineService {
        OwnedEngineService(start: { await self.start() }, restart: { await self.start() },
                           stop: { await self.stop() }, snapshot: { await self.snapshot() })
    }
}

@MainActor
@Test func closingPreparationContinuesWorkWithoutLoginOrBrowserSideEffectsAndOfflineCanContinue() async throws {
    let root = FileManager.default.temporaryDirectory.appendingPathComponent("preparation-\(UUID().uuidString)")
    defer { try? FileManager.default.removeItem(at: root) }
    let home = root.appendingPathComponent("home")
    let bundle = home.appendingPathComponent("Applications/RoleBand.app")
    try FileManager.default.createDirectory(at: bundle, withIntermediateDirectories: true)
    let preferences = UserDefaults.scratch("prepare")
    let identity = Installation(product: "roleband", instance: "0123456789abcdef01234567",
        apiOrigin: "http://127.0.0.1:58329", version: "0.1.0", format: 1)
    let host = PreparationHost()
    var login = LoginState.off
    var loginWrites: [Bool] = []
    var browsers = 0
    let model = LauncherModel(installation: .fixed(identity), ownedEngine: host.service, readStatus: { installation in
        var reply = try JSONSerialization.jsonObject(with: JSONEncoder().encode(installation)) as! [String: Any]
        reply["status"] = ["observed_at": "2026-10-30T12:00:00Z", "activity": "idle", "attention": [], "model": "missing"]
        return try StatusClient.decode(JSONSerialization.data(withJSONObject: ["db": "ok", "launcher": reply]),
                                       status: 200, installation: installation)
    }, openBrowser: { _ in browsers += 1; return true }, preferences: preferences,
       loginService: LoginService(state: { login }, setEnabled: { enabled in loginWrites.append(enabled); login = enabled ? .on : .off },
                                  openSettings: { Issue.record("Settings must open only on explicit request") }),
       bundleURL: bundle, homeURL: home)
    defer { model.stop() }
    model.step = .connection
    model.launch()
    await model.launchAndWait()
    #expect(!model.preparationReady)
    model.dismissSetup()
    #expect(model.step == .connection && loginWrites.isEmpty && browsers == 0)
    #expect(await host.starts == 1)
    #expect(await host.stops == 0)
    await host.ready()
    await model.refreshHost()
    await model.refreshAndWait()
    #expect(model.preparationReady && model.preparation?.modelComplete == false)
    #expect(model.preparation?.reason == "offline" && model.step == .connection)
    #expect(loginWrites.isEmpty && browsers == 0)
    await model.advanceSetup()
    #expect(model.step == .login && loginWrites.isEmpty)
    await model.advanceSetup()
    #expect(model.step == .done && loginWrites == [true] && browsers == 0)
    #expect(model.finish() && browsers == 0)
    #expect(await model.shutdown())
    #expect(await host.stops == 1)
}

@MainActor
@Test func setupAutomaticChecksNeverAskForNotificationPermission() throws {
    let preferences = UserDefaults.scratch("prepare-updates")
    let updates = LauncherUpdates(preferences: preferences, fetch: { throw CancellationError() }, authenticate: { _ in nil })
    defer { updates.stop() }
    var choices: [Bool] = []
    updates.automaticChoiceChanged = { choices.append($0) }
    updates.setAutomaticChecks(true, requestNotifications: false)
    #expect(updates.automatic && choices.isEmpty)
    updates.setAutomaticChecks(false)
    updates.setAutomaticChecks(true)
    #expect(choices == [false, true])
}
