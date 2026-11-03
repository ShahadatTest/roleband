import Foundation

public struct EnginePreparation: Codable, Equatable, Sendable {
    public let database: String
    public let model: String
    public let service: String
    public let downloadedBytes: Int64
    public let totalBytes: Int64
    public let tier: String?
    public let reason: String?
    public let format: Int

    enum CodingKeys: String, CodingKey {
        case database, model, service, tier, reason, format
        case downloadedBytes = "downloaded_bytes", totalBytes = "total_bytes"
    }

    public var ready: Bool { database == "ready" && service == "ready" }
    public var failed: Bool { database == "failed" || service == "failed" }
    public var modelComplete: Bool { model == "ready" || model == "unused" }
    public var fraction: Double { totalBytes > 0 ? Double(downloadedBytes) / Double(totalBytes) : 0 }
}

public struct EngineHealth: Sendable {
    public let preparation: EnginePreparation?
    /// The engine version that answered.
    public let version: String?
    public var ready: Bool { preparation?.ready ?? true }
    public var failed: Bool { preparation?.failed ?? false }
    public init(preparation: EnginePreparation? = nil, version: String? = nil) {
        self.preparation = preparation; self.version = version
    }
}

public enum EngineHealthClient {
    public static func decode(_ data: Data, status: Int, installation: Installation) throws -> EngineHealth {
        struct Reply: Decodable {
            let status: String
            let launcher: Installation
            let preparation: EnginePreparation?
        }
        _ = try installation.target()
        guard status == 200, data.count <= 16384,
              let reply = try? JSONDecoder().decode(Reply.self, from: data), reply.status == "ok" else {
            throw ConnectionProblem.invalidResponse
        }
        guard reply.launcher.product == installation.product, reply.launcher.instance == installation.instance,
              reply.launcher.apiOrigin == installation.apiOrigin, reply.launcher.format == installation.format else {
            throw ConnectionProblem.identityMismatch
        }
        guard let progress = reply.preparation, progress.format == 1, progress.downloadedBytes >= 0,
              progress.totalBytes >= progress.downloadedBytes,
              ["waiting", "creating", "ready", "failed"].contains(progress.database),
              ["waiting", "downloading", "verifying", "ready", "unused", "failed"].contains(progress.model),
              ["starting", "ready", "failed"].contains(progress.service) else { throw ConnectionProblem.invalidResponse }
        return EngineHealth(preparation: reply.preparation, version: reply.launcher.version)
    }

    public static func read(_ installation: Installation) async throws -> EngineHealth {
        let target = try installation.target()
        let url = target.pageURL.appendingPathComponent("api/launcher-health")
        let data = try await LocalHTTP.read(URLRequest(url: url), limit: 16384)
        return try decode(data, status: 200, installation: installation)
    }
}
