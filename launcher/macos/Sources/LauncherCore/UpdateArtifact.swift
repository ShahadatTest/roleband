import CryptoKit
import Darwin
import Foundation

public enum ArtifactProblem: Error, Sendable {
    case untrustedKey, invalidSignature, invalidMetadata, invalidImage
}

/// Metadata authenticated by the installed app's key, independent of the release server.
public struct VerifiedArtifact: Sendable {
    public let version: String
    public let commit: String
    public let imageName: String
    public let bytes: Int64
    public let sha256: String
    /// The signed "Before you update" notice: one paragraph the offer shows above Update.
    public internal(set) var beforeYouUpdate: String? = nil

    public static func installedPublicKey(in bundle: Bundle = .main) throws -> Data {
        guard bundle.bundleIdentifier == "com.roleband.launcher",
              bundle.object(forInfoDictionaryKey: "RoleBandPackagedEngine") as? Bool == true,
              bundle.object(forInfoDictionaryKey: "RoleBandReleaseCandidate") == nil,
              bundle.object(forInfoDictionaryKey: "RoleBandPreview") == nil,
              let encoded = bundle.object(forInfoDictionaryKey: "RoleBandUpdatePublicKey") as? String,
              let key = Data(base64Encoded: encoded), key.count == 32 else { throw ArtifactProblem.untrustedKey }
        return key
    }

    /// The release key held back for replacing a lost or leaked one. A release signed with it is
    /// trusted as if signed with the current key.
    public static func installedSpareKey(in bundle: Bundle = .main) throws -> Data? {
        try spareKey(bundle.object(forInfoDictionaryKey: "RoleBandUpdateSpareKey"), primary: installedPublicKey(in: bundle))
    }

    static func spareKey(_ value: Any?, primary: Data) throws -> Data? {
        guard let value else { return nil }
        guard let encoded = value as? String, let key = Data(base64Encoded: encoded), key.count == 32, key != primary else {
            throw ArtifactProblem.untrustedKey
        }
        return key
    }

    private struct Manifest: Decodable {
        let format: Int
        let version: String
        let commit: String
        let tag: String
        let architecture: String
        let minimum_macos: String
        let signing: String
        let notarized: Bool
        let image: String
        let sha256: String
        let bytes: Int64
        let release_key_sha256: String
        let previous_release_dmg_bytes: Int64?
        let growth_note: String?
        let before_you_update: String?
    }

    /// Format 2 is a release without a notice; format 3 adds the signed notice and nothing else.
    static let noticeLimit = 400

    public static func authenticate(checksum: Data, metadata: Data, signature: Data,
                                    publicKey: Data, spareKey: Data? = nil, version: String) throws -> Self {
        let trusted = [publicKey] + (spareKey.map { [$0] } ?? [])
        guard trusted.allSatisfy({ $0.count == 32 }), Set(trusted).count == trusted.count,
              case let keys = trusted.compactMap({ try? Curve25519.Signing.PublicKey(rawRepresentation: $0) }),
              keys.count == trusted.count else {
            throw ArtifactProblem.untrustedKey
        }
        guard checksum.count <= 512, metadata.count <= 4096, signature.count == 64 else {
            throw ArtifactProblem.invalidMetadata
        }
        guard let signer = keys.first(where: { $0.isValidSignature(signature, for: checksum + metadata) }) else {
            throw ArtifactProblem.invalidSignature
        }
        let fields: Set<String> = ["format", "version", "commit", "tag", "architecture", "minimum_macos",
            "signing", "notarized", "image", "sha256", "bytes", "release_key_sha256",
            "previous_release_dmg_bytes", "growth_note"]
        guard let object = try? JSONSerialization.jsonObject(with: metadata) as? [String: Any],
              let manifest = try? JSONDecoder().decode(Manifest.self, from: metadata),
              manifest.format == 2 && Set(object.keys) == fields
                || manifest.format == 3 && Set(object.keys) == fields.union(["before_you_update"])
                   && manifest.before_you_update.map(Self.isNotice) == true,
              ReleaseVersion(version) != nil, manifest.version == version, manifest.tag == "v" + version,
              manifest.architecture == "arm64", manifest.minimum_macos == "14.0",
              manifest.signing == "self-signed", !manifest.notarized,
              hexadecimal(manifest.commit, length: 40), hexadecimal(manifest.sha256, length: 64),
              manifest.release_key_sha256 == hex(SHA256.hash(data: signer.rawRepresentation)), manifest.bytes > 0,
              manifest.image == ReleaseFiles.prefix(version) + ".dmg",
              checksum == Data("\(manifest.sha256)  \(manifest.image)\n".utf8),
              manifest.previous_release_dmg_bytes == nil || manifest.previous_release_dmg_bytes! > 0 else {
            throw ArtifactProblem.invalidMetadata
        }
        return Self(version: version, commit: manifest.commit, imageName: manifest.image,
                    bytes: manifest.bytes, sha256: manifest.sha256, beforeYouUpdate: manifest.before_you_update)
    }

    /// One paragraph of at most `noticeLimit` Unicode scalars, with no edge spaces, controls or line breaks.
    static func isNotice(_ text: String) -> Bool {
        let scalars = text.unicodeScalars
        return !scalars.isEmpty && scalars.count <= noticeLimit && text == text.trimmingCharacters(in: .whitespacesAndNewlines)
            && !scalars.contains { [.control, .lineSeparator, .paragraphSeparator].contains($0.properties.generalCategory) }
    }

    /// Hash the opened regular file, refusing links and stopping at the signed size.
    public func verifyImage(at path: URL) throws {
        let descriptor = open(path.path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK)
        guard descriptor >= 0 else { throw ArtifactProblem.invalidImage }
        let file = FileHandle(fileDescriptor: descriptor, closeOnDealloc: true)
        defer { try? file.close() }
        var info = stat()
        guard fstat(descriptor, &info) == 0, info.st_mode & S_IFMT == S_IFREG, info.st_size == bytes else {
            throw ArtifactProblem.invalidImage
        }
        var hash = SHA256()
        var read: Int64 = 0
        while let block = try file.read(upToCount: 1 << 20), !block.isEmpty {
            try Task.checkCancellation()
            read += Int64(block.count)
            guard read <= bytes else { throw ArtifactProblem.invalidImage }
            hash.update(data: block)
        }
        guard read == bytes, Self.hex(hash.finalize()) == sha256 else { throw ArtifactProblem.invalidImage }
    }

    private static func hexadecimal(_ value: String, length: Int) -> Bool {
        value.utf8.count == length && value.utf8.allSatisfy { (48...57).contains($0) || (97...102).contains($0) }
    }
    private static func hex<D: Sequence>(_ digest: D) -> String where D.Element == UInt8 {
        digest.map { String(format: "%02x", $0) }.joined()
    }
}
