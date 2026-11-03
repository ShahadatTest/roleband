import Foundation
import Testing
@testable import LauncherCore

@Test func releaseOrderingIsNumericAndPrereleasesDoNotOutrankStableVersions() throws {
    let ordered = ["1.0.0-alpha", "1.0.0-alpha.1", "1.0.0-alpha.beta", "1.0.0-beta", "1.0.0-beta.2", "1.0.0-beta.11", "1.0.0-rc.1", "1.0.0", "1.2.0", "1.10.0", "2.0.0"]
    for (left, right) in zip(ordered, ordered.dropFirst()) {
        #expect(try #require(ReleaseVersion(left)) < #require(ReleaseVersion(right)))
    }
    #expect(ReleaseVersion("1.0.0+one") == ReleaseVersion("1.0.0+two"))
    for invalid in ["", "v1.0.0", "1.0", "01.0.0", "1.0.0-01", "1.0.0+", "1.0.0-", "1.0.0\n", "1.0.0+<script>"] {
        #expect(ReleaseVersion(invalid) == nil)
    }
}

@Test(arguments: ["ready", "notes-missing"])
func installedNotesUseOnlyTheVerifiedLocalEngineAndExplicitEmptyNotesRemainEmpty(mode: String) async throws {
    let server = try LocalEngineFixture(mode)
    let status = try await StatusClient.read(server.installation)
    let notes = try await ReleaseClient.read(status, source: .registration(server.registration))
    #expect(notes.version == "0.1.0")
    #expect(notes.notes == nil ? mode == "notes-missing" : notes.notes!.contains("First public release."))
    #expect(try server.requests().isEmpty)
    let reads = try String(contentsOf: server.root.appendingPathComponent("reads.jsonl"), encoding: .utf8)
    #expect(!reads.contains("https://"))
}

@Test(arguments: ["notes-mismatch", "notes-version", "notes-replacement", "notes-redirect"])
func notesFromAnotherInstanceVersionRedirectOrReplacedRegistrationNeverArrive(mode: String) async throws {
    let server = try LocalEngineFixture(mode)
    let status = try await StatusClient.read(server.installation)
    await #expect(throws: (any Error).self) { try await ReleaseClient.read(status, source: .registration(server.registration)) }
    let reads = try String(contentsOf: server.root.appendingPathComponent("reads.jsonl"), encoding: .utf8)
    #expect(!reads.contains("unexpected"))
    #expect(try server.requests().isEmpty)
}
