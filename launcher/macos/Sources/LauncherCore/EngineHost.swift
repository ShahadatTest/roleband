import Darwin
import Foundation

public enum HostProblem: Error, Equatable, Sendable {
    case sourceInstallation, databaseOwnedElsewhere, alreadyOwned, invalidConfiguration, processInspection, stopFailed
}

public enum HostState: Equatable, Sendable {
    case stopped, starting, running
    case backingOff(until: TimeInterval)
    case needsAttention
}

public struct HostConfiguration: Sendable {
    public let resources: URL
    public let home: URL
    public let installation: Installation
    public let port: Int
    var data: URL { HomeLayout(home).data }
    var pgdata: URL { HomeLayout(home).database }
    var record: URL { data.appendingPathComponent("launcher/owned-engine.json") }
    var python: URL { resources.appendingPathComponent("python/bin/python3.12") }
    var bootstrap: URL { resources.appendingPathComponent("engine/packaged.py") }
    var log: URL { data.appendingPathComponent("logs/owned-engine.log") }

    public init(resources: URL, home: URL, installation: Installation) throws {
        let target = try installation.target()
        guard target.url.host == "127.0.0.1", let port = target.url.port, (1...65535).contains(port),
              resources.lastPathComponent == "Resources",
              resources.deletingLastPathComponent().lastPathComponent == "Contents" else {
            throw HostProblem.invalidConfiguration
        }
        self.resources = resources
        self.home = home
        self.installation = installation
        self.port = port
    }

    func environment(token: String) -> [String: String] {
        ["HOME": home.path, "PATH": "\(resources.appendingPathComponent("python/bin").path):/usr/bin:/bin:/usr/sbin:/sbin",
         "LANG": "en_US.UTF-8", "ROLEBAND_PACKAGED": "1", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1", "PYTHONUNBUFFERED": "1",
         "ROLEBAND_DATABASE_URL": "", "ROLEBAND_DB_EMBEDDED": "true", "ROLEBAND_PGDATA": pgdata.path,
         "ROLEBAND_API_HOST": "127.0.0.1", "ROLEBAND_API_PORT": String(port), OwnedProcess.marker: token]
    }
}

/// Owns only a packaged engine. The caller supplies the verified status identity and decides
/// when to start; polling and crash recovery continue until `stop()` completes.
public actor EngineHost {
    public private(set) var state: HostState = .stopped
    public private(set) var lastFailure: String?
    public private(set) var preparation: EnginePreparation?
    private let configuration: HostConfiguration
    private let now: @Sendable () -> TimeInterval
    private let readHealth: @Sendable (Installation) async throws -> EngineHealth
    private let automatic: Bool
    private let grace: TimeInterval
    private var monitor: Task<Void, Never>?
    private var operation: Task<Void, Error>?
    private var child: OwnedChild?
    private var token: String?
    private var lock: Int32 = -1
    private var startedAt: TimeInterval = 0
    private var failures = 0
    private var restarts: [TimeInterval] = []

    deinit {
        monitor?.cancel()
        if lock >= 0 { close(lock) }
    }

    public init(configuration: HostConfiguration) {
        self.init(configuration: configuration, now: { ProcessInfo.processInfo.systemUptime }, readHealth: EngineHealthClient.read)
    }

    init(configuration: HostConfiguration, now: @escaping @Sendable () -> TimeInterval,
         readStatus: @escaping @Sendable (Installation) async throws -> VerifiedStatus,
         automatic: Bool = true, stopGrace: TimeInterval = 10) {
        self.init(configuration: configuration, now: now, readHealth: {
            _ = try await readStatus($0)
            return EngineHealth()
        }, automatic: automatic, stopGrace: stopGrace)
    }

    init(configuration: HostConfiguration, now: @escaping @Sendable () -> TimeInterval,
         readHealth: @escaping @Sendable (Installation) async throws -> EngineHealth,
         automatic: Bool = true, stopGrace: TimeInterval = 10) {
        self.configuration = configuration
        self.now = now
        self.readHealth = readHealth
        self.automatic = automatic
        self.grace = stopGrace
    }

    public func start() async throws {
        try await serial { try await self.begin() }
    }

    public func stop() async throws {
        monitor?.cancel()
        monitor = nil
        try await serial {
            await self.endMonitoring()
            do {
                try await self.cleanUp()
                await self.didStop()
            } catch {
                await self.attention(error)
                throw error
            }
        }
    }

    public func restart() async throws {
        try await stop()
        try await start()
    }

    /// Stops what an earlier owner of this database left running and releases ownership,
    /// starting nothing. A live owner keeps its lock, so this refuses rather than races it.
    public func reclaim() async throws {
        try await serial {
            do {
                try await self.claim()
                try await self.cleanUp()
                await self.didStop()
            } catch {
                await self.release()
                throw error
            }
        }
    }

    /// Bounded tails stay available after a crash loop, without loading whole logs.
    public func diagnosticLines() -> String {
        ["owned-engine", "supervisor", "api"].compactMap { name -> String? in
            let url = configuration.data.appendingPathComponent("logs/\(name).log")
            guard let file = try? FileHandle(forReadingFrom: url) else { return nil }
            defer { try? file.close() }
            guard let size = try? file.seekToEnd() else { return nil }
            try? file.seek(toOffset: size > 16384 ? size - 16384 : 0)
            guard let bytes = try? file.read(upToCount: 16384) else { return nil }
            return "\(name):\n" + String(decoding: bytes, as: UTF8.self).split(separator: "\n").suffix(40).joined(separator: "\n")
        }.joined(separator: "\n")
    }

    private func serial(_ body: @escaping @Sendable () async throws -> Void) async throws {
        let previous = operation
        let next = Task {
            _ = try? await previous?.value
            try await body()
        }
        operation = next
        try await next.value
    }

    private func begin() async throws {
        guard state == .stopped || state == .needsAttention else { return }
        do {
            try claim()
            try await cleanUp()
            restarts = []
            lastFailure = nil
            try launch()
            if automatic {
                monitor?.cancel()
                monitor = Task { [weak self] in
                    while !Task.isCancelled {
                        do { try await Task.sleep(for: .seconds(3)) } catch { return }
                        guard !Task.isCancelled else { return }
                        try? await self?.check()
                    }
                }
            }
        } catch {
            attention(error)
            throw error
        }
    }

    private func ownedMode(_ app: URL) throws -> LaunchMode {
        let mode = LaunchMode.decide(bundle: app, home: configuration.home)
        if mode == .databaseOwnedElsewhere { throw HostProblem.databaseOwnedElsewhere }
        return mode
    }

    private func claim() throws {
        let app = configuration.resources.deletingLastPathComponent().deletingLastPathComponent()
        guard case .owned = try ownedMode(app) else { throw HostProblem.sourceInstallation }
        if lock >= 0 { return }
        let directory = configuration.record.deletingLastPathComponent()
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        let fd = open(directory.appendingPathComponent("owned-engine.lock").path, O_CREAT | O_RDWR | O_CLOEXEC | O_NOFOLLOW, 0o600)
        guard fd >= 0 else { throw HostProblem.alreadyOwned }
        guard flock(fd, LOCK_EX | LOCK_NB) == 0 else { close(fd); throw HostProblem.alreadyOwned }
        lock = fd
        var accepted = false
        defer { if !accepted { close(fd); lock = -1 } }
        if FileManager.default.fileExists(atPath: configuration.record.path) {
            let attributes = try FileManager.default.attributesOfItem(atPath: configuration.record.path)
            guard attributes[.type] as? FileAttributeType == .typeRegular,
                  (attributes[.ownerAccountID] as? NSNumber)?.uint32Value == getuid(),
                  let mode = attributes[.posixPermissions] as? NSNumber, mode.intValue & 0o077 == 0,
                  ((attributes[.size] as? NSNumber)?.intValue ?? Int.max) < 8192,
                  let raw = try JSONSerialization.jsonObject(with: Data(contentsOf: configuration.record)) as? [String: String],
                  let saved = raw["token"], UUID(uuidString: saved) != nil else { throw HostProblem.processInspection }
            token = saved
        }
        accepted = true
    }

    private func launch() throws {
        // Recheck discovery after cleanup: a source install may have appeared while it waited.
        let app = configuration.resources.deletingLastPathComponent().deletingLastPathComponent()
        guard case .owned(leftover: nil) = try ownedMode(app) else { throw HostProblem.sourceInstallation }
        try FileManager.default.createDirectory(at: configuration.log.deletingLastPathComponent(), withIntermediateDirectories: true,
                                               attributes: [.posixPermissions: 0o700])
        if let size = try? FileManager.default.attributesOfItem(atPath: configuration.log.path)[.size] as? NSNumber, size.intValue > 10_000_000 {
            let rotated = configuration.log.appendingPathExtension("1")
            try? FileManager.default.removeItem(at: rotated)
            try FileManager.default.moveItem(at: configuration.log, to: rotated)
        }
        let made = UUID().uuidString
        // Persist before spawning, so even a crash between spawn and return is recoverable.
        let partial = configuration.record.deletingLastPathComponent().appendingPathComponent(".engine-\(made)")
        defer { try? FileManager.default.removeItem(at: partial) }
        guard FileManager.default.createFile(atPath: partial.path, contents: try JSONSerialization.data(withJSONObject: ["token": made]),
                                            attributes: [.posixPermissions: 0o600]),
              rename(partial.path, configuration.record.path) == 0 else { throw HostProblem.invalidConfiguration }
        token = made
        child = try OwnedChild(executable: configuration.python,
                               arguments: ["-I", configuration.bootstrap.path, "supervisor", "run"],
                               environment: configuration.environment(token: made), log: configuration.log,
                               directory: configuration.bootstrap.deletingLastPathComponent())
        startedAt = now()
        preparation = nil
        failures = 0
        state = .starting
    }

    func check() async throws {
        try await serial { try await self.look() }
    }

    private func look() async throws {
        switch state {
        case .backingOff(let until):
            guard now() >= until else { return }
            restarts.removeAll { now() - $0 >= 600 }
            guard restarts.count < 3 else { state = .needsAttention; return }
            restarts.append(now())
            do { try launch() } catch { try await failed(String(describing: error)) }
        case .starting, .running:
            guard child?.running() == true else { try await failed("engine_exited"); return }
            do {
                let health = try await readHealth(configuration.installation)
                preparation = health.preparation
                failures = 0
                if health.failed {
                    lastFailure = "preparation_failed"
                    state = .needsAttention
                } else if health.ready { state = .running }
                else {
                    // A correctly identified child answers while initial migrations run.
                    state = .starting
                    startedAt = now()
                }
            } catch {
                failures += 1
                if (state == .starting && now() - startedAt >= 60) || (state == .running && failures >= 3) {
                    try await failed("engine_unhealthy")
                }
            }
        case .stopped, .needsAttention: return
        }
    }

    private func failed(_ reason: String) async throws {
        lastFailure = reason
        do { try await cleanUp() } catch { attention(error); throw error }
        restarts.removeAll { now() - $0 >= 600 }
        state = restarts.count >= 3 ? .needsAttention : .backingOff(until: now() + pow(2, Double(restarts.count)))
    }

    private func cleanUp() async throws {
        guard lock >= 0 else { return }
        if let token {
            // Jobs and pg_ctl create new sessions. The inherited marker finds those groups
            // even when their original supervisor has died and their parent is now launchd.
            let deadline = ProcessInfo.processInfo.systemUptime + grace
            var emptyLooks = 0
            var terminated = Set<pid_t>()
            while true {
                let running = child?.running() == true
                var services = try OwnedProcess.marked(token).filter { !$0.isPostgres }
                // The child is ours even during exec, when the kernel can briefly withhold argv.
                if running, let process = child?.identity, process.isAlive, !services.contains(process) { services.append(process) }
                emptyLooks = services.isEmpty && !running ? emptyLooks + 1 : 0
                if emptyLooks >= 2 { break }
                let number = ProcessInfo.processInfo.systemUptime < deadline ? SIGTERM : SIGKILL
                for process in services where number == SIGKILL || terminated.insert(process.group).inserted {
                    try process.signal(number, group: true)
                }
                if ProcessInfo.processInfo.systemUptime > deadline + 2 { throw HostProblem.stopFailed }
                try await Task.sleep(for: .milliseconds(25))
            }
        }
        // PostgreSQL's fast shutdown is SIGINT; SIGTERM is smart shutdown and can wait
        // indefinitely for clients. Its separate session is stopped only after the clients.
        if let pid = LaunchMode.runningServer(configuration.pgdata), let server = OwnedProcess.read(pid), server.isPostgres {
            guard let path = LaunchMode.executable(pid), LaunchMode.isInsideApp(path) else {
                throw HostProblem.sourceInstallation
            }
            guard server.matchesDatabase(configuration.pgdata) else { throw HostProblem.processInspection }
            try server.signal(SIGINT)
            let deadline = ProcessInfo.processInfo.systemUptime + grace
            while server.isAlive {
                if ProcessInfo.processInfo.systemUptime >= deadline { try server.signal(SIGKILL) }
                if ProcessInfo.processInfo.systemUptime > deadline + 2 { throw HostProblem.stopFailed }
                try await Task.sleep(for: .milliseconds(25))
            }
        }
        if let token, !(try OwnedProcess.marked(token)).isEmpty { throw HostProblem.stopFailed }
        _ = child?.running()
        child = nil
        if token != nil { try FileManager.default.removeItem(at: configuration.record) }
        token = nil
    }

    private func didStop() {
        state = .stopped
        release()
    }

    private func release() {
        if lock >= 0 { close(lock); lock = -1 }
    }

    private func endMonitoring() {
        monitor?.cancel()
        monitor = nil
    }

    private func attention(_ error: any Error) {
        lastFailure = String(describing: error)
        state = .needsAttention
    }
}
