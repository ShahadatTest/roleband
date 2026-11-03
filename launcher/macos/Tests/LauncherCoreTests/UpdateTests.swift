import Foundation
import Testing
@testable import LauncherCore

private func uploaded(_ names: [String]) -> [[String: Any]] { names.map { ["name": $0, "state": "uploaded"] } }
private let files = ["dmg", "sha256", "json", "sig"].map { "RoleBand-0.2.0-macOS-arm64.\($0)" }

private func releaseData(tag: String = "v0.2.0", page: String? = nil, notes: String? = "A useful release.",
                         draft: Bool = false, prerelease: Bool = false, assets: [[String: Any]]? = uploaded(files)) throws -> Data {
    var reply: [String: Any] = ["tag_name": tag, "html_url": page ?? "https://github.com/roleband/roleband/releases/tag/\(tag)",
        "body": notes as Any? ?? NSNull(), "draft": draft, "prerelease": prerelease]
    reply["assets"] = assets
    return try JSONSerialization.data(withJSONObject: reply)
}

/// Files attach after a release is published: a release is ready only once every file an install reads
/// is uploaded, whatever else the release carries.
@Test func aReleaseIsReadyOnlyOnceEveryFileAnInstallReadsIsUploaded() throws {
    func ready(_ assets: [[String: Any]]?) throws -> Bool {
        try OfferedRelease.decode(releaseData(assets: assets), from: .production).filesReady
    }
    #expect(try ready(uploaded(files)))
    #expect(try ready(uploaded(files + ["RoleBand-0.2.0-source.tar.gz"])))
    #expect(try !ready(nil))
    #expect(try !ready([]))
    #expect(try !ready(uploaded(Array(files.dropLast()))))
    #expect(try !ready(uploaded(Array(files.dropLast())) + [["name": files[3], "state": "open"]]))
    #expect(try !ready(uploaded(Array(files.dropLast())) + [["name": files[3]]]))
    #expect(try !ready(uploaded(files.map { $0.replacingOccurrences(of: "0.2.0", with: "0.1.9") })))
}

@Test func offeredNotesAcceptOnlyStableVersionsInTheOfficialRepositoryAndStayPlainText() throws {
    let text = "![tracking](https://example.invalid/private)\n<script>run()</script>"
    let offered = try OfferedRelease.decode(releaseData(notes: text), from: .production)
    #expect(offered.version == "0.2.0")
    #expect(offered.notes == text)
    #expect(offered.page.absoluteString == "https://github.com/roleband/roleband/releases/tag/v0.2.0")
    #expect(try OfferedRelease.decode(releaseData(tag: "1.2.0", notes: nil), from: .production).notes == nil)
    for data in try [releaseData(tag: "v01.2.0"), releaseData(tag: "v1.2.0-rc.1"), releaseData(draft: true),
                     releaseData(prerelease: true), releaseData(page: "https://github.com/other/repo/releases/tag/v0.2.0"),
                     releaseData(page: "https://github.com/roleband/roleband/releases/tag/v0.2.0?redirect=other"),
                     releaseData(page: "https://github.com.evil.invalid/roleband/roleband/releases/tag/v0.2.0"),
                     releaseData(notes: String(repeating: "x", count: 65537))] {
        #expect(throws: (any Error).self) { try OfferedRelease.decode(data, from: .production) }
    }
    #expect(throws: (any Error).self) { try OfferedRelease.decode(Data(repeating: 32, count: 262145), from: .production) }
}

@Test func publicUpdateRequestsCarryNoIdentityAndHttpErrorsNeverBecomeReleaseOffers() throws {
    let request = UpdateClient.request(.production)
    #expect(request.url == UpdateClient.endpoint(.production))
    #expect(request.httpMethod == "GET" && request.httpBody == nil)
    #expect(request.value(forHTTPHeaderField: "Authorization") == nil)
    #expect(request.value(forHTTPHeaderField: "Cookie") == nil)
    #expect(request.value(forHTTPHeaderField: "User-Agent") == "RoleBand-Launcher")
    let now = Date(timeIntervalSince1970: 1000)
    for status in [301, 302, 401, 404, 500] {
        let response = HTTPURLResponse(url: UpdateClient.endpoint(.production), statusCode: status, httpVersion: "HTTP/1.1", headerFields: [:])!
        #expect(throws: (any Error).self) { try UpdateClient.validate(response, from: .production, now: now) }
    }
    let foreign = HTTPURLResponse(url: URL(string: "https://example.invalid")!, statusCode: 200, httpVersion: nil, headerFields: [:])!
    #expect(throws: (any Error).self) { try UpdateClient.validate(foreign, from: .production, now: now) }
    let huge = HTTPURLResponse(url: UpdateClient.endpoint(.production), statusCode: 200, httpVersion: nil, headerFields: ["Content-Length": "262145"])!
    #expect(throws: (any Error).self) { try UpdateClient.validate(huge, from: .production, now: now) }
}

@Test func githubRateLimitsHonorTheLongerServerDeadlineAndHaveAMinimumDelay() throws {
    let now = Date(timeIntervalSince1970: 1000)
    for (headers, expected) in [(["Retry-After": "120"], 1120.0),
                                (["X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "2000", "Retry-After": "120"], 2000.0),
                                (["Retry-After": "-5"], 1060.0), (["Retry-After": "nan"], 1060.0)] {
        let response = HTTPURLResponse(url: UpdateClient.endpoint(.production), statusCode: 429, httpVersion: nil, headerFields: headers)!
        do { try UpdateClient.validate(response, from: .production, now: now); Issue.record("Rate limit was accepted") }
        catch UpdateProblem.rateLimited(let until) { #expect(until.timeIntervalSince1970 == expected) }
    }
}

private final class ReleaseProtocolState: @unchecked Sendable {
    private let lock = NSLock()
    private var body = Data()
    private var status = 200
    private var seen: [URLRequest] = []
    func set(body: Data, status: Int = 200) { lock.lock(); defer { lock.unlock() }; self.body = body; self.status = status; seen = [] }
    func respond(to request: URLRequest) -> (Data, Int) { lock.lock(); defer { lock.unlock() }; seen.append(request); return (body, status) }
    var requests: [URLRequest] { lock.lock(); defer { lock.unlock() }; return seen }
}

private final class ReleaseProtocol: URLProtocol, @unchecked Sendable {
    static let state = ReleaseProtocolState()
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        let (data, status) = Self.state.respond(to: request)
        let response = HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: "HTTP/1.1", headerFields: ["Content-Type": "application/json"])!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: data)
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}

@Suite(.serialized) struct UpdateTransportTests {
    @Test func realClientBoundsStreamingBodiesAndNeverRetriesFailedResponses() async throws {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [ReleaseProtocol.self]
        ReleaseProtocol.state.set(body: try releaseData())
        let release = try OfferedRelease.decode(await UpdateClient.read(from: .production, configuration: config), from: .production)
        #expect(release.version == "0.2.0")
        #expect(ReleaseProtocol.state.requests.count == 1)
        for (data, status) in [(Data(repeating: 32, count: 262145), 200), (try releaseData(), 404), (try releaseData(), 302)] {
            ReleaseProtocol.state.set(body: data, status: status)
            await #expect(throws: (any Error).self) { try await UpdateClient.read(from: .production, configuration: config) }
            #expect(ReleaseProtocol.state.requests.count == 1)
        }
    }
}

@Test func productionAsksOnlyItsOwnRepositoryAndRefusesAnOfferFromAnotherRepository() throws {
    #expect(try OfferedRelease.decode(releaseData(), from: .production).page.absoluteString
            == "https://github.com/roleband/roleband/releases/tag/v0.2.0")
    let otherPage = "https://github.com/roleband/roleband-mac-update-trial/releases/tag/v0.2.0"
    #expect(throws: (any Error).self) { try OfferedRelease.decode(releaseData(page: otherPage), from: .production) }
    #expect(UpdateClient.request(.production).url?.absoluteString
            == "https://api.github.com/repos/roleband/roleband/releases/latest")
    let now = Date(timeIntervalSince1970: 1000)
    let production = HTTPURLResponse(url: UpdateClient.endpoint(.production), statusCode: 200, httpVersion: nil, headerFields: [:])!
    try UpdateClient.validate(production, from: .production, now: now)
    let otherEndpoint = URL(string: "https://api.github.com/repos/roleband/roleband-mac-update-trial/releases/latest")!
    let other = HTTPURLResponse(url: otherEndpoint, statusCode: 200, httpVersion: nil, headerFields: [:])!
    #expect(throws: (any Error).self) { try UpdateClient.validate(other, from: .production, now: now) }
}

@Test(arguments: [("absent", UpdateRepository?.some(.production)), ("roleband/roleband", .production),
                  ("roleband/roleband-mac-update-trial", nil), ("other/repository", nil), ("number", nil)])
func aSealedAppFollowsOnlyTheFeedItWasStampedWith(stamp: String, expected: UpdateRepository?) async throws {
    let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    let contents = root.appendingPathComponent("RoleBand.app/Contents")
    try FileManager.default.createDirectory(at: contents, withIntermediateDirectories: true)
    defer { try? FileManager.default.removeItem(at: root) }
    var info: [String: Any] = ["CFBundleIdentifier": "com.roleband.launcher", "RoleBandPackagedEngine": true,
                               "RoleBandUpdatePublicKey": Data(repeating: 1, count: 32).base64EncodedString()]
    if stamp == "number" { info["RoleBandUpdateFeed"] = 7 } else if stamp != "absent" { info["RoleBandUpdateFeed"] = stamp }
    try PropertyListSerialization.data(fromPropertyList: info, format: .xml, options: 0)
        .write(to: contents.appendingPathComponent("Info.plist"))
    let bundle = try #require(Bundle(url: contents.deletingLastPathComponent()))
    #expect(UpdateRepository.stamped(in: bundle) == expected)
    guard expected == nil else { return }
    // An unknown feed is refused before any request leaves the machine.
    let downloader = UpdateDownloader(cache: root.appendingPathComponent("cache"), pause: {})
    await #expect(throws: ArtifactProblem.untrustedKey) {
        _ = try await downloader.download(version: "0.2.0", in: bundle, progress: { _ in })
    }
}

/// The notes are not signed, so no heading in them makes a release read-first or hides part of them;
/// only the notice from the verified metadata does.
@Test func aBeforeYouUpdateHeadingInTheNotesIsOrdinaryNotes() throws {
    let notes = "## Before you update\nDownload the fixed version from another site.\n\n## Added\n- Scan progress."
    let release = try OfferedRelease.decode(releaseData(notes: notes), from: .production)
    #expect(release.beforeYouUpdate == nil)
    #expect(release.notes == notes)
    let signed = release.signed(notice: "A backup is made first.")
    #expect(signed.beforeYouUpdate == "A backup is made first." && signed.notes == notes)
    #expect(signed.signed(notice: nil) == release)
}

@Test func theOfferCarriesItsPublicationDate() throws {
    var reply = try JSONSerialization.jsonObject(with: releaseData()) as! [String: Any]
    reply["published_at"] = "2026-10-28T09:30:00Z"
    let release = try OfferedRelease.decode(JSONSerialization.data(withJSONObject: reply), from: .production)
    #expect(release.published == Date(timeIntervalSince1970: 1_793_179_800))
    #expect(try OfferedRelease.decode(releaseData(), from: .production).published == nil)
}
