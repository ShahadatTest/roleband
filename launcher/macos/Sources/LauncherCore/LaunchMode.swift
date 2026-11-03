import Darwin
import Foundation

/// Where RoleBand keeps its state in a home folder. Source installs and the app share it.
public struct HomeLayout: Sendable {
    public let home: URL
    public init(_ home: URL) { self.home = home }
    public var data: URL { home.appendingPathComponent(".roleband") }
    public var database: URL { data.appendingPathComponent("db") }
    public var registration: URL { data.appendingPathComponent("launcher/installation.json") }
    public var launchAgent: URL { home.appendingPathComponent("Library/LaunchAgents/com.roleband.plist") }
}

/// What the app may do with an engine on this Mac.
public enum LaunchMode: Equatable, Sendable {
    /// Translocated, on a disk image or outside Applications: no engine starts and nothing registers.
    case moveToApplications
    /// A source install lives here and owns the database; the app shows its status and controls only.
    case attach
    /// A database the app did not make, from a source install whose registration and item are gone.
    /// The app starts nothing and never opens, migrates or restores it.
    case databaseOwnedElsewhere
    /// The app starts and supervises its own engine. `leftover` is a database server that an
    /// earlier run of the app left behind, to stop before starting again.
    case owned(leftover: pid_t?)

    public static let bundleIdentifier = "com.roleband.launcher"

    public static func decide(bundle: URL, home: URL,
                              executable: (pid_t) -> URL? = Self.executable) -> Self {
        guard AppLocation.isInstalled(bundle, home: home) else { return .moveToApplications }
        // Either file means a source install, running or stopped. Its database is never the
        // app's to start or migrate, so an entry that cannot be read still counts.
        let layout = HomeLayout(home)
        for evidence in [layout.registration, layout.launchAgent]
        where (try? FileManager.default.attributesOfItem(atPath: evidence.path)) != nil {
            return .attach
        }
        let pgdata = layout.database
        var leftover: pid_t?
        // pg_ctl starts the server in its own session, so its executable, not its process group,
        // says who started it: the app's bundled runtime, or a checkout's virtualenv.
        if let pid = runningServer(pgdata), let path = executable(pid), path.lastPathComponent == "postgres" {
            guard isInsideApp(path) else { return .attach }
            leftover = pid
        }
        guard madeByApp(pgdata) else { return .databaseOwnedElsewhere }
        return .owned(leftover: leftover)
    }

    /// True when no cluster exists yet or the engine recorded the app as its maker. The engine
    /// writes `db.owner.json` beside the cluster before creating it; a source install writes none.
    static func madeByApp(_ pgdata: URL) -> Bool {
        let record = pgdata.deletingLastPathComponent().appendingPathComponent("\(pgdata.lastPathComponent).owner.json")
        guard let data = try? Data(contentsOf: record) else {
            return !FileManager.default.fileExists(atPath: record.path)
                && !FileManager.default.fileExists(atPath: pgdata.appendingPathComponent("PG_VERSION").path)
        }
        return (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["owner"] as? String == "app"
    }

    static func runningServer(_ pgdata: URL) -> pid_t? {
        guard let handle = try? FileHandle(forReadingFrom: pgdata.appendingPathComponent("postmaster.pid")) else { return nil }
        defer { try? handle.close() }
        guard let data = try? handle.read(upToCount: 4096),
              let first = String(data: data, encoding: .utf8)?.split(separator: "\n").first,
              let pid = pid_t(first.trimmingCharacters(in: .whitespaces)), pid > 0 else { return nil }
        return kill(pid, 0) == 0 || errno == EPERM ? pid : nil
    }

    static func isInsideApp(_ path: URL) -> Bool {
        var folder = path.deletingLastPathComponent()
        while folder.pathComponents.count > 1 {
            if folder.pathExtension == "app" {
                let info = folder.appendingPathComponent("Contents/Info.plist")
                guard let data = try? Data(contentsOf: info),
                      let plist = try? PropertyListSerialization.propertyList(from: data, format: nil) as? [String: Any] else { return false }
                return plist["CFBundleIdentifier"] as? String == bundleIdentifier
            }
            folder = folder.deletingLastPathComponent()
        }
        return false
    }

    public static func executable(_ pid: pid_t) -> URL? {
        var buffer = [CChar](repeating: 0, count: 4 * Int(MAXPATHLEN))
        guard proc_pidpath(pid, &buffer, UInt32(buffer.count)) > 0 else { return nil }
        return URL(fileURLWithPath: String(decoding: buffer.prefix { $0 != 0 }.map(UInt8.init(bitPattern:)), as: UTF8.self))
    }
}
