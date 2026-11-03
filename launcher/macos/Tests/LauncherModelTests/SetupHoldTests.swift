import Foundation
import Testing
@testable import LauncherCore
@testable import RoleBandLauncher

private actor CountingHost {
    var starts = 0
    func start() { starts += 1 }
    nonisolated var service: OwnedEngineService {
        OwnedEngineService(start: { await self.start() }, restart: { await self.start() }, stop: {},
                           snapshot: { OwnedEngineSnapshot(state: .stopped, preparation: nil) })
    }
}

@MainActor
private func freshCopy(inApplications: Bool = true, saved: [String: String] = [:]) throws -> (LauncherModel, CountingHost, UserDefaults) {
    let home = FileManager.default.temporaryDirectory.appendingPathComponent("setup-hold-\(UUID().uuidString)")
    let bundle = inApplications ? home.appendingPathComponent("Applications/RoleBand.app")
        : home.appendingPathComponent("Downloads/RoleBand.app")
    try FileManager.default.createDirectory(at: bundle, withIntermediateDirectories: true)
    let preferences = UserDefaults.scratch("setup-hold")
    for (key, value) in saved { if value == "true" { preferences.set(true, forKey: key) } else { preferences.set(value, forKey: key) } }
    let host = CountingHost()
    let model = LauncherModel(ownedEngine: host.service, readStatus: { _ in throw ConnectionProblem.unavailable },
                              preferences: preferences, bundleURL: bundle, homeURL: home)
    return (model, host, preferences)
}

@MainActor
@Test func aFreshCopyStartsNoEngineUntilSetupContinuesPastWelcome() async throws {
    let (model, host, _) = try freshCopy()
    defer { model.stop() }
    await model.launchAndWait()
    #expect(model.step == .welcome && model.engineHeld)
    #expect(await host.starts == 0)
    await model.advanceSetup()
    await model.launchAndWait()
    #expect(model.step == .connection && !model.engineHeld)
    #expect(await host.starts == 1)
}

@MainActor
@Test func aCopyOutsideApplicationsStartsNothingEvenAfterWelcome() async throws {
    let (model, host, _) = try freshCopy(inApplications: false)
    defer { model.stop() }
    await model.launchAndWait()
    await model.advanceSetup()
    #expect(model.step == .installation && model.engineHeld)
    #expect(await host.starts == 0)
}

@MainActor
@Test(arguments: [["setupStep": "connection"], ["setupStep": "login"], ["setupCompleted": "true"]])
func aCopyWhoseSetupHasBegunStartsItsEngineAtOpen(saved: [String: String]) async throws {
    let (model, host, _) = try freshCopy(saved: saved)
    defer { model.stop() }
    await model.launchAndWait()
    #expect(!model.engineHeld)
    #expect(await host.starts == 1)
}

/// The panel draws a Finish setup card from `setupPending` and hides the engine's status and
/// controls while `engineHeld`; the menu-bar click always opens the panel.
@MainActor
@Test func anUnfinishedSetupKeepsLeadingBackToSetupUntilItCompletes() async throws {
    let (model, _, _) = try freshCopy()
    defer { model.stop() }
    await model.launchAndWait()
    #expect(model.setupPending && model.engineHeld)
    await model.advanceSetup()
    #expect(model.setupPending && !model.engineHeld)
    let (done, _, _) = try freshCopy(saved: ["setupCompleted": "true"])
    defer { done.stop() }
    #expect(!done.setupPending && !done.engineHeld)
    let attached = LauncherModel(mode: .attach)
    #expect(!attached.setupPending && !attached.engineHeld)
}
