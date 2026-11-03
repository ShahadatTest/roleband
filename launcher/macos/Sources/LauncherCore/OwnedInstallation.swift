import CryptoKit
import Darwin
import Foundation

public extension Installation {
    static let ownedPort = 8010

    static func owned(bundle: Bundle = .main, port: Int = ownedPort) throws -> Installation {
        guard bundle.bundleIdentifier == LaunchMode.bundleIdentifier,
              bundle.object(forInfoDictionaryKey: "RoleBandPackagedEngine") as? Bool == true,
              let version = bundle.object(forInfoDictionaryKey: "RoleBandVersion") as? String,
              let resources = bundle.resourceURL else { throw ConnectionProblem.invalidInstallation }
        return try owned(resources: resources, version: version, port: port)
    }

    /// The identity of the app whose resources are at `resources`. An update reads it by path:
    /// Foundation can keep serving a `Bundle`'s first Info.plist after the app at that path is replaced.
    static func owned(resources: URL, version: String, port: Int = ownedPort) throws -> Installation {
        guard !version.isEmpty, !version.contains(where: { $0.isWhitespace || $0.isNewline }),
              (1...65535).contains(port), resources.lastPathComponent == "Resources",
              resources.deletingLastPathComponent().lastPathComponent == "Contents",
              let resolved = realpath(resources.path, nil) else { throw ConnectionProblem.invalidInstallation }
        defer { free(resolved) }
        // Foundation rewrites /private/tmp to /tmp. Hash the POSIX path bytes so the
        // instance matches the packaged engine's resolved Resources path.
        let digest = SHA256.hash(data: Data(bytes: resolved, count: strlen(resolved)))
        let instance = digest.prefix(12).map { String(format: "%02x", $0) }.joined()
        let installation = Installation(product: "roleband", instance: instance,
                                        apiOrigin: "http://127.0.0.1:\(port)", version: version, format: 1)
        _ = try installation.target()
        return installation
    }
}

public extension HostConfiguration {
    init(bundle: Bundle = .main, home: URL = FileManager.default.homeDirectoryForCurrentUser,
         port: Int = Installation.ownedPort) throws {
        let installation = try Installation.owned(bundle: bundle, port: port)
        guard let resources = bundle.resourceURL else { throw ConnectionProblem.invalidInstallation }
        try self.init(resources: resources, home: home, installation: installation)
    }
}
