import AppKit
import Foundation
import SwiftUI
import Testing
@testable import LauncherCore
@testable import RoleBandLauncher

private func release(_ version: String) -> Data {
    try! JSONSerialization.data(withJSONObject: ["tag_name": "v" + version,
        "html_url": "https://github.com/roleband/roleband/releases/tag/v" + version,
        "body": "", "draft": false, "prerelease": false,
        "assets": ReleaseFiles.all(version).map { ["name": $0, "state": "uploaded"] }])
}

@MainActor private func preferences() -> UserDefaults {
    .scratch("launcher-panel")
}

/// An engine whose scan the test starts and ends, behind a registration the model reads.
private actor Engine {
    var scanning = false
    func set(scanning: Bool) { self.scanning = scanning }
    func read(_ installation: Installation) throws -> VerifiedStatus {
        var identity = try JSONSerialization.jsonObject(with: JSONEncoder().encode(installation)) as! [String: Any]
        identity["status"] = ["observed_at": "2026-10-31T12:00:00Z", "activity": scanning ? "scanning" : "idle",
                              "attention": [], "model": "ready"]
        return try StatusClient.decode(JSONSerialization.data(withJSONObject: [
            "db": "ok", "launcher": identity, "running": scanning, "manual_sync_running": scanning, "manual_queued": [],
        ]), status: 200, installation: installation)
    }
}

@MainActor private final class HandOffs {
    var plans: [UpdatePlan] = []
}

/// Operations that download and stage at once and record the hand-over instead of quitting.
@MainActor private func operations(home: URL, handOffs: HandOffs) -> UpdateInstallerOperations {
    UpdateInstallerOperations(reserve: { 0 }, download: { version, _, _ in
        let artifact = VerifiedArtifact(version: version, commit: String(repeating: "b", count: 40),
                                        imageName: "RoleBand-\(version)-macOS-arm64.dmg", bytes: 1, sha256: String(repeating: "d", count: 64))
        return DownloadedUpdate(artifact: artifact, image: home.appendingPathComponent(artifact.imageName))
    }, prepare: { _ in
        let trust = InstalledUpdateIdentity(version: "0.1.0", commit: String(repeating: "a", count: 40),
                                            publicKey: Data(repeating: 7, count: 32), certificateSHA256: String(repeating: "c", count: 64))
        return try UpdatePlan(id: UUID(), installed: home.appendingPathComponent("Applications/RoleBand.app"), home: home,
                              trust: trust, to: "0.1.1", toCommit: String(repeating: "b", count: 40), parent: getpid())
    }, discard: { _ in }, handOff: { handOffs.plans.append($0) })
}

@MainActor @Test func noticesFollowAutomaticChecksUntilChosenAndOnlyTurningThemOnAsksMacOS() async throws {
    let defaults = preferences()
    let updates = LauncherUpdates(preferences: defaults, fetch: { release("0.1.1") }, authenticate: { _ in nil })
    var asked: [Bool] = []
    updates.noticesChanged = { asked.append($0) }
    #expect(!updates.notices)
    updates.setAutomaticChecks(true, requestNotifications: false)
    #expect(updates.notices)
    updates.setNotices(false)
    #expect(!updates.notices && asked.isEmpty)
    updates.stop()

    let restored = LauncherUpdates(preferences: defaults, fetch: { release("0.1.1") }, authenticate: { _ in nil })
    restored.noticesChanged = { asked.append($0) }
    #expect(restored.automatic && !restored.notices)
    restored.setNotices(true)
    restored.setNotices(true)
    #expect(restored.notices && asked == [true])
    restored.stop()
}

@MainActor @Test func aRolledBackVersionIsNotOfferedAgainUntilAnExplicitCheckFindsIt() async throws {
    let defaults = preferences()
    let updates = LauncherUpdates(preferences: defaults, fetch: { release("0.1.1") }, authenticate: { _ in nil })
    updates.setAutomaticChecks(true, requestNotifications: false)
    let back = UpdateNotice(id: UUID(), kind: .rolledBack, from: "0.1.0", to: "0.1.1")
    let model = LauncherModel(launcherVersion: "0.1.0", preferences: defaults, updates: updates, updateNotice: back)
    defer { model.stop(); updates.stop() }
    await updates.checkAndWait(automatic: true)
    #expect(updates.offered?.version == "0.1.1")
    #expect(model.updateNotice == back && !model.updateOffered && !model.updateAsks)
    model.dismissUpdateNotice()
    #expect(model.updateNotice == nil && !model.updateOffered && !model.updateAsks)

    await updates.checkManuallyAndWait()
    #expect(model.updateOffered && model.updateAsks)
    // An updated notice says nothing about other versions: a newer offer takes the banner at once,
    // with no need to dismiss the notice first.
    let fresh = LauncherUpdates(preferences: preferences(), fetch: { release("0.1.2") }, authenticate: { _ in nil })
    let updated = LauncherModel(launcherVersion: "0.1.1", preferences: preferences(), updates: fresh,
                                updateNotice: UpdateNotice(id: UUID(), kind: .updated, from: "0.1.0", to: "0.1.1"))
    defer { updated.stop(); fresh.stop() }
    #expect(updated.updateNotice != nil && !updated.updateAsks)
    await fresh.checkManuallyAndWait()
    #expect(updated.updateNotice != nil && updated.updateOffered && updated.updateAsks)
}

@MainActor @Test func aDismissedNoticeStaysDismissedOnTheNextOpenButANewerOneShows() async throws {
    let defaults = preferences()
    let notice = UpdateNotice(id: UUID(), kind: .updated, from: "0.1.0", to: "0.1.1")
    let first = LauncherModel(launcherVersion: "0.1.1", preferences: defaults, updateNotice: notice)
    #expect(first.updateNotice == notice)
    first.dismissUpdateNotice()
    first.stop()
    let reopened = LauncherModel(launcherVersion: "0.1.1", preferences: defaults, updateNotice: notice)
    #expect(reopened.updateNotice == nil)
    reopened.stop()
    let later = UpdateNotice(id: UUID(), kind: .updated, from: "0.1.1", to: "0.1.2")
    let next = LauncherModel(launcherVersion: "0.1.2", preferences: defaults, updateNotice: later)
    #expect(next.updateNotice == later)
    next.stop()
}

@MainActor @Test func onlyAnAppThatOwnsItsEngineGetsAnInstaller() async throws {
    let home = FileManager.default.temporaryDirectory.appendingPathComponent("panel-\(UUID().uuidString)")
    let operations = operations(home: home, handOffs: HandOffs())
    let owned = LauncherModel(mode: .owned(leftover: nil), installOperations: operations)
    let attached = LauncherModel(mode: .attach, installOperations: operations)
    #expect(owned.installer != nil && attached.installer == nil)
    owned.stop()
    attached.stop()
}

@MainActor @Test func updateIsTheOnlyPressEvenDuringAScanAndTheAboutDotStopsAskingOnceItStarts() async throws {
    let root = FileManager.default.temporaryDirectory.appendingPathComponent("panel-\(UUID().uuidString)")
    try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
    defer { try? FileManager.default.removeItem(at: root) }
    let path = root.appendingPathComponent("installation.json")
    try Data(#"{"product":"roleband","instance":"0123456789abcdef01234567","api_origin":"http://127.0.0.1:58241","version":"0.1.0","format":1}"#.utf8).write(to: path)
    try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: path.path)
    let engine = Engine()
    await engine.set(scanning: true)
    let handOffs = HandOffs()
    let updates = LauncherUpdates(preferences: preferences(), fetch: { release("0.1.1") }, authenticate: { _ in nil })
    let model = LauncherModel(registration: path, readStatus: { try await engine.read($0) }, launcherVersion: "0.1.0",
                              updates: updates, installOperations: operations(home: root, handOffs: handOffs))
    defer { model.stop(); updates.stop() }
    await model.refreshAndWait()
    await updates.checkManuallyAndWait()
    let installer = try #require(model.installer)
    #expect(model.verified?.scanAction == .stop && model.updateAsks)

    // The scan still runs: a verified update hands over at once, with no second press.
    await installer.installAndWait("0.1.1")
    #expect(handOffs.plans.count == 1 && installer.activity == .restarting && !model.updateAsks)
    #expect(model.verified?.scanAction == .stop)
}

@Test func theStepsAfterTheDownloadNameThemselvesInEveryLanguage() {
    let english = LauncherCopy(language: "en")
    #expect(UpdateStep.title(.downloading(received: 1, total: 2), version: "0.1.8", copy: english) == "Downloading 0.1.8")
    #expect(UpdateStep.title(.verifying, version: "0.1.8", copy: english) == "Checking 0.1.8")
    #expect(UpdateStep.title(.restarting, version: "0.1.8", copy: english) == "Restarting to update")
    for language in ["en", "es", "zh-Hans"] {
        let copy = LauncherCopy(language: language)
        let titles = [UpdateActivity.downloading(received: 1, total: 2), .verifying, .restarting]
            .map { UpdateStep.title($0, version: "0.1.8", copy: copy) }
        #expect(Set(titles).count == 3, "\(language): \(titles)")
        #expect(!titles.contains(copy.text("reason-other")), "\(language) is missing a step's message")
    }
}

@Test func downloadMegabytesExistOnlyOnceTheSizeIsKnownAndOnlyForTheDownload() {
    let english = LauncherCopy(language: "en")
    #expect(UpdateSize.progress(received: 80_812_000, total: 181_061_003, copy: english) == "81 of 181 MB")
    #expect(UpdateSize.progress(received: 0, total: 0, copy: english) == nil)
    // The steps after the download draw a full line from 1 of 1, which is not a size.
    #expect(UpdateSize.progress(received: 1, total: 1, copy: english) == nil)
}

@Test func downloadProgressReadsInWholeMegabytesWithTheUnitOnce() {
    let english = Locale(identifier: "en_US")
    #expect(UpdateSize.megabytes(30_812_000, unit: false, locale: english) == "31")
    #expect(UpdateSize.megabytes(181_061_003, unit: true, locale: english) == "181 MB")
    #expect(UpdateSize.megabytes(0, unit: false, locale: english) == "0")
    #expect(UpdateSize.megabytes(400_000, unit: false, locale: english) == "0")
}

@Test func updateSizesAreWrittenTheWayTheAppsLanguageWritesNumbers() {
    let spanish = LauncherCopy(language: "es", regional: Locale(identifier: "es_ES"))
    #expect(UpdateSize.bytes(5_600_000_000, locale: spanish.locale) == "5,6 GB")
    #expect(UpdateSize.progress(received: 12_345_000_000, total: 23_456_000_000, copy: spanish) == "12.345 de 23.456 MB")
    let english = LauncherCopy(language: "en", regional: Locale(identifier: "en_US"))
    #expect(UpdateSize.bytes(5_600_000_000, locale: english.locale) == "5.6 GB")
    #expect(UpdateSize.progress(received: 12_345_000_000, total: 23_456_000_000, copy: english) == "12,345 of 23,456 MB")
}

/// A control that cannot be pressed must not look like one that can: What's new while the engine
/// is down, Check now while checking, setup Back while busy.
@MainActor @Test func everyButtonStyleLooksDifferentWhenItCannotBePressed() throws {
    func pixels(_ button: some View) throws -> Data {
        let host = NSHostingView(rootView: button.padding(6).background(Color.white).environment(\.colorScheme, .light))
        host.frame = NSRect(origin: .zero, size: host.fittingSize)
        host.layoutSubtreeIfNeeded()
        let bitmap = try #require(host.bitmapImageRepForCachingDisplay(in: host.bounds))
        host.cacheDisplay(in: host.bounds, to: bitmap)
        return try #require(bitmap.representation(using: .png, properties: [:]))
    }
    let palette = LaunchPalette(dark: false)
    let styles: [(String, (Bool) -> AnyView)] = [
        ("quiet", { AnyView(Button("Scan now") {}.buttonStyle(QuietButtonStyle()).frame(width: 120).disabled($0)) }),
        ("footer", { AnyView(Button("Settings") {}.buttonStyle(FooterButtonStyle()).disabled($0)) }),
        ("mini", { AnyView(Button("Check now") {}.buttonStyle(MiniButtonStyle()).disabled($0)) }),
        ("pill", { AnyView(Button("Update") {}.buttonStyle(PillButtonStyle()).disabled($0)) }),
        ("link", { AnyView(Button("What's new") {}.buttonStyle(RoleBandLauncher.LinkButtonStyle()).disabled($0)) }),
        ("launch", { AnyView(Button("Back") {}.buttonStyle(LaunchButtonStyle(palette: palette)).disabled($0)) }),
        ("launch primary", { AnyView(Button("Continue") {}.buttonStyle(LaunchButtonStyle(palette: palette, primary: true)).disabled($0)) }),
    ]
    for (name, button) in styles {
        #expect(try pixels(button(false)) != pixels(button(true)), "\(name) looks the same when disabled")
    }
}

/// Setup, notes, the status window and the blocked window all close with Command-W, minimize with
/// Command-M, and let the person copy selected diagnostics or notes.
@MainActor @Test func everyWindowClosesMinimizesAndCopiesFromTheKeyboardInEveryLanguage() throws {
    let expected: [(shortcut: String, action: Selector, key: String)] = [
        ("w", #selector(NSWindow.performClose(_:)), "menu-close"), ("m", #selector(NSWindow.performMiniaturize(_:)), "menu-minimize"),
        ("c", #selector(NSText.copy(_:)), "menu-copy"), ("a", #selector(NSText.selectAll(_:)), "menu-select-all"),
        ("q", #selector(NSApplication.terminate(_:)), "quit"),
    ]
    for language in ["en", "es", "zh-Hans"] {
        let copy = LauncherCopy(language: language)
        let items = AppMenu.make(copy).items.flatMap { $0.submenu?.items ?? [] }
        for (shortcut, action, key) in expected {
            let item = try #require(items.first { $0.keyEquivalent == shortcut && $0.keyEquivalentModifierMask == .command },
                                    "\(language) has no Command-\(shortcut.uppercased())")
            #expect(item.action == action && item.title == copy.text(key) && item.title != key)
        }
    }
}

@Test func notificationSettingsOpenOnThisAppsOwnPage() throws {
    let parts = try #require(URLComponents(url: SystemSettings.notifications, resolvingAgainstBaseURL: false))
    #expect(parts.scheme == "x-apple.systempreferences" && parts.path == "com.apple.Notifications-Settings.extension")
    #expect(parts.queryItems == [URLQueryItem(name: "id", value: "com.roleband.launcher")])
}

@MainActor @Test func theSwitchJumpsInsteadOfSlidingUnderReduceMotion() {
    #expect(InkSwitchStyle.animation(reduceMotion: true) == nil)
    #expect(InkSwitchStyle.animation(reduceMotion: false) != nil)
}

@MainActor @Test func theBrowserRowsOpenPagesNoOtherRowAlreadyOpens() {
    // All settings lands on the settings page's first tab, Companies, so no row may open that tab.
    #expect(SettingsTab.browserLinks.map(\.route) == [.schedule, .settings])
    #expect(SettingsTab.browserLinks.map(\.title) == ["panel-scan-times", "panel-all-settings"])
}

@Test func scheduledScanningSwitchedOffByTheEngineOffersNoLinkThatCannotTurnItOn() throws {
    let now = Date(timeIntervalSince1970: 1_793_520_000)
    let picture = try JSONDecoder().decode(ScanPicture.self, from: Data(
        #"{"in_flight":[],"last_stopped":false,"next_scan_at":"2026-10-31T15:00:00Z"}"#.utf8))
    let off = ScheduleLine.of(phase: .idle, schedule: ScheduleState(enabled: false, pausable: false, pausedUntil: nil),
                              picture: picture, now: now)
    #expect(off == .off)
    #expect(off.scheduleLink == nil)
    let on = ScheduleLine.of(phase: .idle, schedule: ScheduleState(enabled: true, pausable: true, pausedUntil: nil),
                             picture: picture, now: now)
    #expect(on.scheduleLink == "scan-change-times")
    #expect(ScheduleLine.of(phase: .stopping, schedule: nil, picture: picture, now: now).scheduleLink == nil)
}

@Test func aReadFirstOfferOpensItsNotesInsteadOfInstalling() throws {
    func offer(_ notes: String) throws -> OfferedRelease {
        try OfferedRelease.decode(JSONSerialization.data(withJSONObject: [
            "tag_name": "v0.2.0", "html_url": "https://github.com/roleband/roleband/releases/tag/v0.2.0", "body": notes,
            "draft": false, "prerelease": false]), from: .production)
    }
    // Only a signed notice makes a release read-first; the same words as a heading in the notes do not.
    #expect(OfferButton.of(try offer("## Added\n- More.").signed(notice: "A backup is made first.")) == .readFirst)
    #expect(OfferButton.of(try offer("## Before you update\nA backup is made first.\n\n## Added\n- More.")) == .install)
    #expect(OfferButton.of(try offer("## Added\n- More.")) == .install)
    #expect(OfferButton.of(nil) == .install)
}
