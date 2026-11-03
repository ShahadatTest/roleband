import CryptoKit
import Darwin
import Foundation

public enum InstallProblem: Error, Sendable {
    case unsafePath, foreignDatabase, engineRunning, incompatibleVersion, invalidJournal, damagedBackup, recoveryRequired,
         healthTimeout
}

public struct UpdateTransactionPaths: Sendable {
    public let installed: URL
    public let home: URL
    public let id: UUID
    public init(installed: URL, home: URL, id: UUID = UUID()) {
        self.installed = installed.deletingLastPathComponent().resolvingSymlinksInPath()
            .appendingPathComponent(installed.lastPathComponent).standardizedFileURL
        self.home = home.resolvingSymlinksInPath().standardizedFileURL; self.id = id
    }
    public var directory: URL { HomeLayout(home).data.appendingPathComponent("updates/" + id.uuidString) }
    public var journal: URL { directory.appendingPathComponent("transaction.json") }
    /// Written when a recovery helper gives up, so later opens show the update instead of retrying it unasked.
    var recoveryFailed: URL { directory.appendingPathComponent("recovery-failed") }
    public var backup: URL { HomeLayout(home).data.appendingPathComponent("backups/pre-update-" + id.uuidString) }
    var stage: URL { installed.deletingLastPathComponent().appendingPathComponent(".update-" + id.uuidString) }
    var next: URL { stage.appendingPathComponent("next.app") }
    var previous: URL { stage.appendingPathComponent("previous.app") }
    var failedApp: URL { stage.appendingPathComponent("failed.app") }
    var failedDatabase: URL { directory.appendingPathComponent("failed-db") }
}

public struct UpdateInstallOperations: Sendable {
    public var validate: @Sendable (URL, String) async throws -> Void
    public var stop: @Sendable () async throws -> Void
    public var launch: @Sendable (URL) async throws -> Void
    public var healthy: @Sendable (String) async throws -> Bool
    /// Whether that version's engine says it is still upgrading or creating its database.
    public var preparing: @Sendable (String) async -> Bool
    public var now: @Sendable () -> TimeInterval
    public var pause: @Sendable () async throws -> Void
    public init(validate: @escaping @Sendable (URL, String) async throws -> Void,
                stop: @escaping @Sendable () async throws -> Void,
                launch: @escaping @Sendable (URL) async throws -> Void,
                healthy: @escaping @Sendable (String) async throws -> Bool,
                preparing: @escaping @Sendable (String) async -> Bool = { _ in false },
                now: @escaping @Sendable () -> TimeInterval = { ProcessInfo.processInfo.systemUptime },
                pause: @escaping @Sendable () async throws -> Void = { try await Task.sleep(for: .seconds(1)) }) {
        self.validate = validate; self.stop = stop; self.launch = launch; self.healthy = healthy
        self.preparing = preparing; self.now = now; self.pause = pause
    }
}

public enum InstallPhase: String, Codable, Sendable {
    case staged, backingUp, backupReady, installing, oldAppMoved, checking, restoring, rolledBack, committed
    public var finished: Bool { self == .committed || self == .rolledBack }
}

public struct UpdateJournal: Equatable, Sendable {
    public let phase: InstallPhase
    public let installed: String
    public let from: String
    public let to: String
}

private struct InstallRecord: Codable {
    let format: Int
    let id: UUID
    let installed: String
    let home: String
    let from: String
    let to: String
    let createdAt: Date
    var phase: InstallPhase
    var hadDatabase = false
    var databaseDigest: String?
    var failure: String?
}

/// The file journal precedes destructive renames so recovery can infer an interrupted move.
public actor UpdateTransaction {
    private let paths: UpdateTransactionPaths
    private let operations: UpdateInstallOperations
    private var busy = false
    private let checkpoint: @Sendable (InstallPhase) throws -> Void
    /// How long a launched version has to answer healthy, counted from launch or from its latest
    /// report that it is still preparing its database.
    static let healthWait: TimeInterval = 120
    /// The engine gives up on preparing its database after 30 minutes and reports the failure; the
    /// helper waits that long and the usual wait beyond it, so the engine's own answer comes first.
    static let preparationCap: TimeInterval = 1800 + healthWait
    public init(paths: UpdateTransactionPaths, operations: UpdateInstallOperations) {
        self.paths = paths; self.operations = operations; checkpoint = { _ in }
    }
    init(paths: UpdateTransactionPaths, operations: UpdateInstallOperations,
         checkpoint: @escaping @Sendable (InstallPhase) throws -> Void) {
        self.paths = paths; self.operations = operations; self.checkpoint = checkpoint
    }

    public func install(candidate: URL, from: String, to: String) async throws -> InstallPhase {
        guard !busy else { throw InstallProblem.invalidJournal }
        busy = true; defer { busy = false }
        guard let old = ReleaseVersion(from), let new = ReleaseVersion(to), old < new else {
            throw InstallProblem.incompatibleVersion
        }
        try validatePaths()
        try assertOwnedAndStopped(requireStopped: false)
        try await operations.validate(paths.installed, from)
        try await operations.validate(candidate, to)
        try Task.checkCancellation()
        try privateDirectory(paths.directory)
        let descriptor = try acquireLock()
        defer { flock(descriptor, LOCK_UN); close(descriptor) }
        for sibling in try FileManager.default.contentsOfDirectory(at: paths.directory.deletingLastPathComponent(),
                                                                  includingPropertiesForKeys: nil)
        where sibling.lastPathComponent != paths.id.uuidString && UUID(uuidString: sibling.lastPathComponent) != nil {
            let journal = sibling.appendingPathComponent("transaction.json")
            if exists(journal) {
                let other = try JSONDecoder().decode(InstallRecord.self, from: Data(contentsOf: journal))
                guard other.phase == .committed || other.phase == .rolledBack else { throw InstallProblem.recoveryRequired }
            }
        }
        guard !exists(paths.journal), !exists(paths.stage), !exists(paths.backup) else { throw InstallProblem.invalidJournal }
        try privateDirectory(paths.stage)
        try FileManager.default.copyItem(at: candidate, to: paths.next)
        try await operations.validate(paths.next, to)
        var record = InstallRecord(format: 1, id: paths.id, installed: paths.installed.path, home: paths.home.path,
                                   from: from, to: to, createdAt: Date(), phase: .staged)
        try save(record)
        var lease: Int32 = -1
        defer { release(&lease) }
        do {
            try Task.checkCancellation()
            try await operations.stop()
            lease = try acquireEngineLease()
            try assertOwnedAndStopped()
            record.hadDatabase = exists(HomeLayout(paths.home).database)
            record.phase = .backingUp; try save(record)
            if record.hadDatabase {
                let database = HomeLayout(paths.home).database
                let original = try treeDigest(database)
                let partial = paths.backup.appendingPathExtension("partial")
                try privateDirectory(paths.backup.deletingLastPathComponent())
                guard !exists(partial) else { throw InstallProblem.invalidJournal }
                try FileManager.default.copyItem(at: database, to: partial)
                guard try treeDigest(partial) == original else { throw InstallProblem.damagedBackup }
                try FileManager.default.moveItem(at: partial, to: paths.backup)
                record.databaseDigest = original
            }
            record.phase = .backupReady; try save(record)
            try assertOwnedAndStopped()
            try await operations.validate(paths.next, to)
            record.phase = .installing; try save(record)
            try FileManager.default.moveItem(at: paths.installed, to: paths.previous)
            record.phase = .oldAppMoved; try save(record)
            try FileManager.default.moveItem(at: paths.next, to: paths.installed)
            record.phase = .checking; try save(record)
            release(&lease)
            let launched = operations.now()
            var deadline = launched + Self.healthWait
            try await operations.launch(paths.installed)
            while operations.now() < deadline {
                try Task.checkCancellation()
                if (try? await operations.healthy(to)) == true && operations.now() < deadline {
                    record.phase = .committed; try save(record)
                    try? pruneBackups()
                    return .committed
                }
                // An upgrade of a large database outlasts the usual wait; each report that it is still
                // running extends the wait, up to the cap.
                if await operations.preparing(to) {
                    deadline = max(deadline, min(operations.now() + Self.healthWait, launched + Self.preparationCap))
                }
                try await operations.pause()
            }
            throw InstallProblem.healthTimeout
        } catch {
            release(&lease)
            if var failed = try? load(), failed.phase != .committed {
                failed.failure = String(String(describing: error).prefix(1024))
                try save(failed, notify: false)
            }
            // Recovery runs independently of cancellation of the update request.
            return try await Task { try await self.restore() }.value
        }
    }

    public func recover() async throws -> InstallPhase {
        guard !busy else { throw InstallProblem.invalidJournal }
        busy = true; defer { busy = false }
        try validatePaths()
        let descriptor = try acquireLock()
        defer { flock(descriptor, LOCK_UN); close(descriptor) }
        return try await restore()
    }

    public func phase() throws -> InstallPhase { try load().phase }

    /// Nil when no journal was written yet; throws when one exists but fails the checks `load` applies.
    /// `anyLocation` accepts a journal written for the app at another path, for a caller that compares it.
    static func journal(_ paths: UpdateTransactionPaths, anyLocation: Bool = false) throws -> UpdateJournal? {
        guard (try? FileManager.default.attributesOfItem(atPath: paths.journal.path)) != nil else { return nil }
        let record = try read(paths, anyLocation: anyLocation)
        return UpdateJournal(phase: record.phase, installed: record.installed, from: record.from, to: record.to)
    }

    private func restore() async throws -> InstallPhase {
        var record = try load()
        if record.phase == .committed || record.phase == .rolledBack { return record.phase }
        try assertOwnedAndStopped(requireStopped: false)
        try await operations.stop()
        var lease = try acquireEngineLease()
        defer { release(&lease) }
        try assertOwnedAndStopped()
        let replaced = exists(paths.previous)
        if replaced {
            try await operations.validate(paths.previous, record.from)
            if record.hadDatabase {
                guard let digest = record.databaseDigest, try treeDigest(paths.backup) == digest else {
                    throw InstallProblem.damagedBackup
                }
            }
            record.phase = .restoring; try save(record)
            let database = HomeLayout(paths.home).database
            if record.hadDatabase {
                guard let digest = record.databaseDigest else { throw InstallProblem.damagedBackup }
                let needsRestore = exists(database) ? try treeDigest(database) != digest : true
                if needsRestore {
                    if exists(database) {
                        guard !exists(paths.failedDatabase) else { throw InstallProblem.recoveryRequired }
                        try FileManager.default.moveItem(at: database, to: paths.failedDatabase)
                    }
                    let temporary = paths.directory.appendingPathComponent("restore-db")
                    if exists(temporary) { try FileManager.default.removeItem(at: temporary) }
                    try FileManager.default.copyItem(at: paths.backup, to: temporary)
                    guard try treeDigest(temporary) == digest else { throw InstallProblem.damagedBackup }
                    try FileManager.default.moveItem(at: temporary, to: database)
                }
            } else if exists(database) {
                guard !exists(paths.failedDatabase) else { throw InstallProblem.recoveryRequired }
                try FileManager.default.moveItem(at: database, to: paths.failedDatabase)
            }
            if exists(paths.installed) {
                guard !exists(paths.failedApp) else { throw InstallProblem.recoveryRequired }
                try FileManager.default.moveItem(at: paths.installed, to: paths.failedApp)
            }
            try FileManager.default.moveItem(at: paths.previous, to: paths.installed)
        } else {
            // A crash after restoring the app can precede the journal update.
            try await operations.validate(paths.installed, record.from)
            if record.phase == .restoring, record.hadDatabase {
                guard let digest = record.databaseDigest,
                      try treeDigest(HomeLayout(paths.home).database) == digest else { throw InstallProblem.recoveryRequired }
            }
        }
        record.phase = .rolledBack; try save(record)
        release(&lease)
        try await operations.launch(paths.installed)
        return .rolledBack
    }

    private func validatePaths() throws {
        guard AppLocation.isInstalled(paths.installed, home: paths.home),
              paths.installed.path == paths.installed.resolvingSymlinksInPath().path,
              paths.home.path == paths.home.resolvingSymlinksInPath().path else { throw InstallProblem.unsafePath }
        for path in [HomeLayout(paths.home).data, paths.directory.deletingLastPathComponent(), paths.directory,
                     paths.stage, paths.backup.deletingLastPathComponent()] where exists(path) {
            let info = try FileManager.default.attributesOfItem(atPath: path.path)
            guard info[.type] as? FileAttributeType == .typeDirectory,
                  (info[.ownerAccountID] as? NSNumber)?.uint32Value == getuid() else { throw InstallProblem.unsafePath }
        }
    }

    private func assertOwnedAndStopped(requireStopped: Bool = true) throws {
        let layout = HomeLayout(paths.home)
        guard !exists(layout.registration), !exists(layout.launchAgent) else {
            throw InstallProblem.foreignDatabase
        }
        let marker = layout.data.appendingPathComponent("db.owner.json")
        if exists(layout.database) || exists(marker) {
            guard let info = try? FileManager.default.attributesOfItem(atPath: marker.path),
                  info[.type] as? FileAttributeType == .typeRegular,
                  (info[.ownerAccountID] as? NSNumber)?.uint32Value == getuid(),
                  (info[.size] as? NSNumber)?.intValue ?? Int.max <= 8192,
                  let data = try? Data(contentsOf: marker),
                  (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["owner"] as? String == "app" else {
                throw InstallProblem.foreignDatabase
            }
        }
        if exists(layout.database) {
            let info = try FileManager.default.attributesOfItem(atPath: layout.database.path)
            guard info[.type] as? FileAttributeType == .typeDirectory,
                  (info[.ownerAccountID] as? NSNumber)?.uint32Value == getuid() else { throw InstallProblem.foreignDatabase }
        }
        if requireStopped, exists(layout.database.appendingPathComponent("postmaster.pid")) {
            throw InstallProblem.engineRunning
        }
    }

    private func privateDirectory(_ path: URL) throws {
        try FileManager.default.createDirectory(at: path, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        let info = try FileManager.default.attributesOfItem(atPath: path.path)
        guard info[.type] as? FileAttributeType == .typeDirectory,
              (info[.ownerAccountID] as? NSNumber)?.uint32Value == getuid(),
              (info[.posixPermissions] as? NSNumber)?.intValue == 0o700 else { throw InstallProblem.unsafePath }
    }

    private func acquireLock() throws -> Int32 {
        try privateDirectory(paths.directory)
        let fd = open(paths.directory.deletingLastPathComponent().appendingPathComponent("install.lock").path,
                      O_CREAT | O_RDWR | O_NOFOLLOW | O_CLOEXEC, 0o600)
        guard fd >= 0 else { throw InstallProblem.invalidJournal }
        var info = stat()
        guard fstat(fd, &info) == 0, info.st_mode & S_IFMT == S_IFREG, info.st_uid == getuid(), info.st_mode & 0o077 == 0 else {
            close(fd); throw InstallProblem.invalidJournal
        }
        guard flock(fd, LOCK_EX | LOCK_NB) == 0 else { close(fd); throw InstallProblem.invalidJournal }
        return fd
    }

    private func acquireEngineLease() throws -> Int32 {
        let folder = HomeLayout(paths.home).data.appendingPathComponent("launcher")
        try privateDirectory(folder)
        let fd = open(folder.appendingPathComponent("owned-engine.lock").path, O_CREAT | O_RDWR | O_NOFOLLOW | O_CLOEXEC, 0o600)
        guard fd >= 0 else { throw InstallProblem.engineRunning }
        var info = stat()
        guard fstat(fd, &info) == 0, info.st_mode & S_IFMT == S_IFREG, info.st_uid == getuid(), info.st_mode & 0o077 == 0 else {
            close(fd); throw InstallProblem.engineRunning
        }
        guard flock(fd, LOCK_EX | LOCK_NB) == 0 else { close(fd); throw InstallProblem.engineRunning }
        return fd
    }

    private func release(_ descriptor: inout Int32) {
        if descriptor >= 0 { flock(descriptor, LOCK_UN); close(descriptor); descriptor = -1 }
    }

    private func exists(_ path: URL) -> Bool { (try? FileManager.default.attributesOfItem(atPath: path.path)) != nil }

    private func save(_ record: InstallRecord, notify: Bool = true) throws {
        let temporary = paths.directory.appendingPathComponent("journal-" + UUID().uuidString)
        guard FileManager.default.createFile(atPath: temporary.path, contents: try JSONEncoder().encode(record),
                                            attributes: [.posixPermissions: 0o600]) else { throw InstallProblem.invalidJournal }
        defer { try? FileManager.default.removeItem(at: temporary) }
        let file = try FileHandle(forWritingTo: temporary)
        try file.synchronize(); try file.close()
        guard rename(temporary.path, paths.journal.path) == 0 else { throw InstallProblem.invalidJournal }
        let directory = open(paths.directory.path, O_RDONLY | O_CLOEXEC)
        guard directory >= 0 else { throw InstallProblem.invalidJournal }
        defer { close(directory) }
        guard fsync(directory) == 0 else { throw InstallProblem.invalidJournal }
        if notify { try checkpoint(record.phase) }
    }

    private func load() throws -> InstallRecord { try Self.read(paths) }

    private static func read(_ paths: UpdateTransactionPaths, anyLocation: Bool = false) throws -> InstallRecord {
        let info = try FileManager.default.attributesOfItem(atPath: paths.journal.path)
        guard info[.type] as? FileAttributeType == .typeRegular,
              (info[.ownerAccountID] as? NSNumber)?.uint32Value == getuid(),
              (info[.posixPermissions] as? NSNumber)?.intValue == 0o600,
              (info[.size] as? NSNumber)?.intValue ?? Int.max <= 8192 else { throw InstallProblem.invalidJournal }
        let record = try JSONDecoder().decode(InstallRecord.self, from: Data(contentsOf: paths.journal))
        guard record.format == 1, record.id == paths.id, anyLocation || record.installed == paths.installed.path,
              record.home == paths.home.path,
              let old = ReleaseVersion(record.from), let new = ReleaseVersion(record.to), old < new else {
            throw InstallProblem.invalidJournal
        }
        return record
    }

    private func treeDigest(_ root: URL) throws -> String {
        guard (try FileManager.default.attributesOfItem(atPath: root.path))[.type] as? FileAttributeType == .typeDirectory else {
            throw InstallProblem.damagedBackup
        }
        let root = root.resolvingSymlinksInPath().standardizedFileURL
        let keys: [URLResourceKey] = [.isDirectoryKey, .isRegularFileKey, .isSymbolicLinkKey]
        let info = try root.resourceValues(forKeys: Set(keys))
        var failure: Error?
        guard info.isDirectory == true, info.isSymbolicLink != true,
              let iterator = FileManager.default.enumerator(at: root, includingPropertiesForKeys: keys, errorHandler: { _, error in
                  failure = error; return false
              }) else {
            throw InstallProblem.damagedBackup
        }
        var entries: [URL] = []
        for case let entry as URL in iterator { entries.append(entry) }
        if let failure { throw failure }
        var hash = SHA256()
        for entry in entries.sorted(by: { $0.path < $1.path }) {
            let values = try entry.resourceValues(forKeys: Set(keys))
            guard values.isSymbolicLink != true else { throw InstallProblem.damagedBackup }
            let canonical = entry.resolvingSymlinksInPath().standardizedFileURL.path
            guard canonical.hasPrefix(root.path + "/") else { throw InstallProblem.damagedBackup }
            let relative = String(canonical.dropFirst(root.path.count))
            let kind = values.isDirectory == true ? "directory:" : "file:"
            hash.update(data: Data((kind + String(relative.utf8.count) + ":" + relative).utf8))
            let attributes = try FileManager.default.attributesOfItem(atPath: entry.path)
            guard let mode = attributes[.posixPermissions] as? NSNumber else { throw InstallProblem.damagedBackup }
            hash.update(data: Data((":" + mode.stringValue + ":").utf8))
            if values.isDirectory == true { continue }
            guard values.isRegularFile == true else { throw InstallProblem.damagedBackup }
            let fd = open(entry.path, O_RDONLY | O_NOFOLLOW | O_CLOEXEC | O_NONBLOCK)
            guard fd >= 0 else { throw InstallProblem.damagedBackup }
            let file = FileHandle(fileDescriptor: fd, closeOnDealloc: true)
            defer { try? file.close() }
            var info = stat()
            guard fstat(fd, &info) == 0, info.st_mode & S_IFMT == S_IFREG else { throw InstallProblem.damagedBackup }
            var digest = SHA256()
            var count: Int64 = 0
            while let bytes = try file.read(upToCount: 1 << 20), !bytes.isEmpty {
                count += Int64(bytes.count)
                guard count <= info.st_size else { throw InstallProblem.damagedBackup }
                digest.update(data: bytes)
            }
            guard count == info.st_size else { throw InstallProblem.damagedBackup }
            hash.update(data: Data(digest.finalize()))
        }
        return hash.finalize().map { String(format: "%02x", $0) }.joined()
    }

    private func pruneBackups() throws {
        var verified: [(Date, URL)] = []
        let root = paths.directory.deletingLastPathComponent()
        for folder in try FileManager.default.contentsOfDirectory(at: root, includingPropertiesForKeys: nil) {
            guard let id = UUID(uuidString: folder.lastPathComponent) else { continue }
            let candidate = UpdateTransactionPaths(installed: paths.installed, home: paths.home, id: id)
            let file = candidate.journal
            guard let info = try? FileManager.default.attributesOfItem(atPath: file.path),
                  info[.type] as? FileAttributeType == .typeRegular,
                  (info[.ownerAccountID] as? NSNumber)?.uint32Value == getuid(),
                  (info[.size] as? NSNumber)?.intValue ?? Int.max <= 8192,
                  let data = try? Data(contentsOf: file), let record = try? JSONDecoder().decode(InstallRecord.self, from: data),
                  record.format == 1, record.id == id, record.home == paths.home.path,
                  record.installed == paths.installed.path, record.phase == .committed, record.hadDatabase,
                  let digest = record.databaseDigest, (try? treeDigest(candidate.backup)) == digest else { continue }
            verified.append((record.createdAt, candidate.backup))
        }
        // Only a newer pair of verified backups permits retiring an older managed copy.
        for (_, backup) in verified.sorted(by: { $0.0 > $1.0 }).dropFirst(2) {
            try FileManager.default.removeItem(at: backup)
        }
    }
}
