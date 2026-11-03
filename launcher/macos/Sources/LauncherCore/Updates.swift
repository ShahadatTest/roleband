import Foundation

public enum ReleaseFiles {
    /// Every file of a release starts with this, as `Tools/release.py` names them.
    public static func prefix(_ version: String) -> String { "RoleBand-\(version)-macOS-arm64" }
    /// What an install reads: the image, its checksum, the metadata and their signature.
    public static func all(_ version: String) -> Set<String> { Set([".dmg", ".sha256", ".json", ".sig"].map { prefix(version) + $0 }) }
}

public struct OfferedRelease: Sendable, Equatable {
    public let version: String
    public let notes: String?
    public let page: URL
    /// `Tools/release.py attach` uploads the files to a release that is already published, so the
    /// newest release can have none or only some of them for a while.
    public let filesReady: Bool
    public let published: Date?

    /// The signed "Before you update" notice, which makes the release read-first: the offer opens the
    /// notes with it above them. It comes only from the release's verified metadata, never from the
    /// notes, which are not signed.
    public private(set) var beforeYouUpdate: String?

    public func signed(notice: String?) -> Self {
        var release = self
        release.beforeYouUpdate = notice
        return release
    }
    public static func decode(_ data: Data, from repository: UpdateRepository) throws -> Self {
        struct Asset: Decodable {
            let name: String
            let state: String?
        }
        struct Reply: Decodable {
            let tag_name: String
            let html_url: String
            let body: String?
            let published_at: String?
            let draft: Bool
            let prerelease: Bool
            let assets: [Asset]?
        }
        guard data.count <= 262144, let reply = try? JSONDecoder().decode(Reply.self, from: data),
              !reply.draft, !reply.prerelease else { throw UpdateProblem.invalidResponse }
        let version = reply.tag_name.hasPrefix("v") ? String(reply.tag_name.dropFirst()) : reply.tag_name
        guard ReleaseVersion(version) != nil, !version.contains("-"),
              reply.html_url == "https://github.com/\(repository.rawValue)/releases/tag/" + reply.tag_name,
              let page = URL(string: reply.html_url), (reply.body?.utf8.count ?? 0) <= 65536 else {
            throw UpdateProblem.invalidResponse
        }
        let uploaded = Set((reply.assets ?? []).filter { $0.state == "uploaded" }.map(\.name))
        return Self(version: version, notes: reply.body, page: page, filesReady: ReleaseFiles.all(version).isSubset(of: uploaded),
                    published: reply.published_at.flatMap { ISO8601DateFormatter().date(from: $0) })
    }
}

public enum UpdateProblem: Error, Sendable {
    case unavailable, invalidResponse, rateLimited(until: Date)
}

private final class UpdateSessionDelegate: NSObject, URLSessionTaskDelegate, Sendable {
    func urlSession(_ session: URLSession, task: URLSessionTask,
                    willPerformHTTPRedirection response: HTTPURLResponse, newRequest request: URLRequest,
                    completionHandler: @escaping @Sendable (URLRequest?) -> Void) { completionHandler(nil) }
    func urlSession(_ session: URLSession, task: URLSessionTask, didReceive challenge: URLAuthenticationChallenge,
                    completionHandler: @escaping @Sendable (URLSession.AuthChallengeDisposition, URLCredential?) -> Void) {
        completionHandler(challenge.protectionSpace.authenticationMethod == NSURLAuthenticationMethodServerTrust
                          ? .performDefaultHandling : .cancelAuthenticationChallenge, nil)
    }
}

public enum UpdateClient {
    public static func endpoint(_ repository: UpdateRepository) -> URL {
        URL(string: "https://api.github.com/repos/\(repository.rawValue)/releases/latest")!
    }
    public static func request(_ repository: UpdateRepository) -> URLRequest {
        var request = URLRequest(url: endpoint(repository), cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 10)
        request.setValue("application/vnd.github+json", forHTTPHeaderField: "Accept")
        request.setValue("2026-03-10", forHTTPHeaderField: "X-GitHub-Api-Version")
        request.setValue("RoleBand-Launcher", forHTTPHeaderField: "User-Agent")
        request.httpShouldHandleCookies = false
        return request
    }
    public static func validate(_ response: HTTPURLResponse, from repository: UpdateRepository, now: Date) throws {
        guard response.url == endpoint(repository) else { throw UpdateProblem.invalidResponse }
        if response.statusCode == 403 || response.statusCode == 429 {
            let retry = response.value(forHTTPHeaderField: "Retry-After").flatMap(Double.init) ?? 60
            let reset = response.value(forHTTPHeaderField: "X-RateLimit-Remaining") == "0"
                ? response.value(forHTTPHeaderField: "X-RateLimit-Reset").flatMap(Double.init) ?? 0 : 0
            let delay = retry.isFinite ? max(60, retry) : 60
            let resetDate = reset.isFinite ? Date(timeIntervalSince1970: reset) : now
            throw UpdateProblem.rateLimited(until: max(now.addingTimeInterval(delay), resetDate))
        }
        guard response.statusCode == 200 else { throw UpdateProblem.unavailable }
        guard response.expectedContentLength <= 262144 else { throw UpdateProblem.invalidResponse }
    }
    public static func read() async throws -> Data {
        guard let repository = UpdateRepository.stamped() else { throw UpdateProblem.unavailable }
        return try await read(from: repository, configuration: .ephemeral)
    }
    static func read(from repository: UpdateRepository, configuration config: URLSessionConfiguration) async throws -> Data {
        config.timeoutIntervalForRequest = 10
        config.timeoutIntervalForResource = 15
        config.urlCache = nil
        config.httpCookieStorage = nil
        config.urlCredentialStorage = nil
        let session = URLSession(configuration: config, delegate: UpdateSessionDelegate(), delegateQueue: nil)
        defer { session.invalidateAndCancel() }
        try Task.checkCancellation()
        let (bytes, response) = try await session.bytes(for: request(repository))
        guard let response = response as? HTTPURLResponse else { throw UpdateProblem.invalidResponse }
        try validate(response, from: repository, now: Date())
        var data = Data()
        for try await byte in bytes {
            try Task.checkCancellation()
            guard data.count < 262144 else { throw UpdateProblem.invalidResponse }
            data.append(byte)
        }
        _ = try OfferedRelease.decode(data, from: repository)
        return data
    }
}
