import Foundation
import Testing
@testable import LauncherCore

private struct OwnedBundleFixture {
    let root: URL
    let app: URL
    let resources: URL
    let bundle: Bundle

    init(metadata: [String: Any] = [:], removing: String? = nil) throws {
        root = URL(fileURLWithPath: "/private/tmp/owned identity É 引号 \(UUID().uuidString)")
        app = root.appendingPathComponent("Applications/RoleBand.app")
        resources = app.appendingPathComponent("Contents/Resources")
        try FileManager.default.createDirectory(at: resources, withIntermediateDirectories: true)
        var info: [String: Any] = ["CFBundleIdentifier": "com.roleband.launcher", "CFBundlePackageType": "APPL",
                                 "CFBundleShortVersionString": "0.1.0", "RoleBandVersion": "0.1.0-beta.2+build.4",
                                 "RoleBandPackagedEngine": true]
        info.merge(metadata) { _, right in right }
        if let removing { info.removeValue(forKey: removing) }
        try PropertyListSerialization.data(fromPropertyList: info, format: .xml, options: 0)
            .write(to: app.appendingPathComponent("Contents/Info.plist"))
        bundle = try #require(Bundle(url: app))
    }

    func remove() { try? FileManager.default.removeItem(at: root) }
}

private func pythonIdentity(_ resources: URL) async throws -> String {
    let code = "import hashlib,os,sys; from pathlib import Path; print(hashlib.sha256(os.fsencode(Path(sys.argv[1]).resolve())).hexdigest()[:24])"
    let result = try await CommandRunner.run(executable: URL(fileURLWithPath: "/usr/bin/python3"),
                                             arguments: ["-I", "-c", code, resources.path])
    #expect(result.exitCode == 0)
    return result.text.trimmingCharacters(in: .whitespacesAndNewlines)
}

@Test func ownedIdentityMatchesPythonForSpacedUnicodeAndPrivateTmpPaths() async throws {
    let fixture = try OwnedBundleFixture()
    defer { fixture.remove() }
    let installation = try Installation.owned(bundle: fixture.bundle)
    let expected = try await pythonIdentity(fixture.resources)
    #expect(installation.instance == expected)
    #expect(installation.product == "roleband" && installation.format == 1)
    #expect(installation.version == "0.1.0-beta.2+build.4")
    #expect(installation.apiOrigin == "http://127.0.0.1:8010")
    #expect(try installation.target().url.absoluteString == "http://127.0.0.1:8010/api/status")
    #expect(try BrowserRoute.radar.url(for: installation).absoluteString == "http://127.0.0.1:8010/")
    #expect(try BrowserRoute.newRoles.url(for: installation).absoluteString == "http://127.0.0.1:8010/?lens=new")
}

@Test func symlinkAliasesAndPortOverridesKeepTheSameOwnedInstance() async throws {
    let fixture = try OwnedBundleFixture()
    defer { fixture.remove() }
    let alias = fixture.root.appendingPathComponent("RoleBand alias.app")
    try FileManager.default.createSymbolicLink(at: alias, withDestinationURL: fixture.app)
    let aliased = try #require(Bundle(url: alias))
    let original = try Installation.owned(bundle: fixture.bundle)
    let alternative = try Installation.owned(bundle: aliased, port: 58271)
    let expected = try await pythonIdentity(fixture.resources)
    #expect(alternative.instance == original.instance)
    #expect(alternative.instance == expected)
    #expect(alternative.apiOrigin == "http://127.0.0.1:58271")
}

@Test func anotherBundleLocationCannotPassAsTheOwnedStatusTarget() async throws {
    let first = try OwnedBundleFixture()
    defer { first.remove() }
    let second = try OwnedBundleFixture()
    defer { second.remove() }
    let expected = try Installation.owned(bundle: first.bundle)
    let other = try Installation.owned(bundle: second.bundle)
    #expect(expected.instance != other.instance)
    var identity = try JSONSerialization.jsonObject(with: JSONEncoder().encode(other)) as! [String: Any]
    identity["status"] = ["observed_at": "2026-10-29T12:00:00Z", "activity": "idle", "attention": [], "model": "ready"]
    let reply = try JSONSerialization.data(withJSONObject: ["db": "ok", "launcher": identity])
    #expect(throws: ConnectionProblem.identityMismatch) {
        try StatusClient.decode(reply, status: 200, installation: expected)
    }
}

@Test(arguments: ["missing-packaged", "false-packaged", "missing-version", "empty-version", "bad-version", "foreign-bundle", "missing-resources"])
func ownedIdentityRefusesSourceShellsAndIncompleteBundleMetadata(problem: String) throws {
    var metadata: [String: Any] = [:]
    var removing: String?
    switch problem {
    case "missing-packaged": removing = "RoleBandPackagedEngine"
    case "false-packaged": metadata["RoleBandPackagedEngine"] = false
    case "missing-version": removing = "RoleBandVersion"
    case "empty-version": metadata["RoleBandVersion"] = ""
    case "bad-version": metadata["RoleBandVersion"] = "0.1.0\n"
    case "foreign-bundle": metadata["CFBundleIdentifier"] = "com.example.other"
    default: break
    }
    let fixture = try OwnedBundleFixture(metadata: metadata, removing: removing)
    defer { fixture.remove() }
    if problem == "missing-resources" { try FileManager.default.removeItem(at: fixture.resources) }
    #expect(throws: ConnectionProblem.invalidInstallation) { try Installation.owned(bundle: fixture.bundle) }
}

@Test(arguments: [-1, 0, 65536, Int.max])
func ownedIdentityRefusesPortsOutsideTheLoopbackPortRange(port: Int) throws {
    let fixture = try OwnedBundleFixture()
    defer { fixture.remove() }
    #expect(throws: ConnectionProblem.invalidInstallation) { try Installation.owned(bundle: fixture.bundle, port: port) }
}

@Test func ownedHostConfigurationUsesItsBundleAndWritesNoDiscoveryRegistration() async throws {
    let fixture = try OwnedBundleFixture()
    defer { fixture.remove() }
    let home = fixture.root.appendingPathComponent("home")
    let configuration = try HostConfiguration(bundle: fixture.bundle, home: home, port: 58271)
    let expected = try await pythonIdentity(fixture.resources)
    #expect(configuration.resources == fixture.bundle.resourceURL)
    #expect(configuration.installation.instance == expected)
    #expect(configuration.port == 58271)
    #expect(configuration.environment(token: "fixture")["ROLEBAND_API_PORT"] == "58271")
    #expect(configuration.pgdata.path == home.appendingPathComponent(".roleband/db").path)
    #expect(!FileManager.default.fileExists(atPath: home.path))
}
