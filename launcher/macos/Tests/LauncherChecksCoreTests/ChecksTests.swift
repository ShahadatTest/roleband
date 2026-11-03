import Foundation
import Testing
@testable import LauncherChecksCore

@Test(arguments: ["http://127.0.0.1:18419/api/status", "http://localhost:18419/api/status", "http://[::1]:18419/api/status"])
func acceptsExplicitLoopbackTargets(raw: String) throws {
    let target = try ProbeTarget(raw)
    #expect(target.pageURL.path == "/")
    #expect(target.pageURL.port == 18419)
}

@Test(arguments: [
    "https://example.com/api/status", "http://127.0.0.1.evil.example/api/status",
    "http://user:password@127.0.0.1/api/status", "file:///api/status",
    "http://127.0.0.1/api/status?url=https://example.com", "http://127.0.0.1/api/status#other",
    "http://127.0.0.1:0/api/status", "http://127.0.0.1:65536/api/status", "http://127.0.0.1/other",
])
func refusesUnsafeOrUnexpectedTargets(raw: String) {
    #expect(throws: ProbeError.invalidTarget) { try ProbeTarget(raw) }
}
