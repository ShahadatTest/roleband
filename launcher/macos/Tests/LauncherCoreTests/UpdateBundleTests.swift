import CryptoKit
import Foundation
import Testing
@testable import LauncherCore

extension InstalledUpdateIdentity {
    var withoutRule: Self {
        Self(version:version, commit:commit, publicKey:publicKey, spareKey:spareKey, certificateSHA256:certificateSHA256)
    }
}

private struct BundleFixture {
    let root: URL
    let old: URL
    let next: URL
    init() throws {
        root = FileManager.default.temporaryDirectory.appendingPathComponent("update-bundles-" + UUID().uuidString)
        old = root.appendingPathComponent("old.app"); next = root.appendingPathComponent("new.app")
        for (app,version,revision) in [(old,"0.1.0",String(repeating:"a",count:40)),(next,"0.1.1",String(repeating:"b",count:40))] {
            for path in ["MacOS/RoleBandLauncher", "Resources/python/bin/python3.12", "Resources/engine/packaged.py",
                         "Resources/engine/alembic.ini", "Resources/dashboard/index.html"] {
                let file = app.appendingPathComponent("Contents/" + path)
                try FileManager.default.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
                try Data("fixture".utf8).write(to: file)
            }
            try Data("{\"version\":\"\(version)\"}".utf8).write(to: app.appendingPathComponent("Contents/Resources/engine/release.json"))
            try PropertyListSerialization.data(fromPropertyList: [
                "CFBundleIdentifier":"com.roleband.launcher", "CFBundleExecutable":"RoleBandLauncher",
                "CFBundleVersion":version, "RoleBandVersion":version, "RoleBandSourceRevision":revision,
                "RoleBandSourceDirty":false, "RoleBandPackagedEngine":true, "LSMinimumSystemVersion":"14.0",
                "RoleBandUpdatePublicKey":Data(repeating:1,count:32).base64EncodedString(),
                "RoleBandUpdateFeed":"roleband/roleband",
            ],format:.xml,options:0).write(to: app.appendingPathComponent("Contents/Info.plist"))
        }
    }
    func remove() { try? FileManager.default.removeItem(at: root) }
    func alter(_ field: String, value: Any, app: URL? = nil) throws {
        let file = (app ?? next).appendingPathComponent("Contents/Info.plist")
        var info = try PropertyListSerialization.propertyList(from: Data(contentsOf:file),format:nil) as! [String:Any]
        info[field] = value is NSNull ? nil : value
        try PropertyListSerialization.data(fromPropertyList:info,format:.xml,options:0).write(to:file)
    }
    /// `problem` is one or more space-separated words, so a test can combine them.
    func verifier(problem: String = "none") -> UpdateBundleVerifier {
        let problems = Set(problem.split(separator:" ").map(String.init))
        return UpdateBundleVerifier(command: { [old] executable, args in
            if executable.lastPathComponent == "lipo" { return CommandOutput(text: problems.contains("architecture") ? "x86_64" : "arm64",exitCode:0) }
            let isNew = args.last != old.path
            // The trusted rule holds for the old app always, and for the new one unless a problem says not.
            if let index = args.firstIndex(of:"-R") {
                let holds = switch args[index+1] {
                case "=trusted rule": !isNew || !problems.contains("rule-fails")
                case "=own rule": !problems.contains("own-rule-unmet")
                case "=" + UpdateBundleVerifier.developerID: isNew && problems.contains("developer-id")
                default: false
                }
                return CommandOutput(text:"",exitCode: holds ? 0 : 3)
            }
            if args.contains("--verify") { return CommandOutput(text:"",exitCode: problems.contains("signature") ? 1 : 0) }
            let prefix = try #require(args.first(where: { $0.hasPrefix("--extract-certificates=") }))
            let file = URL(fileURLWithPath: String(prefix.dropFirst("--extract-certificates=".count))+"0")
            try Data((problems.contains("certificate") && isNew ? "different certificate" : "trusted certificate").utf8).write(to:file)
            return CommandOutput(text:"",exitCode:0)
        })
    }
}

@Test func signedCandidateMustMatchTheInstalledKeyCertificateAndAuthenticatedSource() async throws {
    let f = try BundleFixture(); defer { f.remove() }
    let verifier = f.verifier()
    let trust = try await verifier.installed(at:f.old)
    try await verifier.validate(f.next,version:"0.1.1",commit:String(repeating:"b",count:40),trust:trust)
}

@Test func anUpdateMayCarryTheInstalledSpareKeyAsItsCurrentKeySoALostKeyCanBeReplaced() async throws {
    let f = try BundleFixture(); defer { f.remove() }
    let spare = Data(repeating:2,count:32).base64EncodedString()
    try f.alter("RoleBandUpdateSpareKey",value:spare, app:f.old)
    let trust = try await f.verifier().installed(at:f.old)
    #expect(trust.spareKey == Data(repeating:2,count:32))
    try f.alter("RoleBandUpdatePublicKey",value:spare)
    try f.alter("RoleBandUpdateSpareKey",value:Data(repeating:3,count:32).base64EncodedString())
    try await f.verifier().validate(f.next,version:"0.1.1",commit:String(repeating:"b",count:40),trust:trust)
    // Without a spare in the installed app, the same update names a key the app never trusted.
    let unspared = InstalledUpdateIdentity(version:trust.version,commit:trust.commit,publicKey:trust.publicKey,
                                           certificateSHA256:trust.certificateSHA256)
    await #expect(throws:(any Error).self) {
        try await f.verifier().validate(f.next,version:"0.1.1",commit:String(repeating:"b",count:40),trust:unspared)
    }
}

@Test(arguments:["spare-is-current","short-spare"])
func anUpdatesOwnSpareKeyMustBeWellFormed(problem:String) async throws {
    let f = try BundleFixture(); defer { f.remove() }
    let trust = try await f.verifier().installed(at:f.old)
    try f.alter("RoleBandUpdateSpareKey",value:problem == "short-spare" ? Data(repeating:3,count:31).base64EncodedString()
                                                                        : Data(repeating:1,count:32).base64EncodedString())
    await #expect(throws:(any Error).self) {
        try await f.verifier().validate(f.next,version:"0.1.1",commit:String(repeating:"b",count:40),trust:trust)
    }
}

@Test(arguments:[("0666 file","Contents/Resources/engine/packaged.py",0o666), ("0777 folder","Contents/Resources/engine",0o777),
                 ("setuid","Contents/MacOS/RoleBandLauncher",0o4755), ("setgid","Contents/MacOS/RoleBandLauncher",0o2755),
                 ("group-writable app","",0o775)])
func aCandidateAnotherUserCouldEditOrThatRunsAsAnotherUserIsRefused(name:String, path:String, mode:Int) async throws {
    let f = try BundleFixture(); defer { f.remove() }
    let trust = try await f.verifier().installed(at:f.old)
    let item = path.isEmpty ? f.next : f.next.appendingPathComponent(path)
    try FileManager.default.setAttributes([.posixPermissions:mode], ofItemAtPath:item.path)
    await #expect(throws:BundleInstallProblem.invalidBundle) {
        try await f.verifier().validate(f.next,version:"0.1.1",commit:String(repeating:"b",count:40),trust:trust)
    }
    try FileManager.default.setAttributes([.posixPermissions:path.isEmpty || item.hasDirectoryPath ? 0o755 : 0o644], ofItemAtPath:item.path)
    try await f.verifier().validate(f.next,version:"0.1.1",commit:String(repeating:"b",count:40),trust:trust)
}

@Test func aFifoInsideTheCandidateIsRefused() async throws {
    let f = try BundleFixture(); defer { f.remove() }
    let trust = try await f.verifier().installed(at:f.old)
    #expect(mkfifo(f.next.appendingPathComponent("Contents/Resources/pipe").path, 0o644) == 0)
    await #expect(throws:BundleInstallProblem.invalidBundle) {
        try await f.verifier().validate(f.next,version:"0.1.1",commit:String(repeating:"b",count:40),trust:trust)
    }
}

@Test func theInstalledAppsSigningRuleDecidesWhoMaySignTheUpdateNotItsOwnCertificate() async throws {
    let f = try BundleFixture(); defer { f.remove() }
    try f.alter("RoleBandUpdateRequirement",value:"trusted rule",app:f.old)
    let trust = try await f.verifier().installed(at:f.old)
    #expect(trust.signingRule == "trusted rule")
    // A different certificate is accepted when it meets the rule: how a change of signer ships.
    try await f.verifier(problem:"certificate").validate(f.next,version:"0.1.1",commit:String(repeating:"b",count:40),trust:trust)
    // A refused signer reads as a new signer only under an Apple Developer ID; any other is a failed check,
    // so a stolen release key with a self-made certificate never asks for a hand install.
    for (problem, refusal) in [("rule-fails", BundleInstallProblem.signature), ("rule-fails developer-id", .signer)] {
        await #expect(throws:refusal) {
            try await f.verifier(problem:problem).validate(f.next,version:"0.1.1",commit:String(repeating:"b",count:40),trust:trust)
        }
    }
    // Without a rule, the certificate itself must match, under the same reading of a refusal.
    let unruled = try await f.verifier().installed(at:f.next)
    #expect(unruled.signingRule == nil)
    for (problem, refusal) in [("certificate", BundleInstallProblem.signature), ("certificate developer-id", .signer)] {
        await #expect(throws:refusal) {
            try await f.verifier(problem:problem).validate(f.next,version:"0.1.1",commit:String(repeating:"b",count:40),
                                                           trust:try await f.verifier().installed(at:f.old).withoutRule)
        }
    }
}

@Test func anUpdateThatFailsItsOwnSigningRuleIsRefusedSoItCannotBlockTheUpdatesAfterIt() async throws {
    let f = try BundleFixture(); defer { f.remove() }
    try f.alter("RoleBandUpdateRequirement",value:"trusted rule",app:f.old)
    let trust = try await f.verifier().installed(at:f.old)
    try f.alter("RoleBandUpdateRequirement",value:"own rule")
    try await f.verifier().validate(f.next,version:"0.1.1",commit:String(repeating:"b",count:40),trust:trust)
    await #expect(throws:BundleInstallProblem.invalidBundle) {
        try await f.verifier(problem:"own-rule-unmet").validate(f.next,version:"0.1.1",commit:String(repeating:"b",count:40),trust:trust)
    }
    // An installed app without a rule still refuses an update that fails the rule it brings.
    await #expect(throws:BundleInstallProblem.invalidBundle) {
        try await f.verifier(problem:"own-rule-unmet").validate(f.next,version:"0.1.1",commit:String(repeating:"b",count:40),
                                                                trust:trust.withoutRule)
    }
}

@Test(arguments:["unmet","empty","not-text"])
func aSigningRuleTheAppItselfFailsOrThatIsMalformedIsRefused(problem:String) async throws {
    let f = try BundleFixture(); defer { f.remove() }
    try f.alter("RoleBandUpdateRequirement",value: problem == "unmet" ? "other rule" : problem == "empty" ? "" : 7 as Any,app:f.old)
    await #expect(throws:BundleInstallProblem.invalidBundle) { _ = try await f.verifier().installed(at:f.old) }
}

@Test(arguments:["version","commit","key","candidate","dirty","runtime-version","external-runtime","certificate","signature","architecture",
                 "no-feed","unknown-feed","other-roleband-feed"])
func incompatibleOrUntrustedBundlesNeverBecomeStagedUpdates(problem:String) async throws {
    let f = try BundleFixture(); defer { f.remove() }
    let trust = try await f.verifier().installed(at:f.old)
    switch problem {
    case "version": try f.alter("RoleBandVersion",value:"0.1.2")
    case "commit": try f.alter("RoleBandSourceRevision",value:String(repeating:"c",count:40))
    case "key": try f.alter("RoleBandUpdatePublicKey",value:Data(repeating:2,count:32).base64EncodedString())
    case "candidate": try f.alter("RoleBandReleaseCandidate",value:true)
    case "dirty": try f.alter("RoleBandSourceDirty",value:true)
    case "no-feed": try f.alter("RoleBandUpdateFeed",value:NSNull())
    case "unknown-feed": try f.alter("RoleBandUpdateFeed",value:"other/repository")
    case "other-roleband-feed": try f.alter("RoleBandUpdateFeed",value:"roleband/roleband-mac-update-trial")
    case "runtime-version": try Data("{\"version\":\"0.1.0\"}".utf8).write(to:f.next.appendingPathComponent("Contents/Resources/engine/release.json"))
    case "external-runtime":
        let file = f.next.appendingPathComponent("Contents/Resources/python/bin/python3.12")
        try FileManager.default.removeItem(at:file)
        try FileManager.default.createSymbolicLink(at:file,withDestinationURL:URL(fileURLWithPath:"/usr/bin/true"))
    default:break
    }
    await #expect(throws:(any Error).self) {
        try await f.verifier(problem:problem).validate(f.next,version:"0.1.1",commit:String(repeating:"b",count:40),trust:trust)
    }
}

private final class MountEvents: @unchecked Sendable {
    private let lock = NSLock()
    private var events: [[String]] = []
    func add(_ value: [String]) { lock.withLock { events.append(value) } }
    var calls: [[String]] { lock.withLock { events } }
}

@Test(arguments: ["normal", "bad-image", "wrong-commit", "attach-error", "cancel", "detach-error"])
func imageStagingChecksBeforeCopyingAndDetachesAfterSuccessOrFailure(problem: String) async throws {
    let f = try BundleFixture(); defer { f.remove() }
    let image = f.root.appendingPathComponent("image.dmg")
    let bytes = Data("Authenticated disk image fixture".utf8)
    try bytes.write(to: image)
    let artifact = VerifiedArtifact(version: "0.1.1", commit: String(repeating: "b", count: 40), imageName: "image.dmg",
        bytes: Int64(bytes.count), sha256: SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined())
    if problem == "bad-image" { try Data("corrupt".utf8).write(to: image) }
    if problem == "wrong-commit" { try f.alter("RoleBandSourceRevision", value: String(repeating: "c", count: 40)) }
    let calls = MountEvents()
    let stager = UpdateImageStager(command: { _, arguments in
        calls.add(arguments)
        if arguments.first == "attach" {
            if problem == "attach-error" { return CommandOutput(text: "", exitCode: 1) }
            let index = try #require(arguments.firstIndex(of: "-mountpoint"))
            let mount = URL(fileURLWithPath: arguments[index + 1])
            try FileManager.default.copyItem(at: f.next, to: mount.appendingPathComponent("RoleBand.app"))
            if problem == "cancel" { throw CancellationError() }
            return CommandOutput(text: "", exitCode: 0)
        }
        return CommandOutput(text: "", exitCode: problem == "detach-error" && !arguments.contains("-force") ? 1 : 0)
    }, verifier: f.verifier())
    let destination = f.root.appendingPathComponent("cache/staged.app")
    let download = DownloadedUpdate(artifact: artifact, image: image)
    if problem == "normal" {
        let trust = try await stager.stage(download, installed: f.old, destination: destination)
        #expect(trust.version == "0.1.0")
        #expect(FileManager.default.fileExists(atPath: destination.appendingPathComponent("Contents/Info.plist").path))
    } else {
        await #expect(throws: (any Error).self) { _ = try await stager.stage(download, installed: f.old, destination: destination) }
    }
    if problem == "bad-image" { #expect(calls.calls.isEmpty) }
    else { #expect(calls.calls.contains { $0.first == "detach" }) }
    if problem == "detach-error" { #expect(calls.calls.contains { $0.contains("-force") }) }
    let info = try PropertyListSerialization.propertyList(from: Data(contentsOf: f.old.appendingPathComponent("Contents/Info.plist")), format: nil) as! [String: Any]
    #expect(info["RoleBandVersion"] as? String == "0.1.0")
}

@Test(.enabled(if: ProcessInfo.processInfo.environment["ROLEBAND_UPDATE_TEST_ROOT"] != nil,
               "Requires locally test-signed update app and disk-image fixtures"))
func aRealSignedDiskImageStagesWithoutChangingTheInstalledApp() async throws {
    let fixture = URL(fileURLWithPath: try #require(ProcessInfo.processInfo.environment["ROLEBAND_UPDATE_TEST_ROOT"]))
    let old = fixture.appendingPathComponent("old.app")
    let image = fixture.appendingPathComponent("RoleBand-0.1.1-macOS-arm64.dmg")
    let bytes = try Data(contentsOf: image)
    let artifact = VerifiedArtifact(version: "0.1.1", commit: String(repeating: "b", count: 40), imageName: image.lastPathComponent,
        bytes: Int64(bytes.count), sha256: SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined())
    let destination = fixture.appendingPathComponent("stage-" + UUID().uuidString + "/RoleBand.app")
    defer { try? FileManager.default.removeItem(at: destination.deletingLastPathComponent()) }
    let trust = try await UpdateImageStager().stage(DownloadedUpdate(artifact: artifact, image: image),
                                                   installed: old, destination: destination)
    #expect(trust.version == "0.1.0")
    let staged = try await UpdateBundleVerifier().installed(at: destination)
    #expect(staged.version == "0.1.1" && staged.commit == artifact.commit)
    #expect(try await UpdateBundleVerifier().installed(at: old).version == "0.1.0")
}
