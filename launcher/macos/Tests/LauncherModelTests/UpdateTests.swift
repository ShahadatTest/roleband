import Foundation
import Testing
@testable import LauncherCore
@testable import RoleBandLauncher

private actor UpdateTransport {
    var calls = 0
    var version = "0.2.0"
    var failure: UpdateProblem?
    var suspended: CheckedContinuation<Data, any Error>?
    var suspend = false
    var uploaded = 4
    var notes = "New release notes."
    func set(version: String) { self.version = version }
    func set(notes: String) { self.notes = notes }
    func set(uploaded: Int) { self.uploaded = uploaded }
    func set(failure: UpdateProblem?) { self.failure = failure }
    func hold() { suspend = true }
    func release() throws { suspended?.resume(returning: try data()); suspended = nil }
    private func data() throws -> Data {
        try JSONSerialization.data(withJSONObject: ["tag_name": "v" + version,
            "html_url": "https://github.com/roleband/roleband/releases/tag/v" + version,
            "body": notes, "draft": false, "prerelease": false,
            "assets": ReleaseFiles.all(version).sorted().prefix(uploaded).map { ["name": $0, "state": "uploaded"] }])
    }
    func fetch() async throws -> Data {
        calls += 1
        if suspend { return try await withCheckedThrowingContinuation { suspended = $0 } }
        if let failure { throw failure }
        return try data()
    }
    func waitForSuspension() async { while suspended == nil { await Task.yield() } }
}

private final class UpdateClock: @unchecked Sendable {
    private let lock = NSLock()
    private var value = Date(timeIntervalSince1970: 10000)
    func now() -> Date { lock.lock(); defer { lock.unlock() }; return value }
    func advance(_ seconds: Double) { lock.lock(); defer { lock.unlock() }; value.addTimeInterval(seconds) }
}

@MainActor private func withUpdates(_ body: @MainActor (LauncherUpdates, UpdateTransport, UpdateClock, UserDefaults) async throws -> Void) async throws {
    let preferences = UserDefaults.scratch("update-tests")
    let transport = UpdateTransport()
    let clock = UpdateClock()
    let updates = LauncherUpdates(preferences: preferences, fetch: { try await transport.fetch() }, now: { clock.now() }, authenticate: { _ in nil })
    defer { updates.stop() }
    try await body(updates, transport, clock, preferences)
}

@MainActor @Test func unansweredAndDeclinedChoicesNeverSendUpdateRequestsEvenWhenAskedOrStarted() async throws {
    try await withUpdates { updates, transport, _, preferences in
        updates.start()
        await updates.checkAndWait()
        #expect(await transport.calls == 0)
        updates.choose(.declined)
        updates.start()
        await updates.checkAndWait()
        #expect(await transport.calls == 0)
        #expect(preferences.string(forKey: "updateConsentLocale") == "en")
        let english = LauncherCopy(language: "en")
        #expect(preferences.string(forKey: "updateConsentText") == english.text("update-automatic"))
        #expect(preferences.object(forKey: "updateConsentAt") != nil)
    }
}

@MainActor @Test func anAppStampedWithAnotherRepositoryNeitherRestoresNorAcceptsAProductionOffer() async throws {
    try await withUpdates { updates, transport, clock, preferences in
        updates.choose(.manual)
        await updates.checkAndWait()
        #expect(updates.offered?.version == "0.2.0")
        let unstamped = LauncherUpdates(preferences: preferences, fetch: { try await transport.fetch() },
                                        now: { clock.now() }, repository: nil, authenticate: { _ in nil })
        defer { unstamped.stop() }
        #expect(unstamped.consent == .manual && unstamped.offered == nil)
        await transport.set(version: "0.3.0")
        await unstamped.checkAndWait()
        #expect(unstamped.offered == nil)
        #expect(unstamped.messageKey == "update-failed")
        let production = LauncherUpdates(preferences: preferences, fetch: { try await transport.fetch() }, now: { clock.now() }, authenticate: { _ in nil })
        defer { production.stop() }
        #expect(production.offered?.version == "0.2.0")
    }
}

@MainActor @Test func manualConsentAllowsOnlyExplicitChecksAndSurvivesRelaunchWithoutNetwork() async throws {
    try await withUpdates { updates, transport, clock, preferences in
        updates.choose(.manual)
        updates.start()
        await updates.checkAndWait(automatic: true)
        #expect(await transport.calls == 0)
        await updates.checkAndWait()
        #expect(await transport.calls == 1)
        #expect(updates.offered?.version == "0.2.0")
        #expect(updates.offersUpdate(launcher: "0.1.0", engine: "0.3.0"))
        #expect(!updates.offersUpdate(launcher: "0.2.0", engine: "0.3.0"))
        let restored = LauncherUpdates(preferences: preferences, fetch: { try await transport.fetch() }, now: { clock.now() }, authenticate: { _ in nil })
        defer { restored.stop() }
        restored.start()
        #expect(restored.consent == .manual && restored.offered?.version == "0.2.0")
        #expect(await transport.calls == 1)
    }
}

@MainActor @Test func dailyChecksThrottleFailedAttemptsAcrossRestartsAndRateLimitsAlsoBlockManualChecks() async throws {
    try await withUpdates { updates, transport, clock, preferences in
        await transport.set(failure: .unavailable)
        updates.choose(.daily)
        await updates.checkAndWait()
        #expect(await transport.calls == 1)
        #expect(updates.messageKey == "update-failed")
        let restored = LauncherUpdates(preferences: preferences, fetch: { try await transport.fetch() }, now: { clock.now() }, authenticate: { _ in nil })
        defer { restored.stop() }
        await restored.checkAndWait(automatic: true)
        #expect(await transport.calls == 1)
        clock.advance(86400)
        await transport.set(failure: .rateLimited(until: clock.now().addingTimeInterval(7200)))
        await restored.checkAndWait(automatic: true)
        await restored.checkAndWait()
        #expect(await transport.calls == 2)
        #expect(restored.messageKey == "update-rate-limited")
        clock.advance(7201)
        await transport.set(failure: nil)
        await restored.checkAndWait()
        #expect(await transport.calls == 3)
        #expect(restored.lastSuccess == clock.now())
    }
}

@MainActor @Test func anAttemptRecordedForAnotherRepositoryNeverDelaysThisFeedsFirstAutomaticCheck() async throws {
    try await withUpdates { updates, transport, clock, preferences in
        preferences.set(clock.now(), forKey: "updateLastAttempt")
        preferences.set("roleband/roleband-mac-update-trial", forKey: "updateLastAttemptFeed")
        updates.choose(.daily)
        await updates.checkAndWait(automatic: true)
        #expect(await transport.calls == 1)
        #expect(preferences.string(forKey: "updateLastAttemptFeed") == "roleband/roleband")
        // Production's own attempt now holds its next automatic check for a day.
        let restored = LauncherUpdates(preferences: preferences, fetch: { try await transport.fetch() }, now: { clock.now() }, authenticate: { _ in nil })
        defer { restored.stop() }
        await restored.checkAndWait(automatic: true)
        #expect(await transport.calls == 1)
        clock.advance(86400)
        await restored.checkAndWait(automatic: true)
        #expect(await transport.calls == 2)
    }
}

@MainActor @Test func failedAndOlderRepliesPreserveOffersAndPreviewNeverChangesInstalledHistory() async throws {
    try await withUpdates { updates, transport, _, preferences in
        let history = ["installation": "0.1.0"]
        preferences.set(history, forKey: "seenInstalledReleases")
        updates.choose(.manual)
        await updates.checkAndWait()
        await transport.set(failure: .invalidResponse)
        await updates.checkAndWait()
        #expect(updates.offered?.version == "0.2.0")
        #expect(updates.messageKey == "update-failed")
        await transport.set(failure: nil)
        await transport.set(version: "0.1.0")
        await updates.checkAndWait()
        #expect(updates.offered?.version == "0.2.0")
        #expect(updates.offersUpdate(launcher: "0.1.0", engine: "0.1.0"))
        #expect(preferences.dictionary(forKey: "seenInstalledReleases") as? [String: String] == history)
    }
}

@MainActor @Test func withdrawingPermissionCancelsTheCheckAndDiscardsALateReply() async throws {
    try await withUpdates { updates, transport, _, _ in
        updates.choose(.manual)
        await transport.hold()
        let inFlight = Task { await updates.checkAndWait() }
        await transport.waitForSuspension()
        updates.check()
        updates.start()
        #expect(await transport.calls == 1)
        updates.choose(.declined)
        #expect(!updates.checking)
        try await transport.release()
        await inFlight.value
        #expect(updates.offered == nil)
        #expect(updates.lastSuccess == nil)
        #expect(await transport.calls == 1)
    }
}

@Test func nativeConsentRemainsVerbatimEnglishInEverySupportedLanguage() {
    let english = LauncherCopy(language: "en")
    for language in ["es", "zh-Hans"] {
        for key in ["update-automatic"] {
            #expect(LauncherCopy(language: language).text(key) == english.text(key))
        }
    }
}

@MainActor @Test func anExistingRefusalStaysOfflineUntilAnExplicitManualRequestAndKeepsItsOriginalReceipt() async throws {
    try await withUpdates { _, transport, clock, preferences in
        preferences.set("declined", forKey: "updateConsent")
        preferences.set("Previously displayed wording", forKey: "updateConsentText")
        let restored = LauncherUpdates(preferences: preferences, fetch: { try await transport.fetch() }, now: { clock.now() }, authenticate: { _ in nil })
        defer { restored.stop() }
        restored.start()
        await restored.checkAndWait()
        #expect(!restored.needsChoice && !restored.automatic)
        #expect(await transport.calls == 0)
        #expect(preferences.string(forKey: "updateConsentText") == "Previously displayed wording")
        await restored.checkManuallyAndWait()
        #expect(!restored.needsChoice && !restored.automatic)
        #expect(restored.consent == .declined)
        #expect(await transport.calls == 1)
        #expect(preferences.string(forKey: "updateConsentText") == "Previously displayed wording")
    }
}

@MainActor @Test func turningTheSetupToggleOffKeepsAutomaticChecksOffWithoutBlockingALaterExplicitCheck() async throws {
    try await withUpdates { updates, transport, clock, preferences in
        #expect(updates.needsChoice)
        updates.setAutomaticChecks(false)
        #expect(!updates.needsChoice && !updates.automatic)
        #expect(preferences.string(forKey: "updateConsentText") == updates.text("update-automatic"))
        updates.start()
        await updates.checkAndWait(automatic: true)
        #expect(await transport.calls == 0)
        await updates.checkAndWait()
        #expect(await transport.calls == 1)
        let restored = LauncherUpdates(preferences: preferences, fetch: { try await transport.fetch() }, now: { clock.now() }, authenticate: { _ in nil })
        defer { restored.stop() }
        restored.start()
        #expect(!restored.needsChoice && !restored.automatic)
        #expect(await transport.calls == 1)
    }
}

@MainActor @Test func checkNowIsAnExplicitOneOffRequestWithoutEnablingAutomaticChecksOrCreatingAPrivacyReceipt() async throws {
    try await withUpdates { updates, transport, clock, preferences in
        #expect(updates.needsChoice && !updates.automatic)
        #expect(await transport.calls == 0)
        await updates.checkManuallyAndWait()
        #expect(await transport.calls == 1)
        #expect(updates.needsChoice && !updates.automatic)
        #expect(preferences.string(forKey: "updateConsentText") == nil)
        clock.advance(86401)
        updates.start()
        #expect(await transport.calls == 1)
    }
}

@MainActor @Test func turningAutomaticChecksOffCancelsDailyWorkAndDoesNotRewriteConsentOnRelaunch() async throws {
    try await withUpdates { updates, transport, clock, preferences in
        updates.setAutomaticChecks(true)
        await updates.checkAndWait(automatic: true)
        #expect(updates.automatic && !updates.needsChoice)
        let wording = updates.text("update-automatic")
        updates.setAutomaticChecks(false)
        #expect(!updates.automatic)
        #expect(preferences.string(forKey: "updateConsentText") == wording)
        clock.advance(86401)
        updates.start()
        await updates.checkAndWait(automatic: true)
        #expect(await transport.calls == 1)
        let restored = LauncherUpdates(preferences: preferences, fetch: { try await transport.fetch() }, now: { clock.now() }, authenticate: { _ in nil })
        defer { restored.stop() }
        restored.start()
        #expect(!restored.automatic && !restored.needsChoice)
        #expect(preferences.string(forKey: "updateConsentText") == wording)
    }
}

@MainActor @Test func checkCallbacksDistinguishManualDiscoveryFromAutomaticDiscoveryAndRespectTheDemoInterval() async throws {
    try await withUpdates { _, transport, clock, preferences in
        let updates = LauncherUpdates(preferences: preferences, fetch: { try await transport.fetch() },
                                      now: { clock.now() }, automaticInterval: 15, authenticate: { _ in nil })
        defer { updates.stop() }
        var choices: [Bool] = []
        var discoveries: [Bool] = []
        updates.automaticChoiceChanged = { choices.append($0) }
        updates.didCheck = { _, automatic in discoveries.append(automatic) }
        await updates.checkManuallyAndWait()
        #expect(discoveries == [false] && choices.isEmpty)
        updates.setAutomaticChecks(true)
        await updates.checkAndWait(automatic: true)
        #expect(await transport.calls == 1)
        clock.advance(16)
        await updates.checkAndWait(automatic: true)
        #expect(discoveries == [false, true])
        updates.setAutomaticChecks(false)
        clock.advance(16)
        await updates.checkAndWait(automatic: true)
        #expect(await transport.calls == 2)
        #expect(choices == [true, false])
    }
}

/// Release files attach after the release is published. A check in that window succeeds, offers and
/// announces nothing new and keeps the earlier offer; the check after the upload offers the release.
@MainActor @Test func aReleaseStillWaitingForItsFilesIsNeitherOfferedNorAnnouncedUntilTheyAreUploaded() async throws {
    try await withUpdates { updates, transport, _, _ in
        var discoveries: [String] = []
        updates.didCheck = { release, _ in discoveries.append(release.version) }
        await transport.set(version: "0.1.5")
        await updates.checkManuallyAndWait()
        #expect(updates.offered?.version == "0.1.5")
        await transport.set(version: "0.2.0")
        for uploaded in [0, 3] {
            await transport.set(uploaded: uploaded)
            await updates.checkManuallyAndWait()
            #expect(updates.messageKey == "update-checked")
            #expect(updates.offered?.version == "0.1.5")
        }
        #expect(discoveries == ["0.1.5"])
        await transport.set(uploaded: 4)
        await updates.checkManuallyAndWait()
        #expect(updates.offered?.version == "0.2.0")
        #expect(discoveries == ["0.1.5", "0.2.0"])
    }
}

/// The About row's title follows the check as it happens: unchecked never reads as up to date, a
/// check in flight covers the old result, and a failure covers an offer found earlier.
@MainActor @Test func theStatusRowSaysWhatTheLastCheckFoundAndNeverClaimsAnUncheckedSuccess() async throws {
    try await withUpdates { updates, transport, clock, _ in
        #expect(UpdateStatus.of(updates, offered: nil) == .never)
        await transport.hold()
        updates.checkManually()
        await transport.waitForSuspension()
        #expect(UpdateStatus.of(updates, offered: "0.2.0") == .checking)
        try await transport.release()
        await updates.checkAndWait()
        #expect(UpdateStatus.of(updates, offered: nil) == .current)
        #expect(UpdateStatus.of(updates, offered: "0.2.0") == .offered(version: "0.2.0"))

        let unheld = UpdateTransport()
        await unheld.set(failure: .unavailable)
        let failing = LauncherUpdates(preferences: .scratch("status"),
                                      fetch: { try await unheld.fetch() }, now: { clock.now() }, authenticate: { _ in nil })
        defer { failing.stop() }
        await failing.checkManuallyAndWait()
        #expect(UpdateStatus.of(failing, offered: "0.2.0") == .failed(rateLimited: false))
        await unheld.set(failure: .rateLimited(until: clock.now().addingTimeInterval(60)))
        await failing.checkManuallyAndWait()
        #expect(UpdateStatus.of(failing, offered: nil) == .failed(rateLimited: true))
    }
}

@MainActor
@Test func theOfferWindowUpdatesAnAppThatInstallsItsOwnUpdatesAndExplainsOnlyBesideACheckout() throws {
    let release = try OfferedRelease.decode(Data(#"{"tag_name":"v0.1.1","html_url":"https://github.com/roleband/roleband/releases/tag/v0.1.1","body":"","draft":false,"prerelease":false}"#.utf8), from: .production)
    var installs = 0
    var closes = 0
    let owned = OfferedReleaseView(release: release, copy: LauncherCopy(language: "en"), openPage: {}, close: { closes += 1 },
                                   install: { installs += 1 })
    #expect(owned.primaryKey == "update-install")
    owned.primary()
    #expect((installs, closes) == (1, 0))

    let checkout = OfferedReleaseView(release: release, copy: LauncherCopy(language: "en"), openPage: {}, close: { closes += 1 })
    #expect(checkout.primaryKey == "update-how")
    checkout.primary()
    #expect((installs, closes) == (1, 0))
}

private actor ReleaseSignatures {
    var forged: Set<String> = []
    var offline = false
    var asked: [String] = []
    var notices: [String: String] = [:]
    func forge(_ version: String) { forged.insert(version) }
    func set(offline: Bool) { self.offline = offline }
    func sign(_ version: String, notice: String) { notices[version] = notice }
    func check(_ version: String) throws -> String? {
        asked.append(version)
        if offline { throw URLError(.notConnectedToInternet) }
        if forged.contains(version) { throw ArtifactProblem.invalidSignature }
        return notices[version]
    }
}

@MainActor private final class Announcements { var versions: [String] = [] }

/// The release listing is not signed: a newer release whose signed metadata fails is neither offered
/// nor announced, and an earlier verified offer stays. A check that cannot read the metadata failed.
@MainActor @Test func aReleaseWhoseSignedMetadataFailsIsNeitherOfferedNorAnnounced() async throws {
    let preferences = UserDefaults.scratch("update-signed-offer")
    let transport = UpdateTransport()
    let signatures = ReleaseSignatures()
    let updates = LauncherUpdates(preferences: preferences, fetch: { try await transport.fetch() },
                                  authenticate: { try await signatures.check($0) })
    defer { updates.stop() }
    let announced = Announcements()
    updates.didCheck = { release, _ in announced.versions.append(release.version) }
    updates.choose(.manual)

    await updates.checkManuallyAndWait()
    #expect(updates.offered?.version == "0.2.0")
    #expect(announced.versions == ["0.2.0"])

    await transport.set(version: "0.3.0")
    await signatures.forge("0.3.0")
    await updates.checkManuallyAndWait()
    #expect(updates.offered?.version == "0.2.0")
    #expect(announced.versions == ["0.2.0"])
    #expect(updates.messageKey == "update-checked")
    let stored = try #require(preferences.data(forKey: "offeredRelease"))
    #expect(try OfferedRelease.decode(stored, from: .production).version == "0.2.0")

    await transport.set(version: "0.4.0")
    await signatures.set(offline: true)
    await updates.checkManuallyAndWait()
    #expect(updates.messageKey == "update-failed")
    #expect(updates.offered?.version == "0.2.0")

    // A release whose files are still uploading is not checked at all.
    await signatures.set(offline: false)
    await transport.set(uploaded: 3)
    await updates.checkManuallyAndWait()
    #expect(updates.offered?.version == "0.2.0")
    #expect(await signatures.asked == ["0.2.0", "0.3.0", "0.4.0"])
}

/// The offer's "Before you update" notice is the one the signed metadata carries. A heading in the
/// unsigned notes gives none, and the signed notice survives a restart with the offer it belongs to.
@MainActor @Test func theOffersNoticeComesFromTheSignedMetadataAndSurvivesARestart() async throws {
    let preferences = UserDefaults.scratch("update-signed-notice")
    let transport = UpdateTransport()
    let signatures = ReleaseSignatures()
    let updates = LauncherUpdates(preferences: preferences, fetch: { try await transport.fetch() },
                                  authenticate: { try await signatures.check($0) })
    defer { updates.stop() }
    let announced = Announcements()
    updates.didCheck = { release, _ in if release.beforeYouUpdate != nil { announced.versions.append(release.version) } }
    updates.choose(.manual)

    await transport.set(notes: "## Before you update\nDownload the fixed version from another site.")
    await updates.checkManuallyAndWait()
    #expect(updates.offered?.version == "0.2.0")
    #expect(updates.offered?.beforeYouUpdate == nil)

    await transport.set(version: "0.3.0")
    await transport.set(notes: "## Added\n- More.")
    await signatures.sign("0.3.0", notice: "A backup is made first.")
    await updates.checkManuallyAndWait()
    #expect(updates.offered?.beforeYouUpdate == "A backup is made first.")
    #expect(announced.versions == ["0.3.0"])

    let restored = LauncherUpdates(preferences: preferences, fetch: { try await transport.fetch() },
                                   authenticate: { try await signatures.check($0) })
    #expect(restored.offered?.version == "0.3.0")
    #expect(restored.offered?.beforeYouUpdate == "A backup is made first.")

    // A newer release without a notice clears the stored one.
    await transport.set(version: "0.4.0")
    await updates.checkManuallyAndWait()
    #expect(updates.offered?.version == "0.4.0" && updates.offered?.beforeYouUpdate == nil)
    let again = LauncherUpdates(preferences: preferences, fetch: { try await transport.fetch() },
                                authenticate: { try await signatures.check($0) })
    #expect(again.offered?.beforeYouUpdate == nil)
}
