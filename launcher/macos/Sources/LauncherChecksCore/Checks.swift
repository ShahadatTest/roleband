import Foundation

public enum ProbeError: Error, Equatable, Sendable {
    case invalidTarget
}

public struct ProbeTarget: Sendable {
    public let url: URL
    public init(_ raw: String) throws {
        guard let parts = URLComponents(string: raw), parts.scheme == "http",
              let host = parts.host, ["127.0.0.1", "localhost", "::1", "[::1]"].contains(host),
              parts.user == nil, parts.password == nil, parts.query == nil, parts.fragment == nil,
              parts.path == "/api/status", (1...65535).contains(parts.port ?? 80),
              let url = parts.url else { throw ProbeError.invalidTarget }
        self.url = url
    }
    public var pageURL: URL {
        var parts = URLComponents(url: url, resolvingAgainstBaseURL: false)!
        parts.path = "/"
        return parts.url!
    }
}
