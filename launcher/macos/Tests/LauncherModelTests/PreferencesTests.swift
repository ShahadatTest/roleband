import Darwin
import Foundation
import Testing
@testable import RoleBandLauncher

/// cfprefsd writes named suites to the account's own folder whatever HOME says.
private let accountPreferences = URL(fileURLWithPath: String(cString: getpwuid(getuid())!.pointee.pw_dir))
    .appendingPathComponent("Library/Preferences")

@Test func scratchPreferencesKeepTheirValuesInTheTemporaryFolderAndNeverInTheAccountsPreferences() throws {
    let label = "guard-\(UUID().uuidString)"
    let preferences = UserDefaults.scratch(label)
    preferences.set("kept", forKey: "probe")
    #expect(preferences.synchronize())
    #expect(preferences.string(forKey: "probe") == "kept")
    let temporary = try FileManager.default.contentsOfDirectory(atPath: FileManager.default.temporaryDirectory.path)
    #expect(temporary.filter { $0.contains(label) }.count == 1)
    #expect(try FileManager.default.contentsOfDirectory(atPath: accountPreferences.path).filter { $0.contains(label) }.isEmpty)
}

/// A test or render that names its own suite adds a domain to ~/Library/Preferences on every run,
/// and removing the domain afterwards still leaves its file.
@Test func testsAndRendersMakePreferencesOnlyThroughTheScratchHelper() throws {
    let package = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
    let needle = "UserDefaults(" + "suiteName:"
    var named: [String] = []
    for folder in ["Sources", "Tests"] {
        let files = try #require(FileManager.default.enumerator(at: package.appendingPathComponent(folder), includingPropertiesForKeys: nil))
        for case let file as URL in files where file.pathExtension == "swift" {
            let uses = try String(contentsOf: file, encoding: .utf8).components(separatedBy: needle).count - 1
            if uses > 0 { named.append("\(file.lastPathComponent): \(uses)") }
        }
    }
    #expect(named == ["PanelPreview.swift: 1"])
}
