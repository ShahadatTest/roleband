import Foundation

public enum ScanAction: Sendable { case start, stop }
public enum ControlProblem: Error, Equatable { case stateChanged, refused }
public enum ScanOutcome: Sendable {
    case requested, alreadyRunning, stopRequested, notRunning
    /// The line the panel shows once the engine answers. A scan that started or a stop the engine
    /// took has none: the scan picture and the button already show it, and the line would stay
    /// for the whole scan. A press that changed nothing says why.
    public var key: String? {
        switch self {
        case .requested, .stopRequested: nil
        case .alreadyRunning: "scan-already-running"
        case .notRunning: "scan-not-running"
        }
    }
}

public struct ScanState: Sendable {
    public let running: Bool
    public let manualRunning: Bool
    public let manualQueued: [String]
    public func action(for status: Presentation) -> ScanAction? {
        if manualRunning || !manualQueued.isEmpty { return .stop }
        guard !running, status.activity != .scanning, status.hold == nil, status.queued == nil else { return nil }
        return .start
    }
}

public enum ScanClient {
    public static func perform(_ action: ScanAction, installation: Installation, source: InstallationSource) async throws -> ScanOutcome {
        try source.confirm(installation)
        let status = try await StatusClient.read(installation)
        try source.confirm(installation)
        guard status.scanAction == action else { throw ControlProblem.stateChanged }
        let root = try installation.target().pageURL
        let url = root.appendingPathComponent(action == .start ? "api/sync" : "api/sync/cancel")
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.httpBody = Data("{}".utf8)
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue(installation.apiOrigin, forHTTPHeaderField: "Origin")
        // A timed-out mutation may have committed, so only an explicit user action sends another request.
        let data = try await LocalHTTP.read(request, mutation: true)
        try source.confirm(installation)
        return try decode(data, action: action)
    }

    public static func decode(_ data: Data, action: ScanAction) throws -> ScanOutcome {
        struct Reply: Decodable { let status: String }
        guard data.count <= 262144, let reply = try? JSONDecoder().decode(Reply.self, from: data) else {
            throw ConnectionProblem.invalidResponse
        }
        switch (action, reply.status) {
        case (.start, "started"): return .requested
        case (.start, "already_running"): return .alreadyRunning
        case (.stop, "cancelled"): return .stopRequested
        case (.stop, "not_running"): return .notRunning
        default: throw ConnectionProblem.invalidResponse
        }
    }
}

/// What the scan picture is about. A stop finishes the run inside its own request, so Stopping
/// lasts exactly as long as that request; Starting covers the request and a scan the engine has
/// queued but not begun.
public enum ScanPhase: Sendable, Equatable {
    case scanning, stopping, requesting, idle, stopped

    public static func of(_ status: Presentation, picture: ScanPicture?, requested: ScanAction?) -> ScanPhase {
        if status.activity == .scanning { return requested == .stop ? .stopping : .scanning }
        if requested == .start || status.queued == "scan" { return .requesting }
        return picture?.lastStopped == true ? .stopped : .idle
    }

    /// A scan past its reading says which of the dashboard's two closing steps it is in.
    public func titleKey(_ picture: ScanPicture?) -> String {
        guard self == .scanning else { return titleKey }
        switch picture?.stage {
        case .persisting: return "scan-title-adding"
        case .finishing: return "scan-title-finishing"
        case .collecting, nil: return titleKey
        }
    }

    public var titleKey: String {
        switch self {
        case .scanning: "scan-title-scanning"
        case .stopping: "scan-title-stopping"
        case .requesting: "scan-title-requesting"
        case .idle: "scan-title-idle"
        case .stopped: "scan-title-stopped"
        }
    }
}
