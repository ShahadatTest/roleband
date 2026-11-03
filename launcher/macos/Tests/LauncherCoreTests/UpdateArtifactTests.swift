import CryptoKit
import Foundation
import Testing
@testable import LauncherCore

private struct ArtifactFixture: Decodable {
    let publicKey: Data
    let metadata: Data
    let checksum: Data
    let signature: Data
    let image: Data
    static func load(_ name: String = "update-artifact") throws -> Self {
        let path = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
            .appendingPathComponent("Fixtures/\(name).json")
        return try JSONDecoder().decode(Self.self, from: Data(contentsOf: path))
    }
    func authenticate() throws -> VerifiedArtifact {
        try VerifiedArtifact.authenticate(checksum: checksum, metadata: metadata, signature: signature,
                                          publicKey: publicKey, version: "0.1.1")
    }
}

@Test(arguments: ["release", "candidate", "preview", "source", "missing-key", "bad-key", "wrong-app"])
func updateTrustComesOnlyFromTheInstalledReleaseBundle(kind: String) throws {
    let fixture = try ArtifactFixture.load()
    let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    let contents = root.appendingPathComponent("RoleBand.app/Contents")
    try FileManager.default.createDirectory(at: contents, withIntermediateDirectories: true)
    defer { try? FileManager.default.removeItem(at: root) }
    var info: [String: Any] = ["CFBundleIdentifier": kind == "wrong-app" ? "other.app" : "com.roleband.launcher",
        "RoleBandPackagedEngine": kind != "source", "RoleBandUpdatePublicKey": fixture.publicKey.base64EncodedString()]
    if kind == "candidate" { info["RoleBandReleaseCandidate"] = true }
    if kind == "preview" { info["RoleBandPreview"] = true }
    if kind == "missing-key" { info.removeValue(forKey: "RoleBandUpdatePublicKey") }
    if kind == "bad-key" { info["RoleBandUpdatePublicKey"] = "not-base64" }
    try PropertyListSerialization.data(fromPropertyList: info, format: .xml, options: 0)
        .write(to: contents.appendingPathComponent("Info.plist"))
    let bundle = try #require(Bundle(url: contents.deletingLastPathComponent()))
    if kind == "release" { #expect(try VerifiedArtifact.installedPublicKey(in: bundle) == fixture.publicKey) }
    else { #expect(throws: ArtifactProblem.self) { _ = try VerifiedArtifact.installedPublicKey(in: bundle) } }
}

@Test func nativeUpdaterAcceptsThePythonReleaseToolsExactSignedBytes() throws {
    let fixture = try ArtifactFixture.load()
    let artifact = try fixture.authenticate()
    #expect(artifact.version == "0.1.1" && artifact.commit == String(repeating: "a", count: 40))
    let path = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    defer { try? FileManager.default.removeItem(at: path) }
    try fixture.image.write(to: path)
    try artifact.verifyImage(at: path)
}

@Test(arguments: ["wrong-key", "missing-key", "signature", "checksum", "metadata", "version", "large-metadata", "large-checksum"])
func releaseAuthenticationRefusesTamperingAndUntrustedInputs(problem: String) throws {
    let fixture = try ArtifactFixture.load()
    var key = fixture.publicKey, signature = fixture.signature, checksum = fixture.checksum, metadata = fixture.metadata
    switch problem {
    case "wrong-key": key = Curve25519.Signing.PrivateKey().publicKey.rawRepresentation
    case "missing-key": key = Data()
    case "signature": signature[0] ^= 1
    case "checksum": checksum[0] ^= 1
    case "metadata": metadata[0] ^= 1
    case "large-metadata": metadata = Data(repeating: 0, count: 4097)
    case "large-checksum": checksum = Data(repeating: 0, count: 513)
    default: break
    }
    #expect(throws: ArtifactProblem.self) {
        _ = try VerifiedArtifact.authenticate(checksum: checksum, metadata: metadata, signature: signature,
            publicKey: key, version: problem == "version" ? "0.1.2" : "0.1.1")
    }
}

@Test(arguments: ["format", "architecture", "image", "digest", "commit", "bytes", "key-pin", "unknown-field"])
func evenAuthenticallySignedMetadataMustMatchTheSupportedProductContract(problem: String) throws {
    let fixture = try ArtifactFixture.load()
    var object = try JSONSerialization.jsonObject(with: fixture.metadata) as! [String: Any]
    switch problem {
    case "format": object["format"] = 3
    case "architecture": object["architecture"] = "x86_64"
    case "image": object["image"] = "../Other.app"
    case "digest": object["sha256"] = String(repeating: "z", count: 64)
    case "commit": object["commit"] = "moving-tag"
    case "bytes": object["bytes"] = -1
    case "key-pin": object["release_key_sha256"] = String(repeating: "0", count: 64)
    default: object["unrecognized"] = true
    }
    let metadata = try JSONSerialization.data(withJSONObject: object)
    let signer = Curve25519.Signing.PrivateKey()
    // Keep the key pin valid so each product-contract check is exercised independently.
    if problem != "key-pin" {
        object["release_key_sha256"] = SHA256.hash(data: signer.publicKey.rawRepresentation)
            .map { String(format: "%02x", $0) }.joined()
    }
    let signed = problem == "key-pin" ? metadata : try JSONSerialization.data(withJSONObject: object)
    let checksum = Data("\(object["sha256"] as! String)  \(object["image"] as! String)\n".utf8)
    let signature = try signer.signature(for: checksum + signed)
    #expect(throws: ArtifactProblem.self) {
        _ = try VerifiedArtifact.authenticate(checksum: checksum, metadata: signed, signature: signature,
            publicKey: signer.publicKey.rawRepresentation, version: "0.1.1")
    }
}

@Test(arguments: ["corrupt", "truncated", "oversized", "symbolic-link", "directory"])
func authenticatedMetadataNeverMakesADifferentImageSafe(problem: String) throws {
    let fixture = try ArtifactFixture.load()
    let artifact = try fixture.authenticate()
    let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
    defer { try? FileManager.default.removeItem(at: root) }
    let path = root.appendingPathComponent("image")
    switch problem {
    case "directory": try FileManager.default.createDirectory(at: path, withIntermediateDirectories: true)
    case "symbolic-link":
        let target = root.appendingPathComponent("target")
        try fixture.image.write(to: target)
        try FileManager.default.createSymbolicLink(at: path, withDestinationURL: target)
    case "truncated": try fixture.image.dropLast().write(to: path)
    case "oversized": try (fixture.image + Data([0])).write(to: path)
    default:
        var image = fixture.image
        image[0] ^= 1
        try image.write(to: path)
    }
    #expect(throws: ArtifactProblem.self) { try artifact.verifyImage(at: path) }
}

@Test func aReleaseSignedWithTheSpareKeyIsTrustedOnlyWhenItsPinNamesThatKey() throws {
    let current = Curve25519.Signing.PrivateKey(), spare = Curve25519.Signing.PrivateKey()
    func signed(by signer: Curve25519.Signing.PrivateKey, pin: Curve25519.Signing.PrivateKey) throws -> (Data, Data, Data) {
        let fixture = try ArtifactFixture.load()
        var object = try JSONSerialization.jsonObject(with: fixture.metadata) as! [String: Any]
        object["release_key_sha256"] = SHA256.hash(data: pin.publicKey.rawRepresentation).map { String(format: "%02x", $0) }.joined()
        let metadata = try JSONSerialization.data(withJSONObject: object)
        return (fixture.checksum, metadata, try signer.signature(for: fixture.checksum + metadata))
    }
    func authenticate(_ release: (Data, Data, Data), spareKey: Data?) throws -> VerifiedArtifact {
        try VerifiedArtifact.authenticate(checksum: release.0, metadata: release.1, signature: release.2,
            publicKey: current.publicKey.rawRepresentation, spareKey: spareKey, version: "0.1.1")
    }
    let spareKey = spare.publicKey.rawRepresentation
    #expect(try authenticate(signed(by: spare, pin: spare), spareKey: spareKey).version == "0.1.1")
    #expect(try authenticate(signed(by: current, pin: current), spareKey: spareKey).version == "0.1.1")
    #expect(throws: ArtifactProblem.invalidSignature) { try authenticate(signed(by: spare, pin: spare), spareKey: nil) }
    #expect(throws: ArtifactProblem.invalidMetadata) { try authenticate(signed(by: spare, pin: current), spareKey: spareKey) }
    #expect(throws: ArtifactProblem.untrustedKey) {
        try authenticate(signed(by: current, pin: current), spareKey: current.publicKey.rawRepresentation)
    }
}

@Test(arguments: ["absent", "spare", "same-as-current", "short", "not-base64"])
func theInstalledSpareKeyIsOptionalButNeverMalformedOrTheCurrentKey(kind: String) throws {
    let fixture = try ArtifactFixture.load()
    let spare = Curve25519.Signing.PrivateKey().publicKey.rawRepresentation
    let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    let contents = root.appendingPathComponent("RoleBand.app/Contents")
    try FileManager.default.createDirectory(at: contents, withIntermediateDirectories: true)
    defer { try? FileManager.default.removeItem(at: root) }
    var info: [String: Any] = ["CFBundleIdentifier": "com.roleband.launcher", "RoleBandPackagedEngine": true,
                               "RoleBandUpdatePublicKey": fixture.publicKey.base64EncodedString()]
    switch kind {
    case "spare": info["RoleBandUpdateSpareKey"] = spare.base64EncodedString()
    case "same-as-current": info["RoleBandUpdateSpareKey"] = fixture.publicKey.base64EncodedString()
    case "short": info["RoleBandUpdateSpareKey"] = Data(repeating: 1, count: 31).base64EncodedString()
    case "not-base64": info["RoleBandUpdateSpareKey"] = "not-base64"
    default: break
    }
    try PropertyListSerialization.data(fromPropertyList: info, format: .xml, options: 0)
        .write(to: contents.appendingPathComponent("Info.plist"))
    let bundle = try #require(Bundle(url: contents.deletingLastPathComponent()))
    switch kind {
    case "absent": #expect(try VerifiedArtifact.installedSpareKey(in: bundle) == nil)
    case "spare": #expect(try VerifiedArtifact.installedSpareKey(in: bundle) == spare)
    default: #expect(throws: ArtifactProblem.untrustedKey) { _ = try VerifiedArtifact.installedSpareKey(in: bundle) }
    }
}

/// The "Before you update" notice is trusted only inside the signed metadata: format 3 carries one
/// valid paragraph, format 2 carries none, and any other shape is refused even when properly signed.
@Test func aSignedNoticeComesOnlyFromFormat3MetadataTheToolWrote() throws {
    let plain = try ArtifactFixture.load().authenticate()
    #expect(plain.beforeYouUpdate == nil)
    let noticed = try ArtifactFixture.load("update-artifact-notice")
    #expect(try noticed.authenticate().beforeYouUpdate == "This version moves your radar to a new storage format. A backup is made first.")

    let signer = try Curve25519.Signing.PrivateKey(rawRepresentation: Data(0..<32))
    #expect(signer.publicKey.rawRepresentation == noticed.publicKey)
    let base = try #require(JSONSerialization.jsonObject(with: noticed.metadata) as? [String: Any])
    func signed(_ change: (inout [String: Any]) -> Void) throws -> VerifiedArtifact {
        var object = base
        change(&object)
        let metadata = try JSONSerialization.data(withJSONObject: object)
        return try VerifiedArtifact.authenticate(checksum: noticed.checksum, metadata: metadata,
            signature: signer.signature(for: noticed.checksum + metadata), publicKey: noticed.publicKey, version: "0.1.1")
    }
    #expect(try signed { $0["before_you_update"] = String(repeating: "é", count: 400) }.beforeYouUpdate?.unicodeScalars.count == 400)
    let refused: [(String, (inout [String: Any]) -> Void)] = [
        ("format 3 without a notice", { $0.removeValue(forKey: "before_you_update") }),
        ("format 3 with a null notice", { $0["before_you_update"] = NSNull() }),
        ("format 2 with a notice", { $0["format"] = 2 }),
        ("format 4", { $0["format"] = 4 }),
        ("empty", { $0["before_you_update"] = "" }),
        ("padded", { $0["before_you_update"] = " A backup is made first." }),
        ("two lines", { $0["before_you_update"] = "A backup\nis made first." }),
        ("a tab", { $0["before_you_update"] = "A backup\tis made first." }),
        ("a line separator", { $0["before_you_update"] = "A backup\u{2028}is made first." }),
        ("too long", { $0["before_you_update"] = String(repeating: "x", count: 401) }),
        ("not text", { $0["before_you_update"] = 7 }),
    ]
    for (label, change) in refused {
        #expect(throws: ArtifactProblem.self, "\(label)") { _ = try signed(change) }
    }
}
