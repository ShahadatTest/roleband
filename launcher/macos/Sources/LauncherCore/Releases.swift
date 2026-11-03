import Foundation

public struct ReleaseVersion: Comparable, Sendable {
    private let numbers: [String]
    private let prerelease: [String]
    public init?(_ value: String) {
        guard !value.isEmpty, value.utf8.count <= 128 else { return nil }
        func identifier(_ part: Substring) -> Bool {
            !part.isEmpty && part.utf8.allSatisfy { (48...57).contains($0) || (65...90).contains($0) || (97...122).contains($0) || $0 == 45 }
        }
        func numeric(_ part: Substring) -> Bool { !part.isEmpty && part.utf8.allSatisfy { (48...57).contains($0) } }
        let build = value.split(separator: "+", omittingEmptySubsequences: false)
        guard build.count <= 2, build.count == 1 || (!build[1].isEmpty && build[1].split(separator: ".", omittingEmptySubsequences: false).allSatisfy(identifier)) else { return nil }
        let release = build[0].split(separator: "-", maxSplits: 1, omittingEmptySubsequences: false)
        let core = release[0].split(separator: ".", omittingEmptySubsequences: false)
        guard release.count == 1 || !release[1].isEmpty else { return nil }
        guard core.count == 3, core.allSatisfy({ numeric($0) && ($0.count == 1 || $0.first != "0") }) else { return nil }
        let pre = release.count == 2 ? release[1].split(separator: ".", omittingEmptySubsequences: false) : []
        guard pre.allSatisfy({ identifier($0) && (!numeric($0) || $0.count == 1 || $0.first != "0") }) else { return nil }
        numbers = core.map(String.init)
        prerelease = pre.map(String.init)
    }
    private static func numericLess(_ a: String, _ b: String) -> Bool { a.count == b.count ? a < b : a.count < b.count }
    public static func < (a: Self, b: Self) -> Bool {
        for (left, right) in zip(a.numbers, b.numbers) where left != right { return numericLess(left, right) }
        if a.prerelease.isEmpty || b.prerelease.isEmpty { return !a.prerelease.isEmpty && b.prerelease.isEmpty }
        for (left, right) in zip(a.prerelease, b.prerelease) where left != right {
            let ln = left.utf8.allSatisfy { (48...57).contains($0) }, rn = right.utf8.allSatisfy { (48...57).contains($0) }
            return ln && rn ? numericLess(left, right) : ln != rn ? ln : left < right
        }
        return a.prerelease.count < b.prerelease.count
    }
}

public struct InstalledNotes: Sendable {
    public let identity: Installation
    public let notes: String?
    public var version: String { identity.version }
    public static func decode(_ data: Data, status: VerifiedStatus) throws -> Self {
        struct Reply: Decodable { let launcher: Installation?; let version: String; let notes: String? }
        guard data.count <= 262144, let reply = try? JSONDecoder().decode(Reply.self, from: data), let identity = reply.launcher,
              identity.product == status.installation.product, identity.instance == status.installation.instance,
              identity.apiOrigin == status.installation.apiOrigin, identity.format == status.installation.format,
              identity.version == reply.version, reply.version == status.engineVersion, ReleaseVersion(reply.version) != nil,
              (reply.notes?.utf8.count ?? 0) <= 65536 else { throw ConnectionProblem.invalidResponse }
        return Self(identity: identity, notes: reply.notes)
    }
}

public enum ReleaseClient {
    public static func read(_ status: VerifiedStatus, source: InstallationSource) async throws -> InstalledNotes {
        try source.confirm(status.installation)
        let root = try status.installation.target().pageURL
        let data = try await LocalHTTP.read(URLRequest(url: root.appendingPathComponent("api/release-notes")))
        try source.confirm(status.installation)
        return try InstalledNotes.decode(data, status: status)
    }
}
