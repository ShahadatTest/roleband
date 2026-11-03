import Foundation

public enum PauseAction: String, CaseIterable, Sendable {
    case hour = "1h", threeHours = "3h", tomorrow, resume
    public var key: String {
        switch self {
        case .hour: "pause-hour"
        case .threeHours: "pause-three-hours"
        case .tomorrow: "pause-tomorrow"
        case .resume: "pause-resume"
        }
    }
}

public struct ScheduleState: Sendable, Equatable {
    /// Scans start on their own.
    public let enabled: Bool
    /// The schedule plan starts them, so a pause holds them.
    public let pausable: Bool
    public let pausedUntil: Date?
    public init(enabled: Bool, pausable: Bool, pausedUntil: Date?) {
        self.enabled = enabled
        self.pausable = pausable
        self.pausedUntil = pausedUntil
    }
    public func isPaused(at now: Date = Date()) -> Bool { pausedUntil.map { $0 > now } ?? false }

    /// The schedule reply: its `enabled` is the scheduler switch, and its plan's is the schedule plan.
    public static func decode(_ data: Data) throws -> Self {
        struct Plan: Decodable {
            let enabled: Bool
            let pausedUntil: Date?
            enum CodingKeys: String, CodingKey { case enabled; case pausedUntil = "paused_until" }
            init(from decoder: any Decoder) throws {
                let values = try decoder.container(keyedBy: CodingKeys.self)
                enabled = try values.decode(Bool.self, forKey: .enabled)
                guard values.contains(.pausedUntil) else { throw ConnectionProblem.invalidResponse }
                pausedUntil = try values.decodeIfPresent(Date.self, forKey: .pausedUntil)
            }
        }
        struct Reply: Decodable { let generated_at: Date; let enabled: Bool; let plan: Plan }
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .custom { decoder in
            guard let date = Stamp.date(try decoder.singleValueContainer().decode(String.self)) else {
                throw ConnectionProblem.invalidResponse
            }
            return date
        }
        guard data.count <= 4194304, let reply = try? decoder.decode(Reply.self, from: data) else {
            throw ConnectionProblem.invalidResponse
        }
        return Self(enabled: reply.enabled, pausable: reply.enabled && reply.plan.enabled, pausedUntil: reply.plan.pausedUntil)
    }
}

/// An engine timestamp, with or without fractional seconds. The live scan picture parses several
/// a frame, so the format styles are built once; they are values and safe to share.
public enum Stamp {
    private static let fractional = Date.ISO8601FormatStyle(includingFractionalSeconds: true)
    private static let whole = Date.ISO8601FormatStyle()
    public static func date(_ value: String?) -> Date? {
        guard let value else { return nil }
        return (try? fractional.parse(value)) ?? (try? whole.parse(value))
    }
}

public enum ScheduleClient {
    private static func url(_ installation: Installation, path: String, timezone: String) throws -> URL {
        let root = try installation.target().pageURL
        var parts = URLComponents(url: root.appendingPathComponent(path), resolvingAgainstBaseURL: false)!
        parts.queryItems = [URLQueryItem(name: "tz", value: timezone)]
        // URLComponents leaves "+" bare in a query, and the engine reads a bare "+" as a space.
        parts.percentEncodedQuery = parts.percentEncodedQuery?.replacingOccurrences(of: "+", with: "%2B")
        guard !timezone.isEmpty, timezone.count <= 64, let url = parts.url else { throw ConnectionProblem.invalidInstallation }
        return url
    }

    public static func read(_ status: VerifiedStatus, source: InstallationSource, timezone: String) async throws -> ScheduleState {
        let installation = status.installation
        try source.confirm(installation)
        let request = URLRequest(url: try url(installation, path: "api/schedule", timezone: timezone))
        // The existing schedule response includes the company roster, so it has a separate bounded read budget.
        let data = try await LocalHTTP.read(request, limit: 4194304)
        try source.confirm(installation)
        return try ScheduleState.decode(data)
    }

    public static func perform(_ action: PauseAction, installation: Installation, source: InstallationSource,
                               timezone: String) async throws -> ScheduleState {
        try source.confirm(installation)
        let status = try await StatusClient.read(installation)
        let plan = try await read(status, source: source, timezone: timezone)
        guard (action == .resume) == plan.isPaused() else { throw ControlProblem.stateChanged }
        guard action == .resume || plan.pausable else { throw ControlProblem.stateChanged }
        try source.confirm(installation)
        var request = URLRequest(url: try url(installation, path: "api/schedule/plan", timezone: timezone))
        request.httpMethod = "PUT"
        request.httpBody = try JSONEncoder().encode(["pause": action.rawValue])
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue(installation.apiOrigin, forHTTPHeaderField: "Origin")
        let data = try await LocalHTTP.read(request, mutation: true, limit: 4194304)
        try source.confirm(installation)
        let result = try ScheduleState.decode(data)
        guard action == .resume ? result.pausedUntil == nil : result.isPaused() else {
            throw ConnectionProblem.invalidResponse
        }
        return result
    }
}
