import Foundation
import LauncherCore

@MainActor
enum FirstOpenPreview {
    static func model(preferences: UserDefaults, language: String?, arguments: [String]) throws -> LauncherModel {
        let phase = arguments.first(where: { $0.hasPrefix("--prepare-state=") }).map { String($0.dropFirst(16)) } ?? "downloading"
        let login = arguments.first(where: { $0.hasPrefix("--login-state=") }).map { String($0.dropFirst(14)) } ?? "off"
        let home = FileManager.default.temporaryDirectory.appendingPathComponent("setup-render-\(UUID().uuidString)")
        let identity = try JSONDecoder().decode(Installation.self, from: Data(#"{"product":"roleband","instance":"0123456789abcdef01234567","api_origin":"http://127.0.0.1:58329","version":"0.1.0","format":1}"#.utf8))
        let reason: Any
        if phase == "offline" { reason = "offline" }
        else if phase == "failed" { reason = "database_failed" }
        else { reason = NSNull() }
        let progress: [String: Any] = [
            "format": 1, "database": phase == "starting" ? "creating" : phase == "failed" ? "failed" : "ready",
            "service": phase == "starting" || phase == "failed" ? "starting" : "ready",
            "model": phase == "done" ? "ready" : phase == "downloading" ? "downloading" : "waiting",
            "downloaded_bytes": phase == "done" ? 600153516 : phase == "starting" || phase == "failed" ? 0 : 234059871,
            "total_bytes": 600153516, "tier": "fp32", "reason": reason,
        ]
        let preparation = try JSONDecoder().decode(EnginePreparation.self, from: JSONSerialization.data(withJSONObject: progress))
        let snapshot = OwnedEngineSnapshot(state: preparation.failed ? .needsAttention : preparation.ready ? .running : .starting,
                                          preparation: preparation)
        let host = OwnedEngineService(start: {}, restart: {}, stop: {}, snapshot: { snapshot })
        let service = LoginService(state: {
            switch login { case "on": .on; case "approval": .approval; default: .off }
        }, setEnabled: { _ in }, openSettings: {})
        let model = LauncherModel(LauncherDependencies(mode: .owned(leftover: nil), ownedEngine: host,
            registration: HomeLayout(home).registration, installation: .fixed(identity), readStatus: { installation in
                var response = try JSONSerialization.jsonObject(with: JSONEncoder().encode(installation)) as! [String: Any]
                response["status"] = ["observed_at": "2026-10-30T12:00:00Z", "activity": "idle", "attention": [], "model": "preparing"]
                return try StatusClient.decode(JSONSerialization.data(withJSONObject: ["db": "ok", "launcher": response]),
                                               status: 200, installation: installation)
            }, openBrowser: { _ in false }, preferences: preferences, loginService: service,
            bundleURL: home.appendingPathComponent("Applications/RoleBand.app"), homeURL: home, language: language))
        return model
    }
}
