import Foundation
import Security
import Testing
@testable import LauncherCore

/// A tiny app signed without a certificate, its identifier standing in for a signer.
private func signedApp(_ folder: URL, identifier: String, rule: String? = nil) throws -> URL {
    let app = folder.appendingPathComponent(identifier + ".app")
    try FileManager.default.createDirectory(at: app.appendingPathComponent("Contents/MacOS"), withIntermediateDirectories: true)
    try FileManager.default.copyItem(at: URL(fileURLWithPath: "/usr/bin/true"), to: app.appendingPathComponent("Contents/MacOS/RoleBandLauncher"))
    var info: [String: Any] = ["CFBundleExecutable": "RoleBandLauncher", "CFBundleIdentifier": identifier]
    if let rule { info["RoleBandUpdateRequirement"] = rule }
    try PropertyListSerialization.data(fromPropertyList: info, format: .xml, options: 0)
        .write(to: app.appendingPathComponent("Contents/Info.plist"))
    let sign = Process()
    sign.executableURL = URL(fileURLWithPath: "/usr/bin/codesign")
    sign.arguments = ["--force", "--sign", "-", "--identifier", identifier, app.path]
    sign.standardError = FileHandle.nullDevice
    try sign.run(); sign.waitUntilExit()
    #expect(sign.terminationStatus == 0)
    return app
}

@Test func anOlderCopyRunsOnlyWhenItMeetsTheRunningAppsSigningRuleAndIsIntact() throws {
    let folder = FileManager.default.temporaryDirectory.appendingPathComponent("code-signing-" + UUID().uuidString)
    defer { try? FileManager.default.removeItem(at: folder) }
    let candidate = try signedApp(folder, identifier: "com.example.previous")
    let trusting = try signedApp(folder, identifier: "com.example.running", rule: "identifier \"com.example.previous\"")
    let other = try signedApp(folder, identifier: "com.example.other", rule: "identifier \"com.example.someone\"")
    let unruled = try signedApp(folder, identifier: "com.example.plain")
    #expect(CodeSigning.meetsRule(candidate, of: trusting))
    #expect(!CodeSigning.meetsRule(candidate, of: other))
    // An app with no certificate and no stamped rule states no rule, so nothing meets it.
    #expect(CodeSigning.rule(of: unruled) == nil)
    #expect(!CodeSigning.meetsRule(candidate, of: unruled))
    try Data("changed".utf8).write(to: candidate.appendingPathComponent("Contents/Info.plist"))
    #expect(!CodeSigning.meetsRule(candidate, of: trusting))
}

@Test func theDeveloperIDRuleIsValidAndRefusesSelfMadeAndAppleSystemSignatures() throws {
    var requirement: SecRequirement?
    #expect(SecRequirementCreateWithString(UpdateBundleVerifier.developerID as CFString, [], &requirement) == errSecSuccess)
    let folder = FileManager.default.temporaryDirectory.appendingPathComponent("developer-id-" + UUID().uuidString)
    defer { try? FileManager.default.removeItem(at: folder) }
    for app in [try signedApp(folder, identifier: "com.example.self-made"), URL(fileURLWithPath: "/usr/bin/true")] {
        let check = Process()
        check.executableURL = URL(fileURLWithPath: "/usr/bin/codesign")
        check.arguments = ["--verify", "-R", "=" + UpdateBundleVerifier.developerID, app.path]
        check.standardError = FileHandle.nullDevice
        try check.run(); check.waitUntilExit()
        // 3: the signature is valid but does not meet the requirement.
        #expect(check.terminationStatus == 3, "\(app.lastPathComponent)")
    }
}

@Test func recoveryStartsTheOlderCopyOnlyAfterItsSignatureIsAccepted() throws {
    let home = FileManager.default.temporaryDirectory.appendingPathComponent("recovery-" + UUID().uuidString)
    defer { try? FileManager.default.removeItem(at: home) }
    let paths = UpdateTransactionPaths(installed: home.appendingPathComponent("Applications/RoleBand.app"), home: home, id: UUID())
    let fallback = URL(fileURLWithPath: "/running/RoleBand.app/Contents/MacOS/RoleBandLauncher")
    let previous = paths.previous.appendingPathComponent("Contents/MacOS/RoleBandLauncher")
    var asked = 0
    #expect(UpdateHelperProcess.executable(for: paths, fallback: fallback, trusted: { _, _ in asked += 1; return true }) == fallback)
    #expect(asked == 0)
    try FileManager.default.createDirectory(at: previous.deletingLastPathComponent(), withIntermediateDirectories: true)
    try FileManager.default.copyItem(at: URL(fileURLWithPath: "/usr/bin/true"), to: previous)
    #expect(UpdateHelperProcess.executable(for: paths, fallback: fallback, trusted: { app, _ in app == paths.previous }) == previous)
    #expect(UpdateHelperProcess.executable(for: paths, fallback: fallback, trusted: { _, _ in false }) == fallback)
    // The real check: an unsigned program planted at that path is never started.
    #expect(UpdateHelperProcess.executable(for: paths, fallback: fallback) == fallback)
}
