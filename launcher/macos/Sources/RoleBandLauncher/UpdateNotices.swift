import Foundation
import LauncherCore
import UserNotifications

@MainActor
final class UpdateNotices {
    private let preferences: UserDefaults
    private let authorize: () async -> Bool
    private let deliver: (String) async throws -> Bool
    private let eligible: (String) -> Bool
    private var permission: Task<Bool, Never>?
    private var permissionGeneration = 0
    private var pending: Set<String> = []

    init(preferences: UserDefaults = .standard, authorize: @escaping () async -> Bool,
         deliver: @escaping (String) async throws -> Bool, eligible: @escaping (String) -> Bool) {
        self.preferences = preferences
        self.authorize = authorize
        self.deliver = deliver
        self.eligible = eligible
    }
    func automaticChoiceChanged(_ enabled: Bool) {
        if enabled {
            permissionGeneration += 1
            permission = Task { await authorize() }
        }
    }
    func checked(version: String, automatic: Bool) async {
        guard automatic, eligible(version), !pending.contains(version),
              preferences.string(forKey: "updateNotifiedVersion") != version else { return }
        pending.insert(version)
        defer { pending.remove(version) }
        if let permission {
            let generation = permissionGeneration
            let allowed = await permission.value
            if generation == permissionGeneration { self.permission = nil }
            if !allowed { return }
        }
        guard eligible(version) else { return }
        do {
            if try await deliver(version) {
                preferences.set(version, forKey: "updateNotifiedVersion")
            }
        } catch { return }
    }
}

@MainActor
final class NativeUpdateNotifications: NSObject, UNUserNotificationCenterDelegate {
    private let copy: LauncherCopy
    private let open: (String) -> Void
    init(copy: LauncherCopy, open: @escaping (String) -> Void) {
        self.copy = copy
        self.open = open
        super.init()
        UNUserNotificationCenter.current().delegate = self
    }
    func authorize() async -> Bool { await Self.requestAlerts() }
    func denied() async -> Bool { await Self.authorization() == .denied }
    func deliver(version: String, ifEligible: () -> Bool) async throws -> Bool {
        guard await Self.authorization() == .authorized, ifEligible() else { return false }
        try await Self.post(version: version, title: copy.text("update-available"),
                            body: copy.text("update-notification-body"))
        return true
    }
    // The notification center, its settings and its requests are not Sendable in every SDK.
    // These helpers use them only off the main actor, and only strings and statuses cross.
    private nonisolated static func requestAlerts() async -> Bool {
        (try? await UNUserNotificationCenter.current().requestAuthorization(options: [.alert])) ?? false
    }
    private nonisolated static func authorization() async -> UNAuthorizationStatus {
        await UNUserNotificationCenter.current().notificationSettings().authorizationStatus
    }
    private nonisolated static func post(version: String, title: String, body: String) async throws {
        let content = UNMutableNotificationContent()
        content.title = title
        content.subtitle = version
        content.body = body
        content.userInfo = ["version": version]
        let request = UNNotificationRequest(identifier: "roleband-update-" + version, content: content, trigger: nil)
        try await UNUserNotificationCenter.current().add(request)
    }
    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification,
                                           withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        completionHandler([.banner, .list])
    }
    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse,
                                           withCompletionHandler completionHandler: @escaping () -> Void) {
        let version = response.notification.request.content.userInfo["version"] as? String
        let selected = response.actionIdentifier == UNNotificationDefaultActionIdentifier
        completionHandler()
        if let version, selected { Task { @MainActor [weak self] in self?.open(version) } }
    }
}
