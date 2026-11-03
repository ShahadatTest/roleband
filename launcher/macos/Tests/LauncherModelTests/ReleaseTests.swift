import Foundation
import Testing
@testable import LauncherCore
@testable import RoleBandLauncher

private actor ReleaseTransport {
    var version = "0.1.0"
    var instance = "0123456789abcdef01234567"
    var fail = false
    var notesReads = 0
    func change(_ version: String) { self.version = version }
    func failNotes(_ fail: Bool) { self.fail = fail }
    func read(_ installation: Installation) throws -> VerifiedStatus {
        var identity = try JSONSerialization.jsonObject(with: JSONEncoder().encode(installation)) as! [String: Any]
        identity["version"] = version
        identity["status"] = ["observed_at": "2026-10-28T12:00:00Z", "activity": "idle", "attention": [], "model": "ready"]
        return try StatusClient.decode(JSONSerialization.data(withJSONObject: ["db": "ok", "launcher": identity]), status: 200, installation: installation)
    }
    func notes(_ status: VerifiedStatus) throws -> InstalledNotes {
        notesReads += 1
        if fail { throw ConnectionProblem.unavailable }
        var identity = try JSONSerialization.jsonObject(with: JSONEncoder().encode(status.installation)) as! [String: Any]
        identity["version"] = version
        return try InstalledNotes.decode(JSONSerialization.data(withJSONObject: ["launcher": identity, "version": version,
            "notes": "Useful changes.\n\n- A feature you can use."]), status: status)
    }
}

@MainActor
private func withReleaseModel(_ body: @MainActor (LauncherModel, ReleaseTransport, UserDefaults) async throws -> Void) async throws {
    let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    try FileManager.default.createDirectory(at: root, withIntermediateDirectories: false)
    defer { try? FileManager.default.removeItem(at: root) }
    let path = root.appendingPathComponent("installation.json")
    try Data(#"{"product":"roleband","instance":"0123456789abcdef01234567","api_origin":"http://127.0.0.1:58241","version":"0.1.0","format":1}"#.utf8).write(to: path)
    try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: path.path)
    let preferences = UserDefaults.scratch("release-tests")
    let transport = ReleaseTransport()
    let model = LauncherModel(registration: path, readStatus: { try await transport.read($0) },
                              readNotes: { status, _ in try await transport.notes(status) }, launcherVersion: "0.1.0", preferences: preferences)
    defer { model.stop() }
    try await body(model, transport, preferences)
}

@MainActor
@Test func aNewInstallationHasItsOwnBaselineAndFailedNotesAreNotFetchedOnEveryStatusPoll() async throws {
    try await withReleaseModel { model, transport, _ in
        await model.refreshAndWait()
        await transport.change("0.2.0")
        var identity = try JSONSerialization.jsonObject(with: Data(contentsOf: model.registrationURL)) as! [String: Any]
        identity["instance"] = "abcdef0123456789abcdef01"
        try JSONSerialization.data(withJSONObject: identity).write(to: model.registrationURL)
        await model.refreshAndWait()
        #expect(!model.hasNewRelease)
        await transport.failNotes(true)
        model.setNotesVisible(true)
        await model.refreshAndWait(includeNotes: true)
        #expect(await transport.notesReads == 1)
        await model.refreshAndWait()
        #expect(await transport.notesReads == 1)
        #expect(model.verified != nil && model.notesFailed)
    }
}

@MainActor
@Test func firstConnectionIsNotAnUpdateAndTheActualEngineVersionOverridesStaleRegistrationMetadata() async throws {
    try await withReleaseModel { model, transport, _ in
        await model.refreshAndWait()
        #expect(!model.hasNewRelease && !model.launcherBehind)
        #expect(await transport.notesReads == 0)
        await transport.change("0.2.0")
        await model.refreshAndWait()
        #expect(model.hasNewRelease && model.launcherBehind)
        #expect(model.verified?.engineVersion == "0.2.0")
        #expect(model.verified?.installation.version == "0.1.0")
        #expect(await transport.notesReads == 0)
    }
}

@MainActor
@Test func failedOrClosedNotesDoNotAcknowledgeAnUpgradeAndViewingIsRememberedWithoutDowngradeRegression() async throws {
    try await withReleaseModel { model, transport, preferences in
        await model.refreshAndWait()
        await transport.change("0.2.0")
        await transport.failNotes(true)
        model.setNotesVisible(true)
        await model.refreshAndWait(includeNotes: true)
        #expect(model.hasNewRelease && model.notesFailed)
        model.acknowledgeNotes()
        #expect(model.hasNewRelease)
        await transport.failNotes(false)
        await model.refreshAndWait(includeNotes: true)
        model.setNotesVisible(false)
        model.acknowledgeNotes()
        #expect(model.hasNewRelease)
        model.setNotesVisible(true)
        await model.refreshAndWait(includeNotes: true)
        model.acknowledgeNotes()
        #expect(!model.hasNewRelease)
        #expect((preferences.dictionary(forKey: "seenInstalledReleases") as? [String: String])?["0123456789abcdef01234567"] == "0.2.0")
        await transport.change("0.1.0")
        await model.refreshAndWait()
        #expect(!model.hasNewRelease)
        await transport.change("0.2.0")
        await model.refreshAndWait()
        #expect(!model.hasNewRelease)
    }
}
