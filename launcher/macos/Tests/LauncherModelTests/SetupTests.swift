import Foundation
import AppKit
import ServiceManagement
import LauncherCore
import Testing
@testable import RoleBandLauncher

@MainActor
@Test(.timeLimit(.minutes(1))) func theMainLoginPageDetectsExternalChangesWithoutReturningFromSettings() async throws {
    try await withPreferences { preferences in
        var state = LoginState.off
        let (reads, events) = AsyncStream<LoginState>.makeStream()
        var nextRead = reads.makeAsyncIterator()
        let service = LoginService(state: { events.yield(state); return state }, setEnabled: { _ in }, openSettings: {})
        let model = LauncherModel(preferences: preferences, loginService: service)
        defer { model.stop() }
        model.step = .login
        #expect(model.loginTimer == nil)
        model.setSetupVisible(true)
        #expect(await nextRead.next() == .off)
        let timer = try #require(model.loginTimer)
        state = .on
        timer.fire()
        // The page's own one-second tick may already have read the old state on a busy machine.
        var read = await nextRead.next()
        for _ in 0..<3 where read == .off { read = await nextRead.next() }
        #expect(read == .on)
        #expect(model.loginEnabled)
        model.setSetupVisible(false)
        #expect(!timer.isValid && model.loginTimer == nil)
    }
}

@MainActor
@Test func loginMonitoringHasOneTimerAndStopsWhenThePageOrWindowCloses() async throws {
    try await withPreferences { preferences in
        let model = LauncherModel(preferences: preferences,
                                  loginService: LoginService(state: { .off }, setEnabled: { _ in }, openSettings: {}))
        model.step = .login
        model.setSetupVisible(true)
        let first = try #require(model.loginTimer)
        model.setSetupVisible(true)
        let second = try #require(model.loginTimer)
        #expect(first !== second && !first.isValid && second.isValid)
        model.step = .connection
        #expect(!second.isValid && model.loginTimer == nil)
        model.step = .login
        let third = try #require(model.loginTimer)
        model.setSetupVisible(false)
        #expect(!third.isValid && model.loginTimer == nil)
        model.setSetupVisible(true)
        let fourth = try #require(model.loginTimer)
        model.stop()
        #expect(!fourth.isValid && model.loginTimer == nil)
    }
}

@MainActor
@Test func nativeLoginStatusesTreatANeverRegisteredAppAsOff() {
    #expect(LoginService.state(for: .enabled) == .on)
    #expect(LoginService.state(for: .notRegistered) == .off)
    #expect(LoginService.state(for: .notFound) == .off)
    #expect(LoginService.state(for: .requiresApproval) == .approval)
}

/// macOS as a fresh download in /Applications meets it: `notFound` until the app registers.
@MainActor
private final class FreshLoginItem {
    var status = SMAppService.Status.notFound
    var writes: [Bool] = []
    var service: LoginService {
        LoginService(state: { [unowned self] in LoginService.state(for: status) }, setEnabled: { [unowned self] enabled in
            writes.append(enabled)
            status = enabled ? .enabled : .notRegistered
        }, openSettings: {})
    }
}

@MainActor
private func freshSetup(_ preferences: UserDefaults, _ item: FreshLoginItem) -> LauncherModel {
    let model = LauncherModel(preferences: preferences, loginService: item.service,
                              bundleURL: URL(fileURLWithPath: "/Applications/RoleBand.app"))
    model.step = .login
    model.refreshLogin()
    return model
}

@MainActor
@Test func aFreshDownloadOffersOpenAtLoginAndContinueRegistersIt() async {
    await withPreferences { preferences in
        let item = FreshLoginItem()
        let model = freshSetup(preferences, item)
        defer { model.stop() }
        #expect(model.loginState == .off && model.setupLoginChoice)
        await model.advanceSetup()
        #expect(item.writes == [true] && model.loginState == .on && !model.loginError)
        #expect(model.step == .done)
    }
}

@MainActor
@Test func switchingOffBeforeEverRegisteringAsksMacOSNothingAndContinues() async {
    await withPreferences { preferences in
        let item = FreshLoginItem()
        let model = freshSetup(preferences, item)
        defer { model.stop() }
        await model.chooseSetupLogin(false)
        #expect(item.writes.isEmpty && !model.loginError && !model.setupLoginChoice)
        await model.advanceSetup()
        #expect(item.writes.isEmpty && model.step == .done && item.status == .notFound)
    }
}

@MainActor
private func withPreferences(_ body: (UserDefaults) async throws -> Void) async rethrows {
    let preferences = UserDefaults.scratch("setup-test")
    try await body(preferences)
}

@MainActor
@Test func deferredSetupResumesWithoutBeingMarkedCompleteOrShownAtEveryLogin() async {
    await withPreferences { preferences in
        let first = LauncherModel(preferences: preferences)
        #expect(first.shouldShowSetupAtLaunch)
        first.step = .login
        first.deferSetup()
        let resumed = LauncherModel(preferences: preferences)
        #expect(resumed.step == .login)
        #expect(!resumed.shouldShowSetupAtLaunch)
        #expect(!resumed.setupCompleted)
        #expect(!resumed.finish())
        #expect(!preferences.bool(forKey: "setupCompleted"))
    }
}

@MainActor
@Test func anInstalledCopyResumesPastAnObsoleteInstallationPageAndBackDoesNotReintroduceIt() async {
    await withPreferences { preferences in
        preferences.set(SetupStep.installation.id, forKey: "setupStep")
        let installed = LauncherModel(preferences: preferences,
            bundleURL: URL(fileURLWithPath: "/Applications/RoleBand.app"))
        defer { installed.stop() }
        #expect(installed.step == .connection)
        installed.goBack()
        #expect(installed.step == .welcome)
        installed.advance()
        #expect(installed.step == .connection)
        installed.step = .installation
        installed.prepareSetup()
        #expect(installed.step == .connection)
        let mounted = LauncherModel(preferences: preferences,
            bundleURL: URL(fileURLWithPath: "/Volumes/RoleBand/RoleBand.app"))
        defer { mounted.stop() }
        mounted.step = .welcome
        mounted.advance()
        #expect(mounted.step == .installation)
        #expect(!mounted.finish())
    }
}

@MainActor
@Test func openingSettingsDoesNotRegisterOrInventACompletedPermission() async {
    await withPreferences { preferences in
        var opens = 0
        var registrations = 0
        let service = LoginService(state: { .approval }, setEnabled: { _ in registrations += 1 },
                                   openSettings: { opens += 1 })
        let model = LauncherModel(preferences: preferences, loginService: service)
        model.openLoginSettings()
        model.openLoginSettings()
        #expect(opens == 2)
        #expect(registrations == 0)
        #expect(model.loginState == .approval)
        #expect(!model.loginEnabled && !model.setupCompleted)
    }
}

@MainActor
@Test func loginChangesFollowActualServiceStateIncludingErrorsAndExternalRevocation() async {
    await withPreferences { preferences in
        var state = LoginState.off
        var shouldFail = false
        var settings = 0
        let service = LoginService(state: { state }, setEnabled: { enabled in
            if shouldFail { throw CocoaError(.fileWriteNoPermission) }
            state = enabled ? .approval : .off
        }, openSettings: { settings += 1 })
        let model = LauncherModel(preferences: preferences, loginService: service,
                                  bundleURL: URL(fileURLWithPath: "/Applications/RoleBand.app"))
        await model.setLogin(true)
        #expect(model.loginState == .approval && !model.loginEnabled)
        #expect(settings == 1)
        state = .on
        model.refreshLogin()
        #expect(model.loginEnabled)
        shouldFail = true
        await model.setLogin(false)
        #expect(model.loginEnabled && model.loginError)
        #expect(!model.loginBusy)
        shouldFail = false
        await model.setLogin(false)
        #expect(!model.loginEnabled && !model.loginError)
        #expect(model.loginState == .off)
        state = .on
        model.refreshLogin()
        state = .off
        model.refreshLogin()
        #expect(!model.loginEnabled)
    }
}

@MainActor
@Test func aMountedDiskImageCannotRegisterItselfAtLogin() async {
    await withPreferences { preferences in
        var changes = 0
        let service = LoginService(state: { .off }, setEnabled: { _ in changes += 1 }, openSettings: {})
        let model = LauncherModel(preferences: preferences, loginService: service,
                                  bundleURL: URL(fileURLWithPath: "/Volumes/RoleBand/RoleBand.app"))
        await model.setLogin(true)
        model.step = .installation
        model.advance()
        #expect(changes == 0)
        #expect(model.step == .installation)
        #expect(!model.finish())
    }
}

@MainActor
@Test func completedSetupCanBeRevisitedWithoutTurningLoginOn() async throws {
    try await withPreferences { preferences in
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: false)
        defer { try? FileManager.default.removeItem(at: root) }
        let registration = root.appendingPathComponent("installation.json")
        let identity: [String: Any] = ["product": "roleband", "instance": "0123456789abcdef01234567",
                                      "api_origin": "http://127.0.0.1:58252", "version": "0.1.0", "format": 1]
        try JSONSerialization.data(withJSONObject: identity).write(to: registration)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: registration.path)
        var writes = 0
        let service = LoginService(state: { .off }, setEnabled: { _ in writes += 1 }, openSettings: {})
        var launcher = identity
        launcher["status"] = ["observed_at": "2026-10-28T00:00:00Z", "activity": "idle", "attention": [], "model": "ready"] as [String: Any]
        let data = try JSONSerialization.data(withJSONObject: ["db": "ok", "launcher": launcher])
        let model = LauncherModel(registration: registration, readStatus: { install in
            return try StatusClient.decode(data, status: 200, installation: install)
        }, preferences: preferences, loginService: service,
           bundleURL: URL(fileURLWithPath: "/Applications/RoleBand.app"))
        defer { model.stop() }
        await model.refreshAndWait()
        model.step = .login
        model.refreshLogin()
        model.advance()
        #expect(model.step == .done)
        #expect(model.finish())
        #expect(!model.shouldShowSetupAtLaunch)
        #expect(!model.loginEnabled && writes == 0)
        model.prepareSetup()
        #expect(model.step == .welcome)
        #expect(writes == 0)
        let reopened = LauncherModel(preferences: preferences)
        #expect(reopened.setupCompleted && !reopened.shouldShowSetupAtLaunch)
    }
}
