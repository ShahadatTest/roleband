import CryptoKit
import Foundation

public struct InstalledUpdateIdentity: Sendable {
    public let version: String
    public let commit: String
    public let publicKey: Data
    public let spareKey: Data?
    public let certificateSHA256: String
    /// The code requirement an update's app must meet, stamped into the installed app when it was
    /// sealed. Without one, an update must carry the installed app's own certificate.
    public let signingRule: String?

    public init(version: String, commit: String, publicKey: Data, spareKey: Data? = nil, certificateSHA256: String,
                signingRule: String? = nil) {
        self.version = version; self.commit = commit; self.publicKey = publicKey
        self.spareKey = spareKey; self.certificateSHA256 = certificateSHA256; self.signingRule = signingRule
    }

    /// The keys an update's app may carry as its own: the current one, or the spare after a key is replaced.
    var trustedKeys: [Data] { [publicKey] + (spareKey.map { [$0] } ?? []) }
}

/// `signer`: the app carries a valid Apple Developer ID signature that the installed app's rule
/// does not accept yet. Any other signer the rule refuses is `signature`.
public enum BundleInstallProblem: Error, Sendable { case invalidBundle, signature, signer, mount, staging }

public struct UpdateBundleVerifier: Sendable {
    private let command: @Sendable (URL, [String]) async throws -> CommandOutput
    public init() { command = { try await CommandRunner.run(executable: $0, arguments: $1, timeout: 60) } }
    init(command: @escaping @Sendable (URL, [String]) async throws -> CommandOutput) { self.command = command }

    public func installed(at app: URL) async throws -> InstalledUpdateIdentity {
        let info = try metadata(app)
        guard let version = info["RoleBandVersion"] as? String,
              let commit = info["RoleBandSourceRevision"] as? String else { throw BundleInstallProblem.invalidBundle }
        let key = try key(info)
        try validateFields(info, version: version, commit: commit, keys: [key])
        let certificate = try await certificate(app)
        let rule = try Self.signingRule(info)
        // A rule the installed app itself fails would refuse every update; refuse it here, where it shows.
        if let rule, !(try await satisfies(app, rule)) { throw BundleInstallProblem.invalidBundle }
        return InstalledUpdateIdentity(version: version, commit: commit, publicKey: key,
                                       spareKey: try VerifiedArtifact.spareKey(info["RoleBandUpdateSpareKey"], primary: key),
                                       certificateSHA256: certificate, signingRule: rule)
    }

    public func validate(_ app: URL, version: String, commit: String, trust: InstalledUpdateIdentity) async throws {
        let info = try metadata(app)
        try validateFields(info, version: version, commit: commit, keys: trust.trustedKeys)
        try Self.checkModes(app)
        let own = try Self.signingRule(info)
        let certificate = try await certificate(app)
        let accepted: Bool
        if let rule = trust.signingRule {
            accepted = try await satisfies(app, rule)
        } else {
            accepted = certificate == trust.certificateSHA256
        }
        guard accepted else {
            // Only a signer Apple vouches for reads as a new signer. Any other is a failed check, so a
            // stolen release key with a self-made certificate cannot ask the person to install by hand.
            let vouched = try await satisfies(app, Self.developerID)
            throw vouched ? BundleInstallProblem.signer : BundleInstallProblem.signature
        }
        // An update that fails its own rule would refuse every update after it.
        if let own, own != trust.signingRule, !(try await satisfies(app, own)) { throw BundleInstallProblem.invalidBundle }
    }

    /// An Apple Developer ID Application signature: the Developer ID intermediate certificate and
    /// the Developer ID Application leaf, both issued under Apple's root.
    static let developerID = "anchor apple generic and certificate 1[field.1.2.840.113635.100.6.2.6] exists"
        + " and certificate leaf[field.1.2.840.113635.100.6.1.13] exists"

    static func signingRule(_ info: [String: Any]) throws -> String? {
        guard let value = info["RoleBandUpdateRequirement"] else { return nil }
        guard let rule = value as? String, !rule.isEmpty, rule.utf8.count <= 1024 else { throw BundleInstallProblem.invalidBundle }
        return rule
    }

    private func satisfies(_ app: URL, _ rule: String) async throws -> Bool {
        try await command(URL(fileURLWithPath: "/usr/bin/codesign"), ["--verify", "-R", "=" + rule, app.path]).exitCode == 0
    }

    private func metadata(_ app: URL) throws -> [String: Any] {
        let fileManager = FileManager.default
        let attrs = try fileManager.attributesOfItem(atPath: app.path)
        guard app.pathExtension == "app", attrs[.type] as? FileAttributeType == .typeDirectory else {
            throw BundleInstallProblem.invalidBundle
        }
        let path = app.appendingPathComponent("Contents/Info.plist")
        guard (try fileManager.attributesOfItem(atPath: path.path))[.type] as? FileAttributeType == .typeRegular else {
            throw BundleInstallProblem.invalidBundle
        }
        let file = try FileHandle(forReadingFrom: path)
        defer { try? file.close() }
        let bytes = try file.read(upToCount: 65537) ?? Data()
        guard bytes.count <= 65536,
              let info = try PropertyListSerialization.propertyList(from: bytes, format: nil) as? [String: Any] else {
            throw BundleInstallProblem.invalidBundle
        }
        let prefix = app.resolvingSymlinksInPath().standardizedFileURL.path + "/"
        for relative in ["Contents/MacOS/RoleBandLauncher", "Contents/Resources/python/bin/python3.12",
                         "Contents/Resources/engine/packaged.py", "Contents/Resources/engine/alembic.ini",
                         "Contents/Resources/dashboard/index.html", "Contents/Resources/engine/release.json"] {
            let item = app.appendingPathComponent(relative).resolvingSymlinksInPath().standardizedFileURL
            guard item.path.hasPrefix(prefix),
                  (try fileManager.attributesOfItem(atPath: item.path))[.type] as? FileAttributeType == .typeRegular else {
                throw BundleInstallProblem.invalidBundle
            }
        }
        let release = app.appendingPathComponent("Contents/Resources/engine/release.json")
        let releaseFile = try FileHandle(forReadingFrom: release)
        defer { try? releaseFile.close() }
        let data = try releaseFile.read(upToCount: 4097) ?? Data()
        guard data.count <= 4096,
              let metadata = try JSONSerialization.jsonObject(with: data) as? [String: String],
              metadata["version"] == info["RoleBandVersion"] as? String else { throw BundleInstallProblem.invalidBundle }
        return info
    }

    /// Code signatures do not cover file modes: a file another user may write, or a setuid file,
    /// passes every signature check and keeps its mode when copied into Applications.
    static func checkModes(_ app: URL) throws {
        func safe(_ path: String) -> Bool {
            var info = stat()
            guard lstat(path, &info) == 0 else { return false }
            let type = info.st_mode & S_IFMT
            if type == S_IFLNK { return true }
            return (type == S_IFREG || type == S_IFDIR) && info.st_mode & (S_IWGRP | S_IWOTH | S_ISUID | S_ISGID) == 0
        }
        guard safe(app.path), let walker = FileManager.default.enumerator(atPath: app.path) else {
            throw BundleInstallProblem.invalidBundle
        }
        for case let relative as String in walker where !safe(app.appendingPathComponent(relative).path) {
            throw BundleInstallProblem.invalidBundle
        }
    }

    private func key(_ info: [String: Any]) throws -> Data {
        guard let encoded = info["RoleBandUpdatePublicKey"] as? String,
              let data = Data(base64Encoded: encoded), data.count == 32 else { throw ArtifactProblem.untrustedKey }
        return data
    }

    /// Every sealed app names its feed, and an update must name the one feed the app follows. The key
    /// check below holds the update to the release keys the installed app trusts.
    private func validateFields(_ info: [String: Any], version: String, commit: String, keys: [Data]) throws {
        guard ReleaseVersion(version) != nil, commit.utf8.count == 40,
              commit.utf8.allSatisfy({ (48...57).contains($0) || (97...102).contains($0) }),
              info["CFBundleIdentifier"] as? String == "com.roleband.launcher",
              info["CFBundleExecutable"] as? String == "RoleBandLauncher",
              info["RoleBandPackagedEngine"] as? Bool == true,
              info["RoleBandSourceDirty"] as? Bool == false,
              info["RoleBandReleaseCandidate"] == nil, info["RoleBandPreview"] == nil,
              info["RoleBandRegistration"] == nil, info["RoleBandDemoReleaseFile"] == nil,
              info["RoleBandVersion"] as? String == version,
              info["RoleBandSourceRevision"] as? String == commit,
              info["LSMinimumSystemVersion"] as? String == "14.0",
              (info["RoleBandUpdateFeed"] as? String).flatMap(UpdateRepository.init(rawValue:)) != nil,
              info["CFBundleVersion"] as? String == version.split(whereSeparator: { $0 == "-" || $0 == "+" }).first.map(String.init),
              case let key = try self.key(info), keys.contains(key),
              (try? VerifiedArtifact.spareKey(info["RoleBandUpdateSpareKey"], primary: key)) != nil
                || info["RoleBandUpdateSpareKey"] == nil else { throw BundleInstallProblem.invalidBundle }
    }

    private func certificate(_ app: URL) async throws -> String {
        let codesign = URL(fileURLWithPath: "/usr/bin/codesign")
        guard try await command(codesign, ["--verify", "--deep", "--strict", app.path]).exitCode == 0 else {
            throw BundleInstallProblem.signature
        }
        let architecture = try await command(URL(fileURLWithPath: "/usr/bin/lipo"),
                                             ["-archs", app.appendingPathComponent("Contents/MacOS/RoleBandLauncher").path])
        guard architecture.exitCode == 0, architecture.text.trimmingCharacters(in: .whitespacesAndNewlines) == "arm64" else {
            throw BundleInstallProblem.invalidBundle
        }
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent("update-certificate-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
        defer { try? FileManager.default.removeItem(at: folder) }
        let prefix = folder.appendingPathComponent("cert").path
        guard try await command(codesign, ["--display", "--extract-certificates=" + prefix, app.path]).exitCode == 0,
              let data = try? Data(contentsOf: URL(fileURLWithPath: prefix + "0")), !data.isEmpty, data.count <= 65536 else {
            throw BundleInstallProblem.signature
        }
        return SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }
}

public struct UpdateImageStager: Sendable {
    private let command: @Sendable (URL, [String]) async throws -> CommandOutput
    private let verifier: UpdateBundleVerifier
    public init() {
        command = { try await CommandRunner.run(executable: $0, arguments: $1, timeout: 120) }
        verifier = UpdateBundleVerifier()
    }
    init(command: @escaping @Sendable (URL, [String]) async throws -> CommandOutput, verifier: UpdateBundleVerifier) {
        self.command = command; self.verifier = verifier
    }

    public func stage(_ update: DownloadedUpdate, installed: URL, destination: URL) async throws -> InstalledUpdateIdentity {
        try update.artifact.verifyImage(at: update.image)
        let trust = try await verifier.installed(at: installed)
        guard let previous = ReleaseVersion(trust.version), let next = ReleaseVersion(update.artifact.version), previous < next,
              (try? FileManager.default.attributesOfItem(atPath: destination.path)) == nil else { throw BundleInstallProblem.staging }
        let parent = destination.deletingLastPathComponent()
        try FileManager.default.createDirectory(at: parent, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        let attributes = try FileManager.default.attributesOfItem(atPath: parent.path)
        guard attributes[.type] as? FileAttributeType == .typeDirectory,
              (attributes[.ownerAccountID] as? NSNumber)?.uint32Value == getuid(),
              (attributes[.posixPermissions] as? NSNumber)?.intValue == 0o700 else { throw BundleInstallProblem.staging }
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent("update-mount-" + UUID().uuidString)
        let mount = folder.appendingPathComponent("volume")
        try FileManager.default.createDirectory(at: mount, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        var mayBeMounted = true
        defer { if !mayBeMounted { try? FileManager.default.removeItem(at: folder) } }
        let tool = URL(fileURLWithPath: "/usr/bin/hdiutil")
        do {
            let attached = try await command(tool, ["attach", "-readonly", "-nobrowse", "-noautoopen", "-mountpoint", mount.path, update.image.path])
            guard attached.exitCode == 0 else { throw BundleInstallProblem.mount }
            let app = mount.appendingPathComponent("RoleBand.app")
            try await verifier.validate(app, version: update.artifact.version, commit: update.artifact.commit, trust: trust)
            try Task.checkCancellation()
            try FileManager.default.copyItem(at: app, to: destination)
            try await verifier.validate(destination, version: update.artifact.version, commit: update.artifact.commit, trust: trust)
            let detached = try await command(tool, ["detach", mount.path])
            guard detached.exitCode == 0 else { throw BundleInstallProblem.mount }
            mayBeMounted = false
            return trust
        } catch {
            // Detaching uses a fresh task so cancellation cannot leave the image mounted.
            let detached = try? await Task { try await command(tool, ["detach", mount.path]) }.value
            if detached?.exitCode == 0 { mayBeMounted = false }
            else {
                let forced = try? await Task { try await command(tool, ["detach", "-force", mount.path]) }.value
                if forced?.exitCode == 0 { mayBeMounted = false }
            }
            throw error
        }
    }
}
