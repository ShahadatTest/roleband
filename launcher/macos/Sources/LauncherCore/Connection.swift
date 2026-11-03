import Foundation
import Darwin
import LauncherChecksCore

public enum ConnectionProblem: Error, Equatable, Sendable {
    case missingInstallation, invalidInstallation, upgradeRequired, identityMismatch, invalidResponse, unavailable
}

/// Where the app learns which engine it talks to. Each exchange reads it before and after, so a
/// replaced engine never receives a request meant for the one it replaced.
public struct InstallationSource: Sendable {
    public let current: @Sendable () throws -> Installation
    public init(current: @escaping @Sendable () throws -> Installation) { self.current = current }
    /// A source install, found through the registration file it writes.
    public static func registration(_ url: URL) -> Self { Self { try Installation.load(url) } }
    /// The app's own engine, whose identity follows from its bundle and never changes while it runs.
    public static func fixed(_ installation: Installation) -> Self { Self { installation } }
    public func confirm(_ installation: Installation) throws {
        guard try current() == installation else { throw ConnectionProblem.identityMismatch }
    }
}

public struct Installation: Codable, Equatable, Sendable {
    public let product: String
    public let instance: String
    public let apiOrigin: String
    public let version: String
    public let format: Int
    enum CodingKeys: String, CodingKey { case product, instance, version, format; case apiOrigin = "api_origin" }

    public func target() throws -> ProbeTarget {
        guard product == "roleband", format == 1,
              instance.count == 24, instance.allSatisfy({ "0123456789abcdef".contains($0) }),
              let parts = URLComponents(string: apiOrigin), parts.path.isEmpty,
              let url = URL(string: apiOrigin + "/api/status") else { throw ConnectionProblem.invalidInstallation }
        do { return try ProbeTarget(url.absoluteString) }
        catch { throw ConnectionProblem.invalidInstallation }
    }

    public static func load(_ url: URL) throws -> Installation {
        let manager = FileManager.default
        guard manager.fileExists(atPath: url.path) else { throw ConnectionProblem.missingInstallation }
        do {
            let attributes = try manager.attributesOfItem(atPath: url.path)
            guard attributes[.type] as? FileAttributeType == .typeRegular,
                  (attributes[.ownerAccountID] as? NSNumber)?.uint32Value == getuid(),
                  let mode = attributes[.posixPermissions] as? NSNumber, mode.intValue & 0o077 == 0,
                  ((attributes[.size] as? NSNumber)?.intValue ?? Int.max) <= 8192 else {
                throw ConnectionProblem.invalidInstallation
            }
            let handle = try FileHandle(forReadingFrom: url)
            defer { try? handle.close() }
            let data = try handle.read(upToCount: 8193) ?? Data()
            guard data.count <= 8192 else { throw ConnectionProblem.invalidInstallation }
            let result = try JSONDecoder().decode(Self.self, from: data)
            _ = try result.target()
            return result
        } catch let problem as ConnectionProblem { throw problem }
        catch { throw ConnectionProblem.invalidInstallation }
    }
}

public struct Presentation: Codable, Equatable, Sendable {
    /// A newer engine may send a value this build does not know; it decodes as `unknown`
    /// instead of failing the whole reply, so the panel keeps showing the rest.
    public enum Activity: String, Codable, Sendable {
        case idle, scanning, updating, unknown
        public init(from decoder: Decoder) throws {
            self = Self(rawValue: try decoder.singleValueContainer().decode(String.self)) ?? .unknown
        }
    }
    public struct Hold: Codable, Equatable, Sendable {
        public enum Kind: String, Codable, Sendable {
            case attention, waiting, unknown
            public init(from decoder: Decoder) throws {
                self = Self(rawValue: try decoder.singleValueContainer().decode(String.self)) ?? .unknown
            }
        }
        public let kind: Kind
        public let reason: String
    }
    // Diagnostics the app never reads: optional, so an engine that drops them still reads.
    public let observedAt: String?
    public let activity: Activity
    public let activitySince: String?
    public let hold: Hold?
    public let queued: String?
    public let coverageAt: String?
    public let lastScanAt: String?
    public let lastScanOutcome: String?
    public let model: String?
    enum CodingKeys: String, CodingKey {
        case activity, hold, queued, model
        case observedAt = "observed_at", activitySince = "activity_since", coverageAt = "coverage_at"
        case lastScanAt = "last_scan_at", lastScanOutcome = "last_scan_outcome"
    }
    public var isActive: Bool { activity == .scanning || activity == .updating }
    public var titleKey: String {
        if activity == .scanning { return "scanning" }
        if activity == .updating { return "updating" }
        if let hold { return hold.kind == .attention ? "needs-attention" : "waiting" }
        return queued == "scan" ? "queued" : "ready"
    }
    public var symbol: String {
        if hold?.kind == .attention { return "exclamationmark.circle" }
        if isActive { return "arrow.triangle.2.circlepath" }
        if hold != nil || queued != nil { return "pause.circle" }
        return "checkmark.circle"
    }
    public var reasonKey: String? {
        guard let reason = hold?.reason else { return nil }
        switch reason {
        case "supervisor_absent", "supervisor_stale": return "reason-supervisor"
        case "schema_pending", "dependencies_pending": return "reason-setup"
        case "build_failed": return "reason-build"
        case "preflight_failed": return "reason-checks"
        case "model_missing": return "reason-model"
        case "model_preparing": return "reason-preparing"
        case "waiting_for_mains": return "reason-power"
        case "waiting_for_wake": return "reason-wake"
        case "preflight_running": return "reason-preflight"
        case "busy_external": return "reason-busy"
        case "maintenance": return "reason-maintenance"
        case "update_queued": return "reason-queued"
        case "provider_paused", "provider_backoff", "provider_policy_denied": return "reason-provider"
        default: return "reason-other"
        }
    }
}

/// The menu-bar scan picture. Live fields are present only while a scan executes; `last*`
/// describe the newest finished scan. An engine older than this field sends none, and one
/// older than `scheduling` sends the picture without it.
public struct ScanPicture: Decodable, Sendable, Equatable {
    public struct Company: Decodable, Sendable, Equatable {
        public let name: String
        public let since: String
    }
    /// Where a live scan is. Once every company is read the run still adds the last roles and
    /// then runs the passes after the scan, which can take longer than the reading did.
    public enum Stage: String, Sendable { case collecting, persisting, finishing }
    public let phase: String?
    public let percent: Int?
    public let companiesTotal: Int?
    public let inFlight: [Company]
    public let rolesPending: Int?
    public let rolesRecorded: Int?
    public let lastCompanies: Int?
    public let lastNewRoles: Int?
    public let lastPostings: Int?
    public let lastStopped: Bool
    public let nextScanAt: String?
    public let scheduling: String?
    public let pausedUntil: String?
    enum CodingKeys: String, CodingKey {
        case phase, percent
        case companiesTotal = "companies_total", inFlight = "in_flight", rolesPending = "roles_pending"
        case rolesRecorded = "roles_recorded", lastCompanies = "last_companies", lastNewRoles = "last_new_roles"
        case lastPostings = "last_postings", lastStopped = "last_stopped", nextScanAt = "next_scan_at"
        case scheduling, pausedUntil = "paused_until"
    }
    /// A live scan reported its companies; before its first heartbeat the picture has none.
    public var live: Bool { percent != nil }
    /// The engine's stage, or nil from an engine older than the field or one this app cannot read.
    public var stage: Stage? { phase.flatMap(Stage.init(rawValue:)) }
    /// Every company is read; the scan is adding the last roles or running the passes after it.
    public var everyCompanyRead: Bool { stage == .persisting || stage == .finishing }

    /// How scans start on their own, or nil when the engine does not say in a way this app reads,
    /// and the schedule must be read instead.
    public var schedule: ScheduleState? {
        guard let scheduling, ["plan", "timers", "off"].contains(scheduling) else { return nil }
        let until = pausedUntil.map(Stamp.date)
        if case .some(.none) = until { return nil }
        return ScheduleState(enabled: scheduling != "off", pausable: scheduling == "plan", pausedUntil: until ?? nil)
    }

    /// When the next scan starts, while that is still after `now`; a time already reached is due.
    public func nextScan(after now: Date) -> Date? {
        guard let next = Stamp.date(nextScanAt), next > now else { return nil }
        return next
    }
}

public struct VerifiedStatus: Sendable {
    public let installation: Installation
    public let presentation: Presentation
    public let receivedAt: Date
    public let scanState: ScanState?
    public let engineVersion: String
    public let scan: ScanPicture?
    public var scanAction: ScanAction? { scanState?.action(for: presentation) }
}

private struct Reply: Decodable {
    let db: String
    let launcher: Launcher?
    let running: Bool?
    let manual_sync_running: Bool?
    let manual_queued: [String]?
    struct Launcher: Decodable {
        let product: String, instance: String, api_origin: String, version: String
        let format: Int
        let status: Presentation
        let scan: ScanPicture?
        enum CodingKeys: String, CodingKey { case product, instance, api_origin, version, format, status, scan }
        init(from decoder: any Decoder) throws {
            let values = try decoder.container(keyedBy: CodingKeys.self)
            product = try values.decode(String.self, forKey: .product)
            instance = try values.decode(String.self, forKey: .instance)
            api_origin = try values.decode(String.self, forKey: .api_origin)
            version = try values.decode(String.self, forKey: .version)
            format = try values.decode(Int.self, forKey: .format)
            status = try values.decode(Presentation.self, forKey: .status)
            // The picture is decoration: a block this app cannot read leaves the status usable.
            scan = try? values.decodeIfPresent(ScanPicture.self, forKey: .scan)
        }
    }
}

private final class NoRedirects: NSObject, URLSessionTaskDelegate, Sendable {
    func urlSession(_ session: URLSession, task: URLSessionTask,
                    willPerformHTTPRedirection response: HTTPURLResponse, newRequest request: URLRequest,
                    completionHandler: @escaping @Sendable (URLRequest?) -> Void) { completionHandler(nil) }
}

public enum StatusClient {
    public static func decode(_ data: Data, status: Int, installation: Installation) throws -> VerifiedStatus {
        _ = try installation.target()
        guard status == 200, data.count <= 4194304 else { throw ConnectionProblem.invalidResponse }
        guard let reply = try? JSONDecoder().decode(Reply.self, from: data), reply.db == "ok" else {
            throw ConnectionProblem.invalidResponse
        }
        guard let launcher = reply.launcher else { throw ConnectionProblem.upgradeRequired }
        guard launcher.product == installation.product, launcher.instance == installation.instance,
              launcher.format == installation.format, launcher.api_origin == installation.apiOrigin else {
            throw ConnectionProblem.identityMismatch
        }
        let scan = reply.running.flatMap { running in
            reply.manual_sync_running.flatMap { manual in
                reply.manual_queued.map { ScanState(running: running, manualRunning: manual, manualQueued: $0) }
            }
        }
        return VerifiedStatus(installation: installation, presentation: launcher.status, receivedAt: Date(), scanState: scan, engineVersion: launcher.version,
                              scan: launcher.scan)
    }
    public static func read(_ installation: Installation) async throws -> VerifiedStatus {
        let target = try installation.target()
        // The status carries the scheduler's per-company lists, so it reads with the schedule's budget.
        let data = try await LocalHTTP.read(URLRequest(url: target.url), limit: 4194304)
        return try decode(data, status: 200, installation: installation)
    }
}

enum LocalHTTP {
    /// One session per timeout class keeps the connection to the engine open between polls.
    private static let reads = session(request: 3, resource: 5)
    // A stop waits up to 5 s for the run to end, then writes its results, before it answers.
    private static let mutations = session(request: 20, resource: 20)

    private static func session(request: TimeInterval, resource: TimeInterval) -> URLSession {
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = request
        config.timeoutIntervalForResource = resource
        config.connectionProxyDictionary = [:]
        config.urlCache = nil
        config.httpCookieStorage = nil
        return URLSession(configuration: config, delegate: NoRedirects(), delegateQueue: nil)
    }

    static func read(_ request: URLRequest, mutation: Bool = false, limit: Int = 262144) async throws -> Data {
        try Task.checkCancellation()
        let (bytes, response) = try await (mutation ? mutations : reads).bytes(for: request)
        guard let response = response as? HTTPURLResponse, response.url == request.url else {
            throw ConnectionProblem.invalidResponse
        }
        if mutation && response.statusCode == 409 { throw ControlProblem.refused }
        guard response.statusCode == 200 else { throw ConnectionProblem.invalidResponse }
        var data = Data()
        for try await byte in bytes {
            try Task.checkCancellation()
            guard data.count < limit else { throw ConnectionProblem.invalidResponse }
            data.append(byte)
        }
        return data
    }
}

public enum BrowserRoute: Sendable {
    case radar, newRoles, settings, schedule
    public func url(for installation: Installation) throws -> URL {
        let root = try installation.target().pageURL
        switch self {
        case .radar: return root
        // The dashboard's door to the board on New; it drops the parameter once read.
        case .newRoles: return root.appending(queryItems: [URLQueryItem(name: "lens", value: "new")])
        case .settings: return root.appendingPathComponent("settings")
        case .schedule: return root.appendingPathComponent("settings/schedule")
        }
    }
}

public enum PollPolicy {
    public static func delay(panelOpen: Bool, active: Bool, failures: Int) -> TimeInterval {
        if failures > 0 { return min(300, 15 * pow(2, Double(min(failures - 1, 5)))) }
        return active ? (panelOpen ? 3 : 15) : 60
    }
}
