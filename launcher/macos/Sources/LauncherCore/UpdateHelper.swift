import Darwin
import Foundation

public enum UpdateHelperProblem: Error, Sendable { case invalidPlan, helperRunning }

/// What the running app hands to the out-of-process helper after it staged a verified candidate.
/// The signing identity is recorded from the app that prepared the update, so the helper can check
/// every bundle against it, including after that app has been moved aside.
public struct UpdatePlan: Codable, Equatable, Sendable {
    public struct Parent: Codable, Equatable, Sendable {
        public let pid: Int32
        public let seconds: UInt64
        public let microseconds: UInt64
    }
    public let format: Int
    public let id: UUID
    public let installed: String
    public let home: String
    public let from: String
    public let fromCommit: String
    public let to: String
    public let toCommit: String
    public let publicKey: Data
    /// Absent in plans written before the app carried a spare key.
    public let spareKey: Data?
    public let certificateSHA256: String
    /// Absent in plans written before apps carried a signing rule.
    public let signingRule: String?
    public let parent: Parent

    public var paths: UpdateTransactionPaths {
        UpdateTransactionPaths(installed: URL(fileURLWithPath: installed), home: URL(fileURLWithPath: home), id: id)
    }
    public var candidate: URL { paths.directory.appendingPathComponent("candidate/RoleBand.app") }
    var file: URL { paths.directory.appendingPathComponent("plan.json") }
    /// Rewritten at every hand-off. A helper still waiting for the app to quit sees a new hand-off and
    /// waits its full time again, so a Retry pressed as that helper was about to give up still has a
    /// helper waiting when the app quits.
    var handOffMark: URL { paths.directory.appendingPathComponent("hand-off") }
    var trust: InstalledUpdateIdentity {
        InstalledUpdateIdentity(version: from, commit: fromCommit, publicKey: publicKey, spareKey: spareKey,
                                certificateSHA256: certificateSHA256, signingRule: signingRule)
    }

    init(id: UUID, installed: URL, home: URL, trust: InstalledUpdateIdentity, to: String, toCommit: String, parent: pid_t) throws {
        let paths = UpdateTransactionPaths(installed: installed, home: home, id: id)
        guard let process = OwnedProcess.read(parent) else { throw UpdateHelperProblem.invalidPlan }
        self.init(format: 1, id: id, installed: paths.installed.path, home: paths.home.path, from: trust.version,
                  fromCommit: trust.commit, to: to, toCommit: toCommit, publicKey: trust.publicKey,
                  spareKey: trust.spareKey, certificateSHA256: trust.certificateSHA256, signingRule: trust.signingRule,
                  parent: Parent(pid: process.pid, seconds: process.seconds, microseconds: process.microseconds))
        try validate()
    }

    private init(format: Int, id: UUID, installed: String, home: String, from: String, fromCommit: String, to: String,
                 toCommit: String, publicKey: Data, spareKey: Data?, certificateSHA256: String, signingRule: String?,
                 parent: Parent) {
        self.format = format; self.id = id; self.installed = installed; self.home = home; self.from = from
        self.fromCommit = fromCommit; self.to = to; self.toCommit = toCommit; self.publicKey = publicKey
        self.spareKey = spareKey; self.certificateSHA256 = certificateSHA256; self.signingRule = signingRule
        self.parent = parent
    }

    /// Stages the authenticated image beside the plan and records which process waits to be replaced.
    public static func prepare(_ update: DownloadedUpdate, installed: URL, home: URL,
                               stager: UpdateImageStager = UpdateImageStager()) async throws -> UpdatePlan {
        let id = UUID()
        let paths = UpdateTransactionPaths(installed: installed, home: home, id: id)
        try PrivateFiles.directory(paths.directory)
        do {
            let candidate = paths.directory.appendingPathComponent("candidate/RoleBand.app")
            let trust = try await stager.stage(update, installed: paths.installed, destination: candidate)
            let plan = try UpdatePlan(id: id, installed: paths.installed, home: paths.home, trust: trust,
                                      to: update.artifact.version, toCommit: update.artifact.commit, parent: getpid())
            try plan.save()
            return plan
        } catch {
            try? FileManager.default.removeItem(at: paths.directory)
            throw error
        }
    }

    public func markHandOff() throws {
        try PrivateFiles.write(Data(UUID().uuidString.utf8), to: handOffMark)
    }

    func save() throws {
        try PrivateFiles.directory(paths.directory)
        try PrivateFiles.write(try JSONEncoder().encode(self), to: file)
    }

    public static func load(home: URL, id: UUID) throws -> UpdatePlan {
        let folder = UpdateTransactionPaths(installed: home, home: home, id: id).directory
        try PrivateFiles.requireDirectory(folder)
        let data = try PrivateFiles.read(folder.appendingPathComponent("plan.json"), limit: 16384)
        guard let plan = try? JSONDecoder().decode(UpdatePlan.self, from: data), plan.id == id,
              plan.home == home.resolvingSymlinksInPath().standardizedFileURL.path else { throw UpdateHelperProblem.invalidPlan }
        try plan.validate()
        return plan
    }

    private func validate() throws {
        func hexadecimal(_ value: String, _ length: Int) -> Bool {
            value.utf8.count == length && value.utf8.allSatisfy { (48...57).contains($0) || (97...102).contains($0) }
        }
        guard format == 1, paths.installed.path == installed, paths.home.path == home,
              AppLocation.isInstalled(paths.installed, home: paths.home),
              let old = ReleaseVersion(from), let new = ReleaseVersion(to), old < new,
              hexadecimal(fromCommit, 40), hexadecimal(toCommit, 40), hexadecimal(certificateSHA256, 64),
              publicKey.count == 32, spareKey == nil || (spareKey?.count == 32 && spareKey != publicKey),
              signingRule == nil || (signingRule?.isEmpty == false && signingRule!.utf8.count <= 1024),
              parent.pid > 1 else { throw UpdateHelperProblem.invalidPlan }
    }

    func commit(for version: String) throws -> String {
        if version == to { return toCommit }
        if version == from { return fromCommit }
        throw UpdateHelperProblem.invalidPlan
    }
}

/// Held for the helper's whole life. A launch that finds it held leaves the update to the helper.
final class HelperLease: @unchecked Sendable {
    private let descriptor: Int32

    init(_ directory: URL) throws {
        let fd = open(directory.appendingPathComponent("helper.lock").path, O_CREAT | O_RDWR | O_NOFOLLOW | O_CLOEXEC, 0o600)
        guard fd >= 0 else { throw UpdateHelperProblem.helperRunning }
        var info = stat()
        guard fstat(fd, &info) == 0, info.st_mode & S_IFMT == S_IFREG, info.st_uid == getuid(),
              info.st_mode & 0o077 == 0, flock(fd, LOCK_EX | LOCK_NB) == 0 else {
            close(fd); throw UpdateHelperProblem.helperRunning
        }
        descriptor = fd
    }

    deinit { flock(descriptor, LOCK_UN); close(descriptor) }

    static func held(_ directory: URL) -> Bool {
        let fd = open(directory.appendingPathComponent("helper.lock").path, O_RDONLY | O_NOFOLLOW | O_CLOEXEC)
        guard fd >= 0 else { return false }
        defer { close(fd) }
        if flock(fd, LOCK_SH | LOCK_NB) == 0 { flock(fd, LOCK_UN); return false }
        return errno == EWOULDBLOCK
    }
}

/// What an owned app must do about earlier updates before it may start its engine.
public enum UpdateStartup: Equatable, Sendable {
    case proceed
    /// A helper is replacing or restoring the app; it opens the right version when it finishes.
    case helperAtWork
    /// An update stopped part-way with no helper left. The database may be migrated, so the old
    /// engine must not start until the helper restores it.
    case recover(UUID)
    /// A recovery helper ran for this update and could not finish it. Nothing starts until the person
    /// asks for another try.
    case recoveryFailed(UUID)
    /// A journal exists that cannot be read or belongs to another app location while unfinished.
    case untrustedJournal(UUID)

    public static func decide(installed: URL, home: URL, version: String) -> Self {
        let root = HomeLayout(home).data.appendingPathComponent("updates")
        guard let entries = try? FileManager.default.contentsOfDirectory(at: root, includingPropertiesForKeys: nil) else {
            return .proceed
        }
        var recover: UUID?
        var failed: UUID?
        var untrusted: UUID?
        for entry in entries.sorted(by: { $0.lastPathComponent < $1.lastPathComponent }) {
            guard let id = UUID(uuidString: entry.lastPathComponent) else { continue }
            let paths = UpdateTransactionPaths(installed: installed, home: home, id: id)
            let helper = HelperLease.held(paths.directory)
            let journal: UpdateJournal?
            do { journal = try UpdateTransaction.journal(paths, anyLocation: true) } catch {
                if helper { return .helperAtWork }
                untrusted = untrusted ?? id
                continue
            }
            guard let journal else {
                // A plan with no journal: the helper is still waiting for its app to quit, or it never ran.
                if helper { return .helperAtWork }
                continue
            }
            if journal.phase.finished { continue }
            if helper {
                // The helper opened this version and is waiting for it to report healthy.
                if journal.phase == .checking && journal.to == version && journal.installed == paths.installed.path { continue }
                return .helperAtWork
            }
            if journal.installed != paths.installed.path { untrusted = untrusted ?? id }
            else if FileManager.default.fileExists(atPath: paths.recoveryFailed.path) { failed = failed ?? id }
            else { recover = recover ?? id }
        }
        if let recover { return .recover(recover) }
        if let failed { return .recoveryFailed(failed) }
        if let untrusted { return .untrustedJournal(untrusted) }
        return .proceed
    }
}

public enum UpdateHelperOutcome: String, Sendable {
    case committed, rolledBack
    /// Nothing was replaced; the app that quit was opened again.
    case unchanged
    /// The app never quit, so nothing was touched.
    case parentRunning
    case busy
    /// The update could not finish. After a failed recovery the app opens only to say so: with the
    /// failure recorded it starts no engine, so nothing opens unrestored data.
    case needsAttention
}

/// Runs in its own process so it outlives the app it replaces.
public struct UpdateHelper: Sendable {
    let plan: UpdatePlan
    let operations: UpdateInstallOperations
    let parentTimeout: TimeInterval
    let pause: @Sendable () async throws -> Void
    let note: @Sendable (String) -> Void

    public init(plan: UpdatePlan, operations: UpdateInstallOperations, note: @escaping @Sendable (String) -> Void = { _ in }) {
        self.init(plan: plan, operations: operations, parentTimeout: 120,
                  pause: { try await Task.sleep(for: .milliseconds(100)) }, note: note)
    }

    init(plan: UpdatePlan, operations: UpdateInstallOperations, parentTimeout: TimeInterval,
         pause: @escaping @Sendable () async throws -> Void, note: @escaping @Sendable (String) -> Void = { _ in }) {
        self.plan = plan; self.operations = operations; self.parentTimeout = parentTimeout
        self.pause = pause; self.note = note
    }

    public func apply() async -> UpdateHelperOutcome { await run(recovering: false) }
    /// The app opens after the lease is gone, or its startup would leave the update to this helper.
    public func recover() async -> UpdateHelperOutcome {
        let outcome = await run(recovering: true)
        if outcome == .needsAttention, FileManager.default.fileExists(atPath: plan.paths.recoveryFailed.path) {
            do { try await operations.launch(plan.paths.installed) } catch { note("reopen: \(error)") }
        }
        return outcome
    }

    private func run(recovering: Bool) async -> UpdateHelperOutcome {
        guard let lease = await lease() else { return .busy }
        defer { withExtendedLifetime(lease) {} }
        guard await parentExited() else { return .parentRunning }
        let transaction = UpdateTransaction(paths: plan.paths, operations: operations)
        do {
            let phase = recovering ? try await transaction.recover()
                : try await transaction.install(candidate: plan.candidate, from: plan.from, to: plan.to)
            clean(after: phase)
            return phase == .committed ? .committed : .rolledBack
        } catch {
            note("update \(plan.id.uuidString): \(String(describing: error).prefix(512))")
            // No journal means the installed app and database were never touched.
            let untouched: Bool
            do { untouched = try UpdateTransaction.journal(plan.paths) == nil } catch { untouched = false }
            guard untouched else {
                if recovering { try? PrivateFiles.write(Data(), to: plan.paths.recoveryFailed) }
                return .needsAttention
            }
            if !FileManager.default.fileExists(atPath: plan.paths.stage.appendingPathComponent("previous.app").path) {
                try? FileManager.default.removeItem(at: plan.paths.stage)
            }
            try? FileManager.default.removeItem(at: plan.candidate.deletingLastPathComponent())
            do { try await operations.launch(plan.paths.installed) } catch { note("reopen: \(error)") }
            return .unchanged
        }
    }

    /// The lock probe in `UpdateStartup` holds the lease for an instant, so a fresh helper retries briefly.
    private func lease() async -> HelperLease? {
        for _ in 0..<20 {
            if let lease = try? HelperLease(plan.paths.directory) { return lease }
            try? await Task.sleep(for: .milliseconds(50))
        }
        return nil
    }

    private func parentExited() async -> Bool {
        var handOff = try? Data(contentsOf: plan.handOffMark)
        var deadline = ProcessInfo.processInfo.systemUptime + parentTimeout
        while let process = OwnedProcess.read(plan.parent.pid), process.seconds == plan.parent.seconds,
              process.microseconds == plan.parent.microseconds {
            let latest = try? Data(contentsOf: plan.handOffMark)
            if latest != handOff {
                handOff = latest
                deadline = ProcessInfo.processInfo.systemUptime + parentTimeout
            }
            guard ProcessInfo.processInfo.systemUptime < deadline else { return false }
            do { try await pause() } catch { return false }
        }
        return true
    }

    /// App bundles are re-downloadable and the logs stay in the home folder, so finished
    /// transactions drop them. Database copies are user data and stay.
    private func clean(after phase: InstallPhase) {
        let manager = FileManager.default
        try? manager.removeItem(at: plan.candidate.deletingLastPathComponent())
        try? manager.removeItem(at: plan.paths.recoveryFailed)
        switch phase {
        case .committed: try? manager.removeItem(at: plan.paths.stage)
        case .rolledBack:
            for app in [plan.paths.failedApp, plan.paths.next] { try? manager.removeItem(at: app) }
            rmdir(plan.paths.stage.path)
        default: break
        }
    }
}

public extension UpdateHelper {
    /// Live boundaries. `open` launches an app through Launch Services and returns its process id.
    static func live(plan: UpdatePlan, open: @escaping @Sendable (URL) async throws -> pid_t) -> UpdateInstallOperations {
        let verifier = UpdateBundleVerifier()
        let launched = LaunchedApp()
        let resources = plan.paths.installed.appendingPathComponent("Contents/Resources")
        return UpdateInstallOperations(validate: { app, version in
            try await verifier.validate(app, version: version, commit: try plan.commit(for: version), trust: plan.trust)
        }, stop: {
            try await launched.stop()
            // Reaping reads the engine's own record and marker; it makes no API call, so no instance is needed.
            let installation = Installation(product: "roleband", instance: String(repeating: "0", count: 24),
                                            apiOrigin: "http://127.0.0.1:\(Installation.ownedPort)", version: plan.from, format: 1)
            let configuration = try HostConfiguration(resources: resources, home: plan.paths.home, installation: installation)
            try await EngineHost(configuration: configuration).reclaim()
        }, launch: { app in
            await launched.track(try await open(app))
        }, healthy: { version in
            let installation = try Installation.owned(resources: resources, version: version)
            guard try await StatusClient.read(installation).engineVersion == version else { return false }
            let health = try await EngineHealthClient.read(installation)
            return health.ready && !health.failed
        }, preparing: { version in
            guard let installation = try? Installation.owned(resources: resources, version: version),
                  let health = try? await EngineHealthClient.read(installation) else { return false }
            return health.version == version && health.preparation?.database == "creating"
        })
    }
}

/// The app the helper opened. Rollback stops it before restoring its database.
actor LaunchedApp {
    private var process: OwnedProcess?
    private let grace: TimeInterval

    init(grace: TimeInterval = 30) { self.grace = grace }

    func track(_ pid: pid_t) { process = OwnedProcess.read(pid) }

    /// SIGTERM takes the app's normal quit path, which stops its engine; SIGKILL bounds a hung quit.
    func stop() async throws {
        guard let process else { return }
        self.process = nil
        try process.signal(SIGTERM)
        let deadline = ProcessInfo.processInfo.systemUptime + grace
        while process.isAlive {
            if ProcessInfo.processInfo.systemUptime >= deadline { try process.signal(SIGKILL) }
            if ProcessInfo.processInfo.systemUptime > deadline + 5 { throw HostProblem.stopFailed }
            try await Task.sleep(for: .milliseconds(100))
        }
    }
}

public enum UpdateHelperProcess {
    /// Recovery runs the app that started the update when it is still beside the stage, rather
    /// than the version that failed, but only once its signature meets the running app's signing rule:
    /// anything under the user's home could have put a program at that path.
    public static func executable(for paths: UpdateTransactionPaths, fallback: URL, running: URL = Bundle.main.bundleURL,
                                  trusted: (_ candidate: URL, _ running: URL) -> Bool = CodeSigning.meetsRule) -> URL {
        let previous = paths.previous.appendingPathComponent("Contents/MacOS/RoleBandLauncher")
        guard FileManager.default.isExecutableFile(atPath: previous.path), trusted(paths.previous, running) else { return fallback }
        return previous
    }

    /// Starts the helper in its own session, so quitting the app neither signals nor waits for it.
    /// Its environment is built here and never carries the engine's owner marker.
    public static func spawn(executable: URL, recovering: Bool, id: UUID, home: URL) throws {
        let log = HomeLayout(home).data.appendingPathComponent("logs/update-helper.log")
        try FileManager.default.createDirectory(at: log.deletingLastPathComponent(), withIntermediateDirectories: true,
                                                attributes: [.posixPermissions: 0o700])
        var attributes: posix_spawnattr_t?
        var actions: posix_spawn_file_actions_t?
        posix_spawnattr_init(&attributes)
        posix_spawn_file_actions_init(&actions)
        defer {
            posix_spawnattr_destroy(&attributes)
            posix_spawn_file_actions_destroy(&actions)
        }
        posix_spawnattr_setflags(&attributes, Int16(POSIX_SPAWN_SETSID | POSIX_SPAWN_SETSIGMASK | POSIX_SPAWN_SETSIGDEF | POSIX_SPAWN_CLOEXEC_DEFAULT))
        var mask = sigset_t(0)
        var defaults = sigset_t(0)
        sigemptyset(&mask)
        sigemptyset(&defaults)
        for number in [SIGTERM, SIGINT, SIGHUP, SIGPIPE] { sigaddset(&defaults, number) }
        posix_spawnattr_setsigmask(&attributes, &mask)
        posix_spawnattr_setsigdefault(&attributes, &defaults)
        posix_spawn_file_actions_addopen(&actions, STDIN_FILENO, "/dev/null", O_RDONLY, 0)
        posix_spawn_file_actions_addopen(&actions, STDOUT_FILENO, log.path, O_WRONLY | O_CREAT | O_APPEND, 0o600)
        posix_spawn_file_actions_adddup2(&actions, STDOUT_FILENO, STDERR_FILENO)
        posix_spawn_file_actions_addchdir_np(&actions, "/")
        let mode = recovering ? "--recover-update" : "--apply-update"
        let arguments: [String] = [executable.path, mode, id.uuidString]
        let environment: [String] = ["HOME=" + home.path, "PATH=/usr/bin:/bin:/usr/sbin:/sbin", "LANG=en_US.UTF-8"]
        let argv: [UnsafeMutablePointer<CChar>?] = arguments.map { strdup($0) }
        let env: [UnsafeMutablePointer<CChar>?] = environment.map { strdup($0) }
        defer { (argv + env).forEach { free($0) } }
        var argvPointers = argv + [nil]
        var envPointers = env + [nil]
        var launched: pid_t = 0
        let code = posix_spawn(&launched, executable.path, &actions, &attributes, &argvPointers, &envPointers)
        guard code == 0 else { throw POSIXError(POSIXErrorCode(rawValue: code) ?? .EIO) }
    }
}

enum PrivateFiles {
    static func directory(_ path: URL) throws {
        try FileManager.default.createDirectory(at: path, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        try requireDirectory(path)
    }

    static func requireDirectory(_ path: URL) throws {
        guard let info = try? FileManager.default.attributesOfItem(atPath: path.path),
              info[.type] as? FileAttributeType == .typeDirectory,
              (info[.ownerAccountID] as? NSNumber)?.uint32Value == getuid(),
              (info[.posixPermissions] as? NSNumber)?.intValue == 0o700 else { throw UpdateHelperProblem.invalidPlan }
    }

    static func write(_ data: Data, to file: URL) throws {
        let folder = file.deletingLastPathComponent()
        let temporary = folder.appendingPathComponent(".\(file.lastPathComponent)-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: temporary) }
        guard FileManager.default.createFile(atPath: temporary.path, contents: data, attributes: [.posixPermissions: 0o600]) else {
            throw UpdateHelperProblem.invalidPlan
        }
        let handle = try FileHandle(forWritingTo: temporary)
        try handle.synchronize(); try handle.close()
        guard rename(temporary.path, file.path) == 0 else { throw UpdateHelperProblem.invalidPlan }
        let directory = open(folder.path, O_RDONLY | O_CLOEXEC)
        guard directory >= 0 else { throw UpdateHelperProblem.invalidPlan }
        defer { close(directory) }
        guard fsync(directory) == 0 else { throw UpdateHelperProblem.invalidPlan }
    }

    static func read(_ file: URL, limit: Int) throws -> Data {
        let fd = open(file.path, O_RDONLY | O_NOFOLLOW | O_CLOEXEC | O_NONBLOCK)
        guard fd >= 0 else { throw UpdateHelperProblem.invalidPlan }
        let handle = FileHandle(fileDescriptor: fd, closeOnDealloc: true)
        defer { try? handle.close() }
        var info = stat()
        guard fstat(fd, &info) == 0, info.st_mode & S_IFMT == S_IFREG, info.st_uid == getuid(),
              info.st_mode & 0o777 == 0o600, info.st_size <= limit,
              let data = try handle.read(upToCount: limit + 1), data.count <= limit else { throw UpdateHelperProblem.invalidPlan }
        return data
    }
}
