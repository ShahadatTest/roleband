import Foundation
import Testing
import LauncherCore
@testable import RoleBandLauncher

@MainActor private final class NotificationBoundary {
    var authorized = true
    var enabled = true
    var version = "0.2.0"
    var requests = 0
    var delivered: [String] = []
    var fail = false
    var suspended: CheckedContinuation<Bool, Never>?
    var hold = false
    func authorize() async -> Bool {
        requests += 1
        if hold { return await withCheckedContinuation { suspended = $0 } }
        return authorized
    }
    func deliver(_ version: String) throws -> Bool {
        if fail { throw CocoaError(.fileReadUnknown) }
        guard authorized else { return false }
        delivered.append(version)
        return true
    }
    func notices(_ preferences: UserDefaults) -> UpdateNotices {
        UpdateNotices(preferences: preferences, authorize: { await self.authorize() },
            deliver: { try self.deliver($0) }, eligible: { self.enabled && self.version == $0 })
    }
}

@MainActor private func withNotices(_ body: (NotificationBoundary, UserDefaults) async throws -> Void) async rethrows {
    let preferences = UserDefaults.scratch("notification-tests")
    try await body(NotificationBoundary(), preferences)
}

@MainActor @Test func manualChecksAndDisabledOrStaleAutomaticOffersNeverNotifyOrAskPermission() async {
    await withNotices { boundary, preferences in
        let notices = boundary.notices(preferences)
        await notices.checked(version: "0.2.0", automatic: false)
        await notices.checked(version: "0.1.0", automatic: true)
        boundary.enabled = false
        notices.automaticChoiceChanged(false)
        await notices.checked(version: "0.2.0", automatic: true)
        #expect(boundary.requests == 0 && boundary.delivered.isEmpty)
        #expect(preferences.string(forKey: "updateNotifiedVersion") == nil)
    }
}

@MainActor @Test func automaticNoticesDeliverOncePerVersionAcrossRestartsAndDoNotPromptPassively() async {
    await withNotices { boundary, preferences in
        let notices = boundary.notices(preferences)
        notices.automaticChoiceChanged(true)
        await notices.checked(version: "0.2.0", automatic: true)
        await notices.checked(version: "0.2.0", automatic: true)
        let restored = boundary.notices(preferences)
        await restored.checked(version: "0.2.0", automatic: true)
        boundary.version = "0.3.0"
        await restored.checked(version: "0.3.0", automatic: true)
        #expect(boundary.requests == 1)
        #expect(boundary.delivered == ["0.2.0", "0.3.0"])
    }
}

@MainActor @Test func deniedOrFailedNoticesDoNotRecordDeliveryAndCanRecoverAfterSettingsChange() async {
    await withNotices { boundary, preferences in
        let notices = boundary.notices(preferences)
        boundary.authorized = false
        notices.automaticChoiceChanged(true)
        await notices.checked(version: "0.2.0", automatic: true)
        #expect(preferences.string(forKey: "updateNotifiedVersion") == nil)
        boundary.authorized = true
        boundary.fail = true
        await notices.checked(version: "0.2.0", automatic: true)
        #expect(preferences.string(forKey: "updateNotifiedVersion") == nil)
        boundary.fail = false
        await notices.checked(version: "0.2.0", automatic: true)
        #expect(boundary.requests == 1)
        #expect(boundary.delivered == ["0.2.0"])
    }
}

@MainActor @Test func disablingAutomaticChecksWhileThePermissionPromptIsOpenDiscardsTheNotice() async {
    await withNotices { boundary, preferences in
        boundary.hold = true
        let notices = boundary.notices(preferences)
        notices.automaticChoiceChanged(true)
        let check = Task { await notices.checked(version: "0.2.0", automatic: true) }
        while boundary.suspended == nil { await Task.yield() }
        let duplicate = Task { await notices.checked(version: "0.2.0", automatic: true) }
        await duplicate.value
        boundary.enabled = false
        notices.automaticChoiceChanged(false)
        boundary.suspended?.resume(returning: true)
        await check.value
        #expect(boundary.delivered.isEmpty)
        #expect(preferences.string(forKey: "updateNotifiedVersion") == nil)
    }
}

@Test func demoFeedRequiresBothPreviewIdentityAndAnAbsoluteRegistrationAndFeedPath() {
    var info: [String: Any] = ["RoleBandDemoReleaseFile": "/tmp/release.json"]
    #expect(UpdateDemo.file(in: info) == nil)
    info["RoleBandPreview"] = true
    #expect(UpdateDemo.file(in: info) == nil)
    info["RoleBandRegistration"] = "/tmp/installation.json"
    #expect(UpdateDemo.file(in: info)?.path == "/tmp/release.json")
    info["RoleBandDemoReleaseFile"] = "relative.json"
    #expect(UpdateDemo.file(in: info) == nil)
}

@MainActor @Test func demoChecksReadTheMutableFileThroughNormalValidationAndFailClosedForInvalidConfiguration() async throws {
    try await withNotices { _, preferences in
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let file = directory.appendingPathComponent("release.json")
        let info: [String: Any] = ["RoleBandPreview": true, "RoleBandRegistration": "/tmp/installation.json",
                                   "RoleBandDemoReleaseFile": file.path]
        let updates = UpdateDemo.updates(preferences: preferences, copy: LauncherCopy(), info: info)
        defer { updates.stop() }
        let release: [String: Any] = ["tag_name": "v0.2.0", "html_url": "https://github.com/roleband/roleband/releases/tag/v0.2.0",
                                    "body": "Dummy release.", "draft": false, "prerelease": false,
                                    "assets": ReleaseFiles.all("0.2.0").map { ["name": $0, "state": "uploaded"] }]
        try JSONSerialization.data(withJSONObject: release).write(to: file, options: .atomic)
        await updates.checkManuallyAndWait()
        #expect(updates.offered?.version == "0.2.0" && !updates.automatic)
        try Data("{}".utf8).write(to: file, options: .atomic)
        await updates.checkManuallyAndWait()
        #expect(updates.messageKey == "update-failed" && updates.offered?.version == "0.2.0")
        let invalid = UpdateDemo.updates(preferences: preferences, copy: LauncherCopy(),
                                        info: ["RoleBandDemoReleaseFile": file.path])
        defer { invalid.stop() }
        await invalid.checkManuallyAndWait()
        #expect(invalid.messageKey == "update-failed")
    }
}
