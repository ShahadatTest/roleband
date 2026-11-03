import Darwin
import Foundation

/// Why an update stopped before the helper took over. Every case leaves the running app and its
/// database as they were.
public enum UpdateFailure: Equatable, Sendable {
    case download
    /// The image or the app inside it was not the signed release; the download is discarded.
    case check
    /// A signed release whose app carries an Apple Developer ID this copy does not accept yet, as after
    /// a move to Developer ID. It can only be installed by hand from the release page.
    case signer
    case space(required: Int64)
    /// The verified update could not hand over to the helper.
    case restart

    /// `nil` for a cancellation, which is not a failure.
    public static func classify(_ error: any Error) -> UpdateFailure? {
        switch error {
        case is CancellationError: nil
        case DownloadProblem.insufficientSpace(let required): .space(required: required)
        case BundleInstallProblem.signer: .signer
        case is ArtifactProblem, is BundleInstallProblem, DownloadProblem.wrongSize: .check
        default: .download
        }
    }
}

/// What an update in progress shows, from the press of Update until the app quits for the helper.
public enum UpdateActivity: Equatable, Sendable {
    case downloading(received: Int64, total: Int64)
    /// Offline: the download resumes where it stopped once a connection returns.
    case paused(received: Int64, total: Int64)
    case verifying
    case restarting
    case failed(UpdateFailure)

    public var inProgress: Bool {
        switch self {
        case .downloading, .paused, .verifying: true
        default: false
        }
    }
}

/// The result of the last finished update, read from its journal on the first open afterwards.
public struct UpdateNotice: Equatable, Sendable {
    public enum Kind: Sendable { case updated, rolledBack }
    public let id: UUID
    public let kind: Kind
    public let from: String
    public let to: String
    public init(id: UUID, kind: Kind, from: String, to: String) {
        self.id = id
        self.kind = kind
        self.from = from
        self.to = to
    }

    /// A committed update that installed this version, or a rollback that returned to it. Journals of
    /// another app location or version say nothing about this one.
    public static func latest(installed: URL, home: URL, version: String) -> UpdateNotice? {
        let root = HomeLayout(home).data.appendingPathComponent("updates")
        guard let entries = try? FileManager.default.contentsOfDirectory(at: root, includingPropertiesForKeys: nil) else {
            return nil
        }
        var newest: (date: Date, notice: UpdateNotice)?
        for entry in entries {
            guard let id = UUID(uuidString: entry.lastPathComponent) else { continue }
            let paths = UpdateTransactionPaths(installed: installed, home: home, id: id)
            guard let journal = try? UpdateTransaction.journal(paths), journal.phase.finished,
                  let date = (try? paths.journal.resourceValues(forKeys: [.contentModificationDateKey]))?.contentModificationDate
            else { continue }
            let kind: Kind
            if journal.phase == .committed && journal.to == version { kind = .updated }
            else if journal.phase == .rolledBack && journal.from == version { kind = .rolledBack }
            else { continue }
            if newest.map({ date > $0.date }) ?? true {
                newest = (date, UpdateNotice(id: id, kind: kind, from: journal.from, to: journal.to))
            }
        }
        return newest?.notice
    }
}

public enum DiskUsage {
    /// Allocated bytes under a folder. The walk does not follow symbolic links, so files they point
    /// to are not counted. A missing folder uses none.
    public static func bytes(at folder: URL) throws -> Int64 {
        guard FileManager.default.fileExists(atPath: folder.path) else { return 0 }
        let keys: [URLResourceKey] = [.totalFileAllocatedSizeKey]
        guard let walk = FileManager.default.enumerator(at: folder, includingPropertiesForKeys: keys) else {
            throw CocoaError(.fileReadUnknown)
        }
        var total: Int64 = 0
        for case let file as URL in walk {
            total += Int64(try file.resourceValues(forKeys: Set(keys)).totalFileAllocatedSize ?? 0)
        }
        return total
    }

    /// Room an update needs beyond its download: the backup of the database made before replacing
    /// the app, and the staged copy of the new app, which is about the size of the installed one.
    public static func updateReserve(installed: URL, home: URL) throws -> Int64 {
        try bytes(at: HomeLayout(home).database) + bytes(at: installed)
    }
}

public extension UpdatePlan {
    /// Removes update folders that were prepared but never handed to a helper: the app quit while it
    /// waited for a scan, or the spawn failed. Only a folder holding nothing but a plan and a staged
    /// candidate goes, with no journal and no helper, untouched for the given time.
    static func discardAbandoned(home: URL, olderThan age: TimeInterval = 600, now: Date = Date()) {
        let manager = FileManager.default
        let root = HomeLayout(home).data.appendingPathComponent("updates")
        guard let entries = try? manager.contentsOfDirectory(at: root, includingPropertiesForKeys: nil) else { return }
        for entry in entries {
            guard UUID(uuidString: entry.lastPathComponent) != nil,
                  let contents = try? manager.contentsOfDirectory(atPath: entry.path),
                  Set(contents).isSubset(of: ["plan.json", "candidate", "helper.lock"]),
                  !HelperLease.held(entry),
                  let modified = (try? entry.resourceValues(forKeys: [.contentModificationDateKey]))?.contentModificationDate,
                  now.timeIntervalSince(modified) >= age else { continue }
            try? manager.removeItem(at: entry)
        }
    }
}
