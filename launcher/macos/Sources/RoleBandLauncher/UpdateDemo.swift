import Foundation
import LauncherCore

struct UpdateDemo {
    static func file(in info: [String: Any]) -> URL? {
        guard info["RoleBandPreview"] as? Bool == true,
              let registration = info["RoleBandRegistration"] as? String, registration.hasPrefix("/"),
              let path = info["RoleBandDemoReleaseFile"] as? String, path.hasPrefix("/") else { return nil }
        return URL(fileURLWithPath: path)
    }
    static var active: Bool { file(in: Bundle.main.infoDictionary ?? [:]) != nil }
    @MainActor static func updates(preferences: UserDefaults, copy: LauncherCopy,
                                   info: [String: Any] = Bundle.main.infoDictionary ?? [:]) -> LauncherUpdates {
        guard info["RoleBandDemoReleaseFile"] != nil else { return LauncherUpdates(preferences: preferences, copy: copy) }
        let file = file(in: info)
        return LauncherUpdates(preferences: preferences, copy: copy, fetch: {
            guard let file else { throw UpdateProblem.invalidResponse }
            let values = try file.resourceValues(forKeys: [.fileSizeKey, .isRegularFileKey])
            guard values.isRegularFile == true, (values.fileSize ?? Int.max) <= 262144 else { throw UpdateProblem.invalidResponse }
            return try Data(contentsOf: file)
        }, automaticInterval: 15, authenticate: { _ in nil })
    }
}
