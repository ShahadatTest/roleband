import Foundation
import LauncherCore

/// The panel in a fixed state for `--render-panel`: an owned engine that answers from a fixture,
/// a release feed with one newer version, and the requested update and scan state. Nothing is downloaded,
/// installed or restarted.
@MainActor
enum PanelPreview {
    static func model(preferences: UserDefaults, language: String?, arguments: [String]) async throws -> LauncherModel {
        func value(_ name: String) -> String? {
            arguments.first(where: { $0.hasPrefix("--\(name)=") }).map { String($0.dropFirst(name.count + 3)) }
        }
        let update = value("update") ?? "none"
        // `--setup=held` renders a fresh copy still on Welcome, `--setup=started` one past it.
        let setup = value("setup")
        preferences.set(setup == nil, forKey: "setupCompleted")
        if setup == "started" { preferences.set(SetupStep.connection.id, forKey: "setupStep") }
        let login = value("login-state") ?? "on"
        let home = FileManager.default.temporaryDirectory.appendingPathComponent("panel-render-\(UUID().uuidString)")
        let identity = try JSONDecoder().decode(Installation.self, from: Data(#"{"product":"roleband","instance":"0123456789abcdef01234567","api_origin":"http://127.0.0.1:58329","version":"0.1.0","format":1}"#.utf8))
        let scan = value("scan") ?? "idle"
        // `--hold=<reason>` holds the engine for that reason; `--status=incorrect` is a reply the app cannot read.
        let hold = value("hold")
        let unreadable = value("status") == "incorrect"
        let scanning = update == "waiting" || ["running", "stopping", "finishing"].contains(scan)
        let host = OwnedEngineService(start: {}, restart: {}, stop: {}, snapshot: { OwnedEngineSnapshot(state: .running, preparation: nil) })
        let service = LoginService(state: {
            switch login { case "approval": .approval; case "off": .off; default: .on }
        }, setEnabled: { _ in }, openSettings: {})
        // `--update=read-first` is an offer whose signed metadata carries a "Before you update" notice.
        let signedNotice = update == "read-first" ? "This version changes how your radar is stored. A backup is made first." : nil
        let body = ""
        let release = try JSONSerialization.data(withJSONObject: ["tag_name": "v0.1.1",
            "html_url": "https://github.com/roleband/roleband/releases/tag/v0.1.1", "body": body, "draft": false, "prerelease": false,
            "published_at": ISO8601DateFormatter().string(from: Date().addingTimeInterval(-86_400 * 3)),
            "assets": ReleaseFiles.all("0.1.1").map { ["name": $0, "state": "uploaded"] }])
        // `--update=current` is a check that found nothing newer five minutes ago; `--update=unreachable` one that fails now;
        // `--update=checking` one still waiting for the feed.
        if update == "current" { preferences.set(Date().addingTimeInterval(-300), forKey: "updateLastSuccess") }
        let updates = LauncherUpdates(preferences: preferences, copy: LauncherCopy(language: language), fetch: {
            if update == "unreachable" { throw UpdateProblem.unavailable }
            if update == "checking" { try await Task.sleep(for: .seconds(3600)) }
            return release
        }, authenticate: { _ in signedNotice })
        let notice: UpdateNotice? = switch update {
        case "updated": UpdateNotice(id: UUID(), kind: .updated, from: "0.1.0", to: "0.1.1")
        case "rolled-back": UpdateNotice(id: UUID(), kind: .rolledBack, from: "0.1.0", to: "0.1.1")
        default: nil
        }
        var dependencies = LauncherDependencies(mode: .owned(leftover: nil), ownedEngine: host,
            registration: HomeLayout(home).registration, installation: .fixed(identity), readStatus: { installation in
                if unreadable { throw ConnectionProblem.invalidResponse }
                var response = try JSONSerialization.jsonObject(with: JSONEncoder().encode(installation)) as! [String: Any]
                let stamp = { (seconds: TimeInterval) in ISO8601DateFormatter().string(from: Date().addingTimeInterval(seconds)) }
                var status: [String: Any] = ["observed_at": stamp(0), "activity": scanning ? "scanning" : "idle",
                                             "activity_since": stamp(-134), "attention": [], "model": "ready",
                                             "last_scan_at": stamp(-7_200), "coverage_at": stamp(-7_200)]
                if let hold { status["hold"] = ["kind": "waiting", "reason": hold] }
                response["status"] = status
                response["scan"] = picture(scan, scanning: scanning, stamp: stamp)
                let reply: [String: Any] = ["db": "ok", "launcher": response, "running": scanning,
                                            "manual_sync_running": scanning, "manual_queued": []]
                return try StatusClient.decode(JSONSerialization.data(withJSONObject: reply), status: 200, installation: installation)
            }, readSchedule: { _, _, _ in
                let plan: [String: Any] = ["enabled": scan != "off" && scan != "timers",
                                           "paused_until": scan == "paused" ? ISO8601DateFormatter().string(from: Date().addingTimeInterval(10_800)) : NSNull()]
                return try ScheduleState.decode(JSONSerialization.data(withJSONObject: ["generated_at": "2026-10-30T12:00:00Z",
                                                                                         "enabled": scan != "off", "plan": plan]))
            },
            launcherVersion: notice.map { $0.kind == .updated ? $0.to : $0.from } ?? "0.1.0", openBrowser: { _ in false }, preferences: preferences, loginService: service,
            bundleURL: home.appendingPathComponent("Applications/RoleBand.app"), homeURL: home, language: language)
        dependencies.updates = updates
        dependencies.updateNotice = notice
        dependencies.installOperations = inert
        let model = LauncherModel(dependencies)
        model.panelTab = PanelTab.allCases.first(where: { value("tab") == ["scan", "settings", "about"][$0.rawValue] }) ?? .scan
        await model.launchAndWait()
        await model.refreshAndWait(includeSchedule: true)
        if update == "checking" { updates.checkManually() }
        else if !["none", "current"].contains(update) && notice == nil {
            updates.checkManually()
            while updates.checking { try await Task.sleep(for: .milliseconds(10)) }
        }
        if let installer = model.installer, let activity = activity(update) { installer.show(activity, version: "0.1.1") }
        if scan == "requesting" { model.showRequest(.start) }
        if scan == "stopping" { model.showRequest(.stop) }
        return model
    }

    /// The engine's scan picture for `--scan=`: a live scan with five companies in flight, one past
    /// its reading (`finishing`), or the last scan at rest, finished or stopped. `--scan=none` sends
    /// an engine without the field.
    nonisolated private static func picture(_ scan: String, scanning: Bool, stamp: (TimeInterval) -> String) -> Any {
        if scan == "none" { return NSNull() }
        let stopped = scan == "stopped"
        var picture: [String: Any] = ["in_flight": [], "last_companies": stopped ? 16 : 42, "last_new_roles": stopped ? 7 : 18,
                                      "last_postings": 712, "last_stopped": stopped,
                                      "next_scan_at": scan == "overdue" ? stamp(-2_160) : stamp(10_800),
                                      "scheduling": scan == "off" || scan == "timers" ? scan : "plan",
                                      "paused_until": scan == "paused" ? stamp(10_800) : NSNull()]
        if scanning {
            let names = ["Nvidia", "Apple", "Google", "Amazon", "Microsoft"]
            picture["percent"] = 38
            picture["companies_total"] = 42
            picture["roles_pending"] = 214
            picture["roles_recorded"] = 498
            picture["in_flight"] = names.enumerated().map { ["name": $1, "since": stamp(-148 + Double($0) * 15)] }
            picture["phase"] = "collecting"
        }
        if scan == "finishing" {
            picture.merge(["phase": "finishing", "percent": 100, "companies_total": 123, "roles_pending": 0,
                           "roles_recorded": 59, "in_flight": []]) { $1 }
        }
        return picture
    }

    private static func activity(_ update: String) -> UpdateActivity? {
        switch update {
        case "downloading": .downloading(received: 30_812_000, total: 181_061_003)
        case "paused": .paused(received: 96_000_000, total: 280_000_000)
        case "verifying": .verifying
        case "restarting": .restarting
        case "failed-download": .failed(.download)
        case "failed-check": .failed(.check)
        case "failed-space": .failed(.space(required: 5_600_000_000))
        case "failed-restart": .failed(.restart)
        default: nil
        }
    }

    /// Never reached: the render shows each state without running an update.
    private static let inert = UpdateInstallerOperations(reserve: { throw CancellationError() },
        download: { _, _, _ in throw CancellationError() }, prepare: { _ in throw CancellationError() },
        discard: { _ in }, handOff: { _ in throw CancellationError() })
}

extension UserDefaults {
    /// Preferences for one render or test. A suite named by an absolute path is the plist at that path,
    /// so these sit in the temporary folder, which macOS clears, and never add a domain to
    /// ~/Library/Preferences.
    static func scratch(_ label: String) -> UserDefaults {
        UserDefaults(suiteName: FileManager.default.temporaryDirectory
            .appendingPathComponent("roleband-\(label)-\(UUID().uuidString)").path)!
    }
}
