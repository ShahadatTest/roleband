import Darwin
import Foundation
import Testing
@testable import LauncherCore

struct LaunchModeFixture {
    let home: URL
    let installed: URL
    init() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        home = root.appendingPathComponent("home")
        installed = home.appendingPathComponent("Applications/RoleBand.app")
        try FileManager.default.createDirectory(at: installed.appendingPathComponent("Contents"), withIntermediateDirectories: true)
        try FileManager.default.createDirectory(at: home.appendingPathComponent(".roleband/db"), withIntermediateDirectories: true)
    }
    func app(_ folder: URL, identifier: String = "com.roleband.launcher") throws -> URL {
        try FileManager.default.createDirectory(at: folder.appendingPathComponent("Contents"), withIntermediateDirectories: true)
        try PropertyListSerialization.data(fromPropertyList: ["CFBundleIdentifier": identifier], format: .xml, options: 0)
            .write(to: folder.appendingPathComponent("Contents/Info.plist"))
        return folder.appendingPathComponent("Contents/Resources/python/lib/python3.12/site-packages/pixeltable_pgserver/pginstall/bin/postgres")
    }
    func write(_ relative: String, _ text: String = "{}") throws {
        let file = home.appendingPathComponent(relative)
        try FileManager.default.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data(text.utf8).write(to: file)
    }
    func serverRuns(_ pid: pid_t) throws { try write(".roleband/db/postmaster.pid", "\(pid)\n/db\n") }
}

func exitedProcess() throws -> pid_t {
    let process = Process()
    process.executableURL = URL(fileURLWithPath: "/usr/bin/true")
    try process.run()
    process.reap()
    return process.processIdentifier
}

@Test func anAppOutsideApplicationsStartsNothingEvenBesideASourceInstall() throws {
    let fixture = try LaunchModeFixture()
    try fixture.write(".roleband/launcher/installation.json")
    for location in ["Downloads/RoleBand.app", "private/var/folders/xy/T/AppTranslocation/AB12/d/RoleBand.app"] {
        let bundle = fixture.home.appendingPathComponent(location)
        #expect(LaunchMode.decide(bundle: bundle, home: fixture.home) == .moveToApplications)
    }
}

@Test func aSourceInstallsRegistrationOrItemMeansAttachWhetherOrNotItRuns() throws {
    for evidence in [".roleband/launcher/installation.json", "Library/LaunchAgents/com.roleband.plist"] {
        let fixture = try LaunchModeFixture()
        #expect(LaunchMode.decide(bundle: fixture.installed, home: fixture.home) == .owned(leftover: nil))
        try fixture.write(evidence)
        #expect(LaunchMode.decide(bundle: fixture.installed, home: fixture.home) == .attach)
    }
}

@Test func aBrokenLinkToARegistrationStillCountsAsASourceInstall() throws {
    let fixture = try LaunchModeFixture()
    let link = fixture.home.appendingPathComponent(".roleband/launcher/installation.json")
    try FileManager.default.createDirectory(at: link.deletingLastPathComponent(), withIntermediateDirectories: true)
    try FileManager.default.createSymbolicLink(atPath: link.path, withDestinationPath: "/nonexistent/installation.json")
    #expect(LaunchMode.decide(bundle: fixture.installed, home: fixture.home) == .attach)
}

@Test func aRunningServerFromACheckoutMeansAttachAndOneFromTheAppIsALeftover() throws {
    let fixture = try LaunchModeFixture()
    let live = getpid()
    try fixture.serverRuns(live)
    let checkout = URL(fileURLWithPath: "/Users/someone/RoleBand/backend/.venv/lib/python3.12/site-packages/pixeltable_pgserver/pginstall/bin/postgres")
    #expect(LaunchMode.decide(bundle: fixture.installed, home: fixture.home, executable: { _ in checkout }) == .attach)
    let ownServer = try fixture.app(fixture.installed)
    #expect(LaunchMode.decide(bundle: fixture.installed, home: fixture.home, executable: { $0 == live ? ownServer : nil }) == .owned(leftover: live))
    let movedAside = try fixture.app(fixture.home.appendingPathComponent("Library/Caches/RoleBand/old/RoleBand.app"))
    #expect(LaunchMode.decide(bundle: fixture.installed, home: fixture.home, executable: { _ in movedAside }) == .owned(leftover: live))
    let otherApp = try fixture.app(fixture.home.appendingPathComponent("Applications/Other.app"), identifier: "com.example.other")
    #expect(LaunchMode.decide(bundle: fixture.installed, home: fixture.home, executable: { _ in otherApp }) == .attach)
}

@Test func aStaleServerFileOrAReusedProcessNumberDoesNotBlockTheAppsOwnEngine() throws {
    let fixture = try LaunchModeFixture()
    try fixture.serverRuns(try exitedProcess())
    #expect(LaunchMode.decide(bundle: fixture.installed, home: fixture.home, executable: { _ in nil }) == .owned(leftover: nil))
    try fixture.serverRuns(getpid())
    #expect(LaunchMode.decide(bundle: fixture.installed, home: fixture.home) == .owned(leftover: nil))
    try fixture.write(".roleband/db/postmaster.pid", "not a process\n")
    #expect(LaunchMode.decide(bundle: fixture.installed, home: fixture.home) == .owned(leftover: nil))
}

@Test func onlyADatabaseTheAppRecordedAsItsOwnIsTheAppsToRun() throws {
    let fixture = try LaunchModeFixture()
    #expect(LaunchMode.decide(bundle: fixture.installed, home: fixture.home) == .owned(leftover: nil))
    try fixture.write(".roleband/db/PG_VERSION", "17\n")
    #expect(LaunchMode.decide(bundle: fixture.installed, home: fixture.home) == .databaseOwnedElsewhere)
    for record in [#"{"owner": "source"}"#, "not json", "[]", #"{"owner": 1}"#] {
        try fixture.write(".roleband/db.owner.json", record)
        #expect(LaunchMode.decide(bundle: fixture.installed, home: fixture.home) == .databaseOwnedElsewhere)
    }
    try fixture.write(".roleband/db.owner.json", #"{"owner": "app"}"#)
    #expect(LaunchMode.decide(bundle: fixture.installed, home: fixture.home) == .owned(leftover: nil))
    try fixture.write(".roleband/launcher/installation.json")
    #expect(LaunchMode.decide(bundle: fixture.installed, home: fixture.home) == .attach)
}

@Test func aRecordWithoutADatabaseStillBelongsToItsMaker() throws {
    let fixture = try LaunchModeFixture()
    try fixture.write(".roleband/db.owner.json", #"{"owner": "source"}"#)
    #expect(LaunchMode.decide(bundle: fixture.installed, home: fixture.home) == .databaseOwnedElsewhere)
}

@Test func aCheckoutServerOnAnUnrecordedDatabaseMeansAttach() throws {
    let fixture = try LaunchModeFixture()
    try fixture.write(".roleband/db/PG_VERSION", "17\n")
    try fixture.serverRuns(getpid())
    let checkout = URL(fileURLWithPath: "/Users/someone/RoleBand/backend/.venv/lib/python3.12/site-packages/pixeltable_pgserver/pginstall/bin/postgres")
    #expect(LaunchMode.decide(bundle: fixture.installed, home: fixture.home, executable: { _ in checkout }) == .attach)
}
