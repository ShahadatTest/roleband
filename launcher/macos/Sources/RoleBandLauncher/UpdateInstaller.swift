import AppKit
import Foundation
import LauncherCore

struct UpdateInstallerOperations: Sendable {
    var reserve: @Sendable () throws -> Int64
    var download: @Sendable (String, Int64, @escaping @Sendable (DownloadProgress) -> Void) async throws -> DownloadedUpdate
    var prepare: @Sendable (DownloadedUpdate) async throws -> UpdatePlan
    /// Deletes a downloaded release that failed its check.
    var discard: @Sendable (String) -> Void
    /// Starts the helper and quits, so the helper can replace this app.
    var handOff: @MainActor @Sendable (UpdatePlan) throws -> Void
}

extension UpdateInstallerOperations {
    static func live(installed: URL, home: URL, cache: URL, bundle: Bundle = .main) -> Self {
        let downloader = UpdateDownloader(cache: cache)
        return Self(
            reserve: { try DiskUsage.updateReserve(installed: installed, home: home) },
            download: { version, reserve, progress in
                try await downloader.download(version: version, in: bundle, reserveBytes: reserve, progress: progress)
            },
            prepare: { try await UpdatePlan.prepare($0, installed: installed, home: home) },
            discard: { version in try? FileManager.default.removeItem(at: cache.appendingPathComponent("update-" + version)) },
            handOff: { plan in
                guard let executable = bundle.executableURL else { throw UpdateHelperProblem.invalidPlan }
                try plan.markHandOff()
                try UpdateHelperProcess.spawn(executable: executable, recovering: false, id: plan.id, home: home)
                AppQuit.request()
            })
    }
}

/// One update from the press of Update until this app quits for the helper. Update is the only
/// press: a verified update restarts at once, and a running scan stops with what it found kept.
@MainActor
final class UpdateInstaller: ObservableObject {
    @Published private(set) var activity: UpdateActivity?
    @Published private(set) var version: String?
    private let operations: UpdateInstallerOperations
    private var task: Task<Void, Never>?
    private var plan: UpdatePlan?
    private var generation = 0

    init(operations: UpdateInstallerOperations) {
        self.operations = operations
    }

    /// Puts the line in one state with nothing behind it, for `--render-panel`.
    func show(_ activity: UpdateActivity, version: String) {
        self.activity = activity
        self.version = version
    }

    func install(_ version: String) {
        guard idle, ReleaseVersion(version) != nil else { return }
        // A refused quit keeps its plan, and that plan's helper may still be waiting for this app to
        // quit. Handing the same plan over again means a second helper finds its lease taken and
        // stands aside, so two helpers never wait to replace this app, and the hand-off restarts the
        // first helper's wait.
        if plan != nil { return restart() }
        generation += 1
        let token = generation
        self.version = version
        activity = .downloading(received: 0, total: 0)
        let operations = operations
        let relay = ProgressRelay()
        task = Task {
            do {
                // The reserve walks the installed app and the database: tens of thousands of files.
                let reserve = try await Task.detached(priority: .userInitiated) { try operations.reserve() }.value
                let update = try await operations.download(version, reserve) { progress in
                    guard relay.store(progress) else { return }
                    Task { @MainActor in if let latest = relay.take() { self.report(latest, token: token) } }
                }
                guard generation == token else { return }
                activity = .verifying
                let plan = try await operations.prepare(update)
                guard generation == token else {
                    try? FileManager.default.removeItem(at: plan.paths.directory)
                    return
                }
                self.plan = plan
                restart()
            } catch {
                guard generation == token else { return }
                guard let failure = UpdateFailure.classify(error) else { activity = nil; return }
                if failure == .check || failure == .signer { operations.discard(version) }
                activity = .failed(failure)
            }
        }
    }

    /// Stops a download or check in progress. Nothing was installed, so nothing needs undoing.
    func cancel() {
        guard activity?.inProgress == true else { return }
        generation += 1
        task?.cancel()
        task = nil
        activity = nil
    }

    private var idle: Bool {
        if case .failed = activity { return true }
        return activity == nil
    }

    /// The quit the helper waits for was refused, so this app keeps running and nothing was replaced.
    func quitRefused() {
        if activity == .restarting { activity = .failed(.restart) }
    }

    private func restart() {
        guard let plan else { return }
        activity = .restarting
        do { try operations.handOff(plan) } catch {
            try? FileManager.default.removeItem(at: plan.paths.directory)
            self.plan = nil
            activity = .failed(.restart)
        }
    }

    private func report(_ progress: DownloadProgress, token: Int) {
        // Progress hops here on its own task, so a late report never overrides a later phase.
        guard generation == token, let activity, activity.inProgress, activity != .verifying else { return }
        switch progress.phase {
        case .metadata: self.activity = .downloading(received: 0, total: 0)
        case .downloading:
            // The line shows whole megabytes; a chunk inside the one it shows would redraw it unchanged.
            if case .downloading(let shown, let total) = activity, total == progress.total,
               UpdateSize.wholeMegabytes(shown) == UpdateSize.wholeMegabytes(progress.received) { return }
            self.activity = .downloading(received: progress.received, total: progress.total)
        case .offline: self.activity = .paused(received: progress.received, total: progress.total)
        case .verifying, .ready: self.activity = .verifying
        }
    }

    func installAndWait(_ version: String) async {
        install(version)
        await task?.value
    }
}

/// Holds the newest download progress for one main-actor hop at a time, so a fast download
/// queues one update for the line instead of one per network chunk, and the last value still lands.
private final class ProgressRelay: @unchecked Sendable {
    private let lock = NSLock()
    private var latest: DownloadProgress?
    /// Keeps the value; true when no hop is waiting to read one.
    func store(_ value: DownloadProgress) -> Bool {
        lock.withLock {
            defer { latest = value }
            return latest == nil
        }
    }
    func take() -> DownloadProgress? {
        lock.withLock {
            defer { latest = nil }
            return latest
        }
    }
}
