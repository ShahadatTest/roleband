import Foundation
import Testing
@testable import LauncherCore

@Test func failuresSayWhatTheyMeanAndACancellationIsNotOne() {
    #expect(UpdateFailure.classify(DownloadProblem.insufficientSpace(required: 5_600_000_000)) == .space(required: 5_600_000_000))
    #expect(UpdateFailure.classify(ArtifactProblem.invalidSignature) == .check)
    #expect(UpdateFailure.classify(ArtifactProblem.invalidImage) == .check)
    #expect(UpdateFailure.classify(BundleInstallProblem.signature) == .check)
    #expect(UpdateFailure.classify(BundleInstallProblem.signer) == .signer)
    #expect(UpdateFailure.classify(DownloadProblem.response) == .download)
    #expect(UpdateFailure.classify(DownloadProblem.wrongSize) == .check)
    #expect(UpdateFailure.classify(URLError(.badServerResponse)) == .download)
    #expect(UpdateFailure.classify(CancellationError()) == nil)
}

@Test func theSpaceAnUpdateReservesCountsTheDatabaseAndTheAppButNotLinkedFiles() throws {
    let root = FileManager.default.temporaryDirectory.appendingPathComponent("update-reserve-" + UUID().uuidString)
    defer { try? FileManager.default.removeItem(at: root) }
    let home = root.appendingPathComponent("home")
    let app = home.appendingPathComponent("Applications/RoleBand.app")
    let outside = root.appendingPathComponent("large")
    try FileManager.default.createDirectory(at: HomeLayout(home).database, withIntermediateDirectories: true)
    try FileManager.default.createDirectory(at: app.appendingPathComponent("Contents"), withIntermediateDirectories: true)
    try Data(count: 400_000).write(to: HomeLayout(home).database.appendingPathComponent("base"))
    try Data(count: 200_000).write(to: app.appendingPathComponent("Contents/engine"))
    try Data(count: 3_000_000).write(to: outside)
    try FileManager.default.createSymbolicLink(at: HomeLayout(home).database.appendingPathComponent("linked"), withDestinationURL: outside)

    #expect(try DiskUsage.bytes(at: root.appendingPathComponent("missing")) == 0)
    let database = try DiskUsage.bytes(at: HomeLayout(home).database)
    let installed = try DiskUsage.bytes(at: app)
    #expect(database >= 400_000 && database < 1_000_000)
    #expect(installed >= 200_000 && installed < 1_000_000)
    #expect(try DiskUsage.updateReserve(installed: app, home: home) == database + installed)
}
