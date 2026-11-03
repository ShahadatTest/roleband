import Foundation
import Testing
@testable import LauncherCore

private let preparationIdentity = Installation(product: "roleband", instance: "0123456789abcdef01234567",
    apiOrigin: "http://127.0.0.1:58329", version: "0.1.0", format: 1)

@Test func identityHealthReportsPreparationWithoutClaimingTheDashboardIsReady() throws {
    let data = Data(#"{"status":"ok","launcher":{"product":"roleband","instance":"0123456789abcdef01234567","api_origin":"http://127.0.0.1:58329","version":"0.1.0","format":1},"preparation":{"database":"creating","model":"waiting","service":"starting","downloaded_bytes":0,"total_bytes":0,"tier":null,"reason":null,"format":1}}"#.utf8)
    let result = try EngineHealthClient.decode(data, status: 200, installation: preparationIdentity)
    #expect(!result.ready && !result.failed)
    #expect(result.preparation?.database == "creating")
    #expect(result.version == "0.1.0")
}

@Test(arguments: ["wrong-instance", "negative-bytes", "too-many-bytes", "new-format", "redirect", "missing-state", "unknown-state"])
func preparationRefusesWrongIdentityAndImpossibleProgress(problem: String) throws {
    var identity = try JSONSerialization.jsonObject(with: JSONEncoder().encode(preparationIdentity)) as! [String: Any]
    if problem == "wrong-instance" { identity["instance"] = "aaaaaaaaaaaaaaaaaaaaaaaa" }
    let progress: [String: Any] = ["database": "ready", "model": problem == "unknown-state" ? "invented" : "downloading", "service": "ready",
        "downloaded_bytes": problem == "negative-bytes" ? -1 : problem == "too-many-bytes" ? 101 : 39,
        "total_bytes": 100, "format": problem == "new-format" ? 2 : 1]
    let state: Any = problem == "missing-state" ? NSNull() : progress
    let bytes = try JSONSerialization.data(withJSONObject: ["status": "ok", "launcher": identity, "preparation": state])
    #expect(throws: ConnectionProblem.self) {
        _ = try EngineHealthClient.decode(bytes, status: problem == "redirect" ? 302 : 200, installation: preparationIdentity)
    }
}

@Test func aModelWaitingOfflineDoesNotBlockAnOtherwiseReadyService() throws {
    let progress = EnginePreparation(database: "ready", model: "waiting", service: "ready", downloadedBytes: 312,
                                    totalBytes: 800, tier: "fp32", reason: "offline", format: 1)
    let health = EngineHealth(preparation: progress)
    #expect(health.ready && !health.failed && !progress.modelComplete)
    #expect(progress.fraction == 0.39)
}
