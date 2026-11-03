import Foundation

public enum SetupStep: Int, CaseIterable, Sendable {
    case welcome, installation, connection, login, done
    /// The saved form of a step: its name, so adding a step never moves a saved position.
    public var id: String { String(describing: self) }
    public init?(id: String) {
        guard let step = Self.allCases.first(where: { $0.id == id }) else { return nil }
        self = step
    }
    public func next(connected: Bool, installed: Bool = true) -> Self {
        if self == .welcome && installed { return .connection }
        if self == .installation && !installed { return .installation }
        if self == .connection && !connected { return .connection }
        return Self(rawValue: min(rawValue + 1, Self.done.rawValue))!
    }
    public func previous(installed: Bool) -> Self {
        if self == .connection && installed { return .welcome }
        return Self(rawValue: max(0, rawValue - 1))!
    }
    public static func steps(installed: Bool) -> [Self] {
        allCases.filter { !installed || $0 != .installation }
    }
}

public enum LoginState: Sendable, Equatable {
    case off, on, approval, unknown
}

public enum AppLocation {
    public static func isInstalled(_ bundle: URL, home: URL) -> Bool {
        let path = bundle.resolvingSymlinksInPath().standardizedFileURL
        guard path.pathExtension == "app" else { return false }
        return [URL(fileURLWithPath: "/Applications"), home.appendingPathComponent("Applications")]
            .contains { path.deletingLastPathComponent().path == $0.resolvingSymlinksInPath().standardizedFileURL.path }
    }
}
