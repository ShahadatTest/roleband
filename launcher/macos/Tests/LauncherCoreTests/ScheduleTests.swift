import Foundation
import Testing
@testable import LauncherCore

@Test(arguments: PauseAction.allCases)
func pauseAndResumeChangeOnlyThePauseChoiceAndUseTheMacTimezone(action: PauseAction) async throws {
    let server = try LocalEngineFixture(action == .resume ? "paused" : "ready")
    let state = try await ScheduleClient.perform(action, installation: server.installation,
                                               source: .registration(server.registration), timezone: "Europe/Stockholm")
    #expect(state.isPaused() == (action != .resume))
    let requests = try server.requests()
    #expect(requests.count == 1)
    let sent = try #require(requests.first)
    #expect(sent["method"] == "PUT")
    let url = try #require(URLComponents(string: sent["path"]!))
    #expect(url.path == "/api/schedule/plan")
    #expect(url.queryItems == [URLQueryItem(name: "tz", value: "Europe/Stockholm")])
    #expect(try JSONDecoder().decode([String: String].self, from: Data(sent["body"]!.utf8)) == ["pause": action.rawValue])
    #expect(sent["origin"] == server.installation.apiOrigin)
    #expect(sent["content_type"] == "application/json")
}

@Test(arguments: ["schedule-invalid", "schedule-disabled", "schedule-mismatch", "schedule-replacement", "paused"])
func unknownDisabledChangedOrAlreadyPausedSchedulesPreventPauseWrites(mode: String) async throws {
    let server = try LocalEngineFixture(mode)
    await #expect(throws: (any Error).self) {
        try await ScheduleClient.perform(.tomorrow, installation: server.installation,
                                         source: .registration(server.registration), timezone: "Europe/Stockholm")
    }
    #expect(try server.requests().isEmpty)
}

@Test func aResumeThatHasAlreadyHappenedDoesNotSendAnotherWrite() async throws {
    let server = try LocalEngineFixture("ready")
    await #expect(throws: ControlProblem.stateChanged) {
        try await ScheduleClient.perform(.resume, installation: server.installation,
                                         source: .registration(server.registration), timezone: "UTC")
    }
    #expect(try server.requests().isEmpty)
}

@Test(arguments: ["held", "scheduled", "manual"])
func pausingFutureWorkDoesNotStopAnActiveScanOrRequireRemovingAnotherHold(mode: String) async throws {
    let server = try LocalEngineFixture(mode)
    _ = try await ScheduleClient.perform(.hour, installation: server.installation,
                                         source: .registration(server.registration), timezone: "UTC")
    let status = try await StatusClient.read(server.installation)
    if mode != "held" { #expect(status.presentation.activity == .scanning) }
    if mode == "manual" { #expect(status.scanAction == .stop) }
    #expect(try server.requests().allSatisfy { $0["method"] == "PUT" })
}

@Test(arguments: ["schedule-refused", "schedule-redirect", "schedule-uncertain"])
func scheduleRefusalsRedirectsAndUnconfirmedPausesAreNotSuccessAndNeverRepeatWrites(mode: String) async throws {
    let server = try LocalEngineFixture(mode)
    await #expect(throws: (any Error).self) {
        try await ScheduleClient.perform(.hour, installation: server.installation,
                                         source: .registration(server.registration), timezone: "UTC")
    }
    #expect(try server.requests().count == 1)
}

@Test func aLargeExistingRosterDoesNotBreakTheSmallPlanRead() async throws {
    let server = try LocalEngineFixture("schedule-large")
    let status = try await StatusClient.read(server.installation)
    let plan = try await ScheduleClient.read(status, source: .registration(server.registration), timezone: "UTC")
    #expect(plan.enabled && !plan.isPaused())
    #expect(try server.requests().isEmpty)
}

@Test func aTimeZoneWithAPlusSignReachesTheEngineAsWritten() async throws {
    let server = try LocalEngineFixture("ready")
    let status = try await StatusClient.read(server.installation)
    _ = try await ScheduleClient.read(status, source: .registration(server.registration), timezone: "Etc/GMT+5")
    let reads = try String(contentsOf: server.root.appendingPathComponent("reads.jsonl"), encoding: .utf8)
        .split(separator: "\n").map { try JSONSerialization.jsonObject(with: Data($0.utf8)) as! [String: Any] }
    let schedule = try #require(reads.first { ($0["path"] as? String)?.hasPrefix("/api/schedule") == true })
    #expect(schedule["tz"] as? [String] == ["Etc/GMT+5"])
}

@Test func pauseStateRequiresExplicitValidFactsAndExpiresAtItsActualDeadline() throws {
    let state = try ScheduleState.decode(Data(#"{"generated_at":"2026-10-28T00:00:00.123456+00:00","enabled":true,"plan":{"enabled":true,"paused_until":"2026-10-28T08:00:00+02:00"}}"#.utf8))
    let deadline = try #require(state.pausedUntil)
    #expect(state.isPaused(at: deadline.addingTimeInterval(-1)))
    #expect(!state.isPaused(at: deadline))
    for json in [#"{"generated_at":"2026-10-28T00:00:00Z","enabled":true,"plan":{"enabled":true}}"#,
                 #"{"generated_at":"2026-10-28T00:00:00Z","enabled":true,"plan":{"enabled":true,"paused_until":"yesterday"}}"#,
                 #"{"enabled":true,"plan":{"enabled":true,"paused_until":null}}"#,
                 #"{"generated_at":"2026-10-28T00:00:00Z","plan":{"enabled":true,"paused_until":null}}"#] {
        #expect(throws: ConnectionProblem.invalidResponse) { try ScheduleState.decode(Data(json.utf8)) }
    }
    #expect(throws: ConnectionProblem.invalidResponse) { try ScheduleState.decode(Data(repeating: 32, count: 4194305)) }
}

@Test func theSchedulerSwitchSaysWhetherScansStartAndThePlanSaysWhetherTheyPause() throws {
    func state(scheduler: Bool, plan: Bool) throws -> ScheduleState {
        try ScheduleState.decode(Data(#"{"generated_at":"2026-10-28T00:00:00Z","enabled":\#(scheduler),"plan":{"enabled":\#(plan),"paused_until":null}}"#.utf8))
    }
    let off = try state(scheduler: false, plan: true)
    #expect(!off.enabled && !off.pausable)
    let timers = try state(scheduler: true, plan: false)
    #expect(timers.enabled && !timers.pausable)
    let plan = try state(scheduler: true, plan: true)
    #expect(plan.enabled && plan.pausable)
}
