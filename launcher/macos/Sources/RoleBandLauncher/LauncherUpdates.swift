import Foundation
import LauncherCore
import SwiftUI

enum UpdateConsent: String {
    case undecided, daily, manual, declined
    var permitsRequests: Bool { self == .daily || self == .manual }
}

@MainActor
final class LauncherUpdates: ObservableObject {
    @Published private(set) var consent: UpdateConsent
    @Published private(set) var offered: OfferedRelease?
    @Published private(set) var checking = false
    @Published private(set) var messageKey: String?
    @Published private(set) var lastSuccess: Date?
    @Published var notificationsDenied = false
    /// Unset until the person turns notices on or off; until then notices follow automatic checks.
    @Published private var noticeChoice: Bool?
    /// A version that was rolled back is not offered again on its own; Check now can still find it.
    @Published private(set) var suppressedVersion: String?
    private let preferences: UserDefaults
    private let fetch: @Sendable () async throws -> Data
    /// Checks a version's signed metadata against this app's release keys and returns its signed notice;
    /// throws `ArtifactProblem` when it fails.
    private let authenticate: @Sendable (String) async throws -> String?
    private let repository: UpdateRepository?
    private let now: @Sendable () -> Date
    private let copy: LauncherCopy
    private let automaticInterval: TimeInterval
    var automaticChoiceChanged: ((Bool) -> Void)?
    var didCheck: ((OfferedRelease, Bool) -> Void)?
    var noticesChanged: ((Bool) -> Void)?
    private var task: Task<Void, Never>?
    private var timer: Timer?
    private var generation = 0
    init(preferences: UserDefaults = .standard, copy: LauncherCopy = LauncherCopy(),
         fetch: @escaping @Sendable () async throws -> Data = UpdateClient.read,
         now: @escaping @Sendable () -> Date = { Date() }, automaticInterval: TimeInterval = 86400,
         repository: UpdateRepository? = UpdateRepository.stamped(),
         authenticate: @escaping @Sendable (String) async throws -> String? = {
             try await UpdateDownloader.authenticate(version: $0).beforeYouUpdate
         }) {
        self.preferences = preferences
        self.repository = repository
        self.copy = copy
        self.fetch = fetch
        self.authenticate = authenticate
        self.now = now
        self.automaticInterval = max(1, automaticInterval)
        consent = UpdateConsent(rawValue: preferences.string(forKey: "updateConsent") ?? "") ?? .undecided
        offered = repository.flatMap { repository in
            preferences.data(forKey: "offeredRelease").flatMap { try? OfferedRelease.decode($0, from: repository) }
                .map { $0.signed(notice: preferences.string(forKey: "offeredNotice")) }
        }
        lastSuccess = preferences.object(forKey: "updateLastSuccess") as? Date
        noticeChoice = preferences.object(forKey: "updateNotices") as? Bool
        suppressedVersion = preferences.string(forKey: "updateSuppressedVersion")
    }
    var notices: Bool { noticeChoice ?? automatic }
    func setNotices(_ enabled: Bool) {
        guard enabled != notices || noticeChoice == nil else { return }
        noticeChoice = enabled
        preferences.set(enabled, forKey: "updateNotices")
        if enabled { noticesChanged?(true) }
    }
    func suppress(_ version: String) {
        suppressedVersion = version
        preferences.set(version, forKey: "updateSuppressedVersion")
    }
    func text(_ key: String) -> String { copy.text(key) }
    var needsChoice: Bool { consent == .undecided }
    var automatic: Bool { consent == .daily }
    func choose(_ choice: UpdateConsent, requestNotifications: Bool = true) {
        guard choice != .undecided, choice != consent else { return }
        let wording = text("update-automatic")
        stop()
        consent = choice
        messageKey = nil
        preferences.set(choice.rawValue, forKey: "updateConsent")
        preferences.set(wording, forKey: "updateConsentText")
        preferences.set("en", forKey: "updateConsentLocale")
        preferences.set(now(), forKey: "updateConsentAt")
        if requestNotifications { automaticChoiceChanged?(choice == .daily && notices) }
        if choice == .daily { start() }
    }
    func setAutomaticChecks(_ enabled: Bool, requestNotifications: Bool = true) {
        choose(enabled ? .daily : .manual, requestNotifications: requestNotifications)
    }
    func checkManually() { check(explicitlyRequested: true) }
    func start() {
        guard consent == .daily else { return }
        check(automatic: true)
    }
    func stop() {
        generation += 1
        task?.cancel()
        task = nil
        timer?.invalidate()
        timer = nil
        checking = false
    }
    /// The next automatic check: a day after the last attempt on this app's feed, so an attempt the
    /// preferences record for any other repository never delays this one's first check.
    private var nextAutomatic: Date {
        let sameFeed = repository != nil && preferences.string(forKey: "updateLastAttemptFeed") == repository?.rawValue
        let last = sameFeed ? preferences.object(forKey: "updateLastAttempt") as? Date : nil
        let attempt = last?.addingTimeInterval(automaticInterval) ?? .distantPast
        let blocked = preferences.object(forKey: "updateBlockedUntil") as? Date ?? .distantPast
        return max(attempt, blocked)
    }
    func check(automatic: Bool = false, explicitlyRequested: Bool = false) {
        guard consent.permitsRequests || explicitlyRequested, !checking, !automatic || consent == .daily else { return }
        timer?.invalidate()
        let blocked = preferences.object(forKey: "updateBlockedUntil") as? Date ?? .distantPast
        guard now() >= blocked else { messageKey = "update-rate-limited"; schedule(); return }
        guard !automatic || now() >= nextAutomatic else { schedule(); return }
        checking = true
        messageKey = nil
        preferences.set(now(), forKey: "updateLastAttempt")
        preferences.set(repository?.rawValue, forKey: "updateLastAttemptFeed")
        let token = generation
        task = Task {
            defer {
                if generation == token { checking = false; schedule() }
            }
            do {
                let data = try await fetch()
                try Task.checkCancellation()
                guard generation == token, consent.permitsRequests || explicitlyRequested else { return }
                guard let repository else { throw UpdateProblem.unavailable }
                let release = try OfferedRelease.decode(data, from: repository)
                // Until its files are uploaded, the newest release is not offered and the check found nothing new.
                // The listing is not signed, so a release is offered only once its signed metadata verifies;
                // one that fails is treated as no release at all, while a network failure fails the check.
                let signed: OfferedRelease?
                if release.filesReady {
                    do { signed = release.signed(notice: try await authenticate(release.version)) } catch is ArtifactProblem { signed = nil }
                } else { signed = nil }
                try Task.checkCancellation()
                guard generation == token, consent.permitsRequests || explicitlyRequested else { return }
                if let signed {
                    // A stale or reordered upstream release never replaces a newer cached offer.
                    if offered.map({ ReleaseVersion($0.version)! <= ReleaseVersion(release.version)! }) ?? true {
                        offered = signed
                        preferences.set(data, forKey: "offeredRelease")
                        preferences.set(signed.beforeYouUpdate, forKey: "offeredNotice")
                    }
                    if explicitlyRequested && release.version == suppressedVersion {
                        suppressedVersion = nil
                        preferences.removeObject(forKey: "updateSuppressedVersion")
                    }
                }
                lastSuccess = now()
                preferences.set(lastSuccess, forKey: "updateLastSuccess")
                messageKey = "update-checked"
                if let signed { didCheck?(signed, automatic) }
            } catch is CancellationError { return }
            catch {
                guard generation == token, consent.permitsRequests || explicitlyRequested else { return }
                if case UpdateProblem.rateLimited(let until) = error {
                    preferences.set(until, forKey: "updateBlockedUntil")
                    messageKey = "update-rate-limited"
                } else { messageKey = "update-failed" }
            }
        }
    }
    private func schedule() {
        timer?.invalidate()
        guard consent == .daily else { return }
        let next = Timer(timeInterval: max(1, nextAutomatic.timeIntervalSince(now())), repeats: false) { [weak self] _ in
            Task { @MainActor in self?.start() }
        }
        next.tolerance = min(60, automaticInterval / 10)
        RunLoop.main.add(next, forMode: .common)
        timer = next
    }
    func checkAndWait(automatic: Bool = false) async { check(automatic: automatic); await task?.value }
    func checkManuallyAndWait() async { checkManually(); await task?.value }
    func offersUpdate(launcher: String?, engine: String?) -> Bool {
        guard let offered, offered.version != suppressedVersion, let release = ReleaseVersion(offered.version) else { return false }
        return [launcher, engine].compactMap { $0.flatMap(ReleaseVersion.init) }.contains { $0 < release }
    }
}

/// The one line the About tab's update row stands for. A check in flight outranks what the last
/// one found, and a failed check outranks an older offer: the row says what happened just now.
enum UpdateStatus: Equatable {
    case checking, failed(rateLimited: Bool), never, offered(version: String), current

    @MainActor static func of(_ updates: LauncherUpdates, offered: String?) -> UpdateStatus {
        if updates.checking { return .checking }
        switch updates.messageKey {
        case "update-rate-limited": return .failed(rateLimited: true)
        case "update-failed": return .failed(rateLimited: false)
        default: break
        }
        if let offered { return .offered(version: offered) }
        return updates.lastSuccess == nil ? .never : .current
    }
}
