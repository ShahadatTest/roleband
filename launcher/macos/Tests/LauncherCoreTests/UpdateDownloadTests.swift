import CryptoKit
import Foundation
import Testing
@testable import LauncherCore

private final class ProgressLog: @unchecked Sendable {
    private let lock = NSLock()
    private var values: [DownloadProgress] = []
    let acknowledgement: URL?
    init(acknowledgement: URL? = nil) { self.acknowledgement = acknowledgement }
    func add(_ value: DownloadProgress) {
        lock.withLock { values.append(value) }
        if value.phase == .downloading, value.received >= 65536, let acknowledgement {
            try? Data().write(to: acknowledgement)
        }
    }
    var all: [DownloadProgress] { lock.withLock { values } }
}

private struct DownloadServer {
    let root: URL
    let process: Process
    let origin: AssetOrigin
    let image: Data
    let key: Data
    var cache: URL { root.appendingPathComponent("cache") }
    var imageName: String { "RoleBand-0.1.1-macOS-arm64.dmg" }
    var part: URL { cache.appendingPathComponent("update-0.1.1/" + imageName + ".part") }

    init(mode: String) async throws {
        root = FileManager.default.temporaryDirectory.appendingPathComponent("update-download-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        let fixture = URL(fileURLWithPath: #filePath).deletingLastPathComponent().appendingPathComponent("Fixtures/update-artifact.json")
        var values = try JSONDecoder().decode([String: Data].self, from: Data(contentsOf: fixture))
        image = Data(repeating: 71, count: 1 << 20)
        let signer = Curve25519.Signing.PrivateKey()
        key = signer.publicKey.rawRepresentation
        var manifest = try JSONSerialization.jsonObject(with: #require(values["metadata"])) as! [String: Any]
        let sha = SHA256.hash(data: image).map { String(format: "%02x", $0) }.joined()
        manifest["sha256"] = sha; manifest["bytes"] = image.count
        manifest["release_key_sha256"] = SHA256.hash(data: key).map { String(format: "%02x", $0) }.joined()
        values["metadata"] = try JSONSerialization.data(withJSONObject: manifest)
        values["checksum"] = Data("\(sha)  RoleBand-0.1.1-macOS-arm64.dmg\n".utf8)
        values["signature"] = try signer.signature(for: values["checksum"]! + values["metadata"]!)
        values["image"] = image
        try JSONEncoder().encode(values).write(to: root.appendingPathComponent("fixture.json"))
        try Data(mode.utf8).write(to: root.appendingPathComponent("mode"))
        let script = #"""
import base64, http.server, json, pathlib, socket, sys, threading, time
root = pathlib.Path(sys.argv[1])
fixture = {k:base64.b64decode(v) for k,v in json.loads((root/'fixture.json').read_text()).items()}
class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def do_GET(self):
        mode=(root/'mode').read_text()
        with (root/'requests.jsonl').open('a') as log:
            log.write(json.dumps({'path':self.path,'headers':dict(self.headers)})+'\n')
        if mode=='offline':
            self.connection.shutdown(socket.SHUT_RDWR);self.connection.close();return
        name=self.path.rsplit('/',1)[-1]
        kind='image' if name.endswith('.dmg') else 'checksum' if name.endswith('.sha256') else 'signature' if name.endswith('.sig') else 'metadata'
        body=fixture[kind]
        if mode=='bad-signature' and kind=='signature': body=bytes([body[0]^1])+body[1:]
        if mode=='metadata-overflow' and kind=='metadata': body=b'x'*4097
        if mode=='redirect':
            self.send_response(302);self.send_header('Location','http://localhost:%s/trap'%self.server.server_port);self.end_headers();return
        if mode=='redirect-loop' or (mode=='allowed-redirect' and not self.path.startswith('/assets/')):
            self.send_response(302)
            target=self.path if mode=='redirect-loop' else '/assets/'+name
            self.send_header('Location','http://127.0.0.1:%s%s'%(self.server.server_port,target));self.end_headers();return
        if kind=='image' and mode=='corrupt': body=bytes([body[0]^1])+body[1:]
        if kind=='image' and mode in ('oversized','foreign-range'): body+=b'x'
        if kind=='image' and mode=='short': body=body[:-1]
        if kind=='image' and mode=='truncated': body=body[:65536]
        offset=int(self.headers.get('Range','bytes=0-')[6:].split('-')[0])
        resume=kind=='image' and offset>0 and mode!='ignored-range'
        if resume and offset>=len(body):
            self.send_response(416);self.send_header('Content-Range',f'bytes */{len(body)}');self.end_headers();return
        self.send_response(206 if resume else 200)
        if resume:
            start=offset+1 if mode=='wrong-range' else offset
            self.send_header('Content-Range',f'bytes {start}-{len(body)-1}/{len(body)}')
            body=body[offset:]
        self.send_header('Content-Length',str(len(body)));self.end_headers()
        if kind=='image' and mode in ('interrupt','slow') and not (root/'cut').exists():
            self.wfile.write(body[:65536]);self.wfile.flush();(root/'cut').write_text('sent')
            deadline=time.monotonic()+5
            while not (root/'ack').exists() and time.monotonic()<deadline: threading.Event().wait(.01)
            if mode=='slow': threading.Event().wait()
            self.connection.shutdown(socket.SHUT_RDWR);self.connection.close();return
        self.wfile.write(body)
server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
(root/'port').write_text(str(server.server_port))
server.serve_forever()
"""#
        process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
        process.arguments = ["-I", "-c", script, root.path]
        let log = root.appendingPathComponent("server.log")
        FileManager.default.createFile(atPath: log.path, contents: Data())
        process.standardOutput = try FileHandle(forWritingTo: log)
        process.standardError = process.standardOutput
        try process.run()
        let deadline = ContinuousClock.now.advanced(by: .seconds(5))
        let portPath = root.appendingPathComponent("port")
        // The file exists before the server has written the port into it, so wait for a number.
        var port: String? { (try? String(contentsOf: portPath, encoding: .utf8)).flatMap { Int($0) != nil ? $0 : nil } }
        while port == nil && ContinuousClock.now < deadline {
            try await Task.sleep(for: .milliseconds(10))
        }
        guard let port else {
            process.stopAndReap()
            throw DownloadProblem.response
        }
        origin = AssetOrigin(base: URL(string: "http://127.0.0.1:\(port)/")!, loopback: true)
    }
    func stop() {
        process.stopAndReap()
        try? FileManager.default.removeItem(at: root)
    }
    func requests() throws -> [[String: Any]] {
        try String(contentsOf: root.appendingPathComponent("requests.jsonl"), encoding: .utf8)
            .split(separator: "\n").map { try JSONSerialization.jsonObject(with: Data($0.utf8)) as! [String: Any] }
    }
    func seedPartial() throws {
        try FileManager.default.createDirectory(at: part.deletingLastPathComponent(), withIntermediateDirectories: true,
                                                attributes: [.posixPermissions: 0o700])
        try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: cache.path)
        try image.prefix(65536).write(to: part)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: part.path)
    }
}

private final class Attempts: @unchecked Sendable {
    private let lock = NSLock()
    private var count = 0
    func next() -> Int { lock.withLock { count += 1; return count } }
    var made: Int { lock.withLock { count } }
}

@Test func aServerThatKeepsTimingOutWithNoProgressEndsTheDownloadButALostNetworkIsWaitedOut() async throws {
    let downloader = UpdateDownloader(cache: FileManager.default.temporaryDirectory, pause: {})
    let stalled = Attempts()
    await #expect(throws: URLError.self) {
        _ = try await downloader.retry(progress: { _ in }, received: { 0 }, total: 10) { () async throws -> Int in
            _ = stalled.next(); throw URLError(.timedOut)
        }
    }
    #expect(stalled.made == UpdateDownloader.stallLimit)
    // Timeouts that each bring a few more bytes are a slow link, not a stalled server.
    let slow = Attempts()
    let finished = try await downloader.retry(progress: { _ in }, received: { Int64(slow.made) }, total: 10) { () async throws -> Int in
        let attempt = slow.next(); if attempt < 3 * UpdateDownloader.stallLimit { throw URLError(.timedOut) }; return attempt
    }
    #expect(finished == 3 * UpdateDownloader.stallLimit)
    let offline = Attempts()
    let resumed = try await downloader.retry(progress: { _ in }, received: { 0 }, total: 10) { () async throws -> Int in
        let attempt = offline.next(); if attempt < 5 * UpdateDownloader.stallLimit { throw URLError(.notConnectedToInternet) }; return attempt
    }
    #expect(resumed == 5 * UpdateDownloader.stallLimit)
}

@Test(arguments: ["normal", "interrupt", "resume", "ignored-range", "complete-partial", "allowed-redirect"])
func signedImageDownloadsResumeRealPartialBytesAndOnlyPublishVerifiedContent(mode: String) async throws {
    let server = try await DownloadServer(mode: mode)
    defer { server.stop() }
    if ["resume", "ignored-range", "complete-partial"].contains(mode) { try server.seedPartial() }
    if mode == "complete-partial" { try server.image.write(to: server.part) }
    let progress = ProgressLog(acknowledgement: server.root.appendingPathComponent("ack"))
    let downloader = UpdateDownloader(cache: server.cache, pause: {})
    let result = try await downloader.download(version: "0.1.1", publicKey: server.key, origin: server.origin, progress: progress.add)
    #expect(try Data(contentsOf: result.image) == server.image)
    #expect(!FileManager.default.fileExists(atPath: server.part.path))
    #expect(progress.all.last?.phase == .ready)
    let requests = try server.requests()
    let images = requests.filter { ($0["path"] as? String)?.hasSuffix(".dmg") == true }
    if mode == "complete-partial" { #expect(images.isEmpty) }
    if ["interrupt", "resume", "ignored-range"].contains(mode) {
        #expect(images.contains { ($0["headers"] as? [String: String])?["Range"] == "bytes=65536-" })
    }
    if mode == "interrupt" { #expect(progress.all.contains { $0.phase == .offline && $0.received == 65536 }) }
    #expect(requests.allSatisfy {
        let headers = $0["headers"] as? [String: String] ?? [:]
        return headers["Authorization"] == nil && headers["Cookie"] == nil
    })
}

@Test(arguments: ["bad-signature", "metadata-overflow", "wrong-range", "oversized", "corrupt", "redirect", "redirect-loop"])
func downloadingNeverPublishesAnUnauthenticatedOrInvalidImage(mode: String) async throws {
    let server = try await DownloadServer(mode: mode)
    defer { server.stop() }
    if mode == "wrong-range" { try server.seedPartial() }
    let downloader = UpdateDownloader(cache: server.cache, pause: { throw CancellationError() })
    await #expect(throws: (any Error).self) {
        _ = try await downloader.download(version: "0.1.1", publicKey: server.key, origin: server.origin, progress: { _ in })
    }
    #expect(!FileManager.default.fileExists(atPath: server.part.deletingPathExtension().path))
    let requests = try server.requests()
    if ["bad-signature", "metadata-overflow", "redirect"].contains(mode) {
        #expect(!requests.contains { ($0["path"] as? String)?.hasSuffix(".dmg") == true })
    }
    #expect(!requests.contains { $0["path"] as? String == "/trap" })
    if mode == "redirect-loop" { #expect(requests.count <= 6) }
}

/// An image of another size than the signed one is not the signed release: it is refused as a failed
/// check, on the first request and without waiting for a connection, and nothing of it is kept.
/// A reply that only gets the resume range wrong stays a download problem.
@Test(arguments: ["oversized", "short", "foreign-range", "truncated", "wrong-range"])
func anImageOfAnotherSizeFailsItsCheckAtOnceButABrokenRangeIsADownloadProblem(mode: String) async throws {
    let server = try await DownloadServer(mode: mode)
    defer { server.stop() }
    if ["foreign-range", "truncated", "wrong-range"].contains(mode) { try server.seedPartial() }
    let downloader = UpdateDownloader(cache: server.cache, pause: { throw CancellationError() })
    var thrown: (any Error)?
    do { _ = try await downloader.download(version: "0.1.1", publicKey: server.key, origin: server.origin, progress: { _ in }) }
    catch { thrown = error }
    let failure = try #require(thrown)
    if mode == "wrong-range" {
        #expect(UpdateFailure.classify(failure) == .download)
    } else {
        guard case DownloadProblem.wrongSize = failure else { Issue.record("\(mode): \(failure)"); return }
        #expect(UpdateFailure.classify(failure) == .check)
    }
    #expect(!FileManager.default.fileExists(atPath: server.part.path))
    #expect(!FileManager.default.fileExists(atPath: server.part.deletingPathExtension().path))
    #expect(try server.requests().filter { ($0["path"] as? String)?.hasSuffix(".dmg") == true }.count == 1)
}

@Test func cancellingAnImageTransferKeepsItsRealPartialFileForTheNextLaunch() async throws {
    let server = try await DownloadServer(mode: "slow")
    defer { server.stop() }
    let progress = ProgressLog(acknowledgement: server.root.appendingPathComponent("ack"))
    let downloader = UpdateDownloader(cache: server.cache, pause: {})
    let task = Task { try await downloader.download(version: "0.1.1", publicKey: server.key, origin: server.origin, progress: progress.add) }
    let deadline = ContinuousClock.now.advanced(by: .seconds(5))
    while !progress.all.contains(where: { $0.phase == .downloading && $0.received > 0 }), ContinuousClock.now < deadline {
        try await Task.sleep(for: .milliseconds(10))
    }
    let competing = UpdateDownloader(cache: server.cache, pause: {})
    await #expect(throws: DownloadProblem.self) {
        _ = try await competing.download(version: "0.1.1", publicKey: server.key, origin: server.origin, progress: { _ in })
    }
    task.cancel()
    await #expect(throws: CancellationError.self) { _ = try await task.value }
    #expect(try Data(contentsOf: server.part) == server.image.prefix(65536))
    try Data("normal".utf8).write(to: server.root.appendingPathComponent("mode"))
    let result = try await downloader.download(version: "0.1.1", publicKey: server.key, origin: server.origin, progress: progress.add)
    #expect(try Data(contentsOf: result.image) == server.image)
}

@Test func metadataNetworkLossWaitsThenRecoversWithoutAnImageRequestBeforeAuthentication() async throws {
    let server = try await DownloadServer(mode: "offline")
    defer { server.stop() }
    let modeFile = server.root.appendingPathComponent("mode")
    let downloader = UpdateDownloader(cache: server.cache, pause: { try Data("normal".utf8).write(to: modeFile) })
    let progress = ProgressLog()
    let result = try await downloader.download(version: "0.1.1", publicKey: server.key, origin: server.origin, progress: progress.add)
    #expect(try Data(contentsOf: result.image) == server.image)
    #expect(progress.all.contains { $0.phase == .offline && $0.received == 0 && $0.total == 0 })
    #expect(progress.all.last?.phase == .ready)
}

@Test func productionAssetOriginsRefuseOtherRepositoriesCredentialsAndNonTLSRedirects() throws {
    let base = try UpdateRepository.production.releaseURL(version: "0.1.1")
    let origin = AssetOrigin(base: base, loopback: false)
    #expect(origin.permits(base.appendingPathComponent("image.dmg")))
    #expect(origin.permits(URL(string: "https://release-assets.githubusercontent.com/asset?token=public-test")!))
    for url in ["http://github.com/roleband/roleband/releases/download/v0.1.1/image.dmg",
                "https://github.com/other/app/releases/download/v0.1.1/image.dmg",
                "https://github.com/roleband/roleband/releases/download/v0.1.10/image.dmg",
                "https://user:password@release-assets.githubusercontent.com/image",
                "https://release-assets.githubusercontent.com.evil.invalid/image"] {
        #expect(!origin.permits(URL(string: url)!))
    }
}

@Test(arguments: [false, true])
func cachedImagesAreVerifiedAgainAndCorruptionCausesANewDownload(corrupt: Bool) async throws {
    let server = try await DownloadServer(mode: "normal")
    defer { server.stop() }
    let downloader = UpdateDownloader(cache: server.cache, pause: {})
    let first = try await downloader.download(version: "0.1.1", publicKey: server.key, origin: server.origin, progress: { _ in })
    if corrupt { try Data(repeating: 0, count: server.image.count).write(to: first.image) }
    let second = try await downloader.download(version: "0.1.1", publicKey: server.key, origin: server.origin, progress: { _ in })
    #expect(try Data(contentsOf: second.image) == server.image)
    let images = try server.requests().filter { ($0["path"] as? String)?.hasSuffix(".dmg") == true }
    #expect(images.count == (corrupt ? 2 : 1))
}

@Test func diskCapacityIncludesTheBackupReserveAndStopsBeforeTheImageRequest() async throws {
    let server = try await DownloadServer(mode: "normal")
    defer { server.stop() }
    let downloader = UpdateDownloader(cache: server.cache, pause: {}, available: { _ in Int64(server.image.count) })
    await #expect(throws: DownloadProblem.self) {
        _ = try await downloader.download(version: "0.1.1", publicKey: server.key, origin: server.origin,
                                          reserveBytes: 1, progress: { _ in })
    }
    #expect(!(try server.requests()).contains { ($0["path"] as? String)?.hasSuffix(".dmg") == true })
}

@Test func aSymlinkInThePartialFileSlotCannotWriteOrDeleteItsTarget() async throws {
    let server = try await DownloadServer(mode: "normal")
    defer { server.stop() }
    try server.seedPartial()
    try FileManager.default.removeItem(at: server.part)
    let target = server.root.appendingPathComponent("unrelated")
    let original = Data("Preserve this file".utf8)
    try original.write(to: target)
    try FileManager.default.createSymbolicLink(at: server.part, withDestinationURL: target)
    let downloader = UpdateDownloader(cache: server.cache, pause: {})
    await #expect(throws: DownloadProblem.self) {
        _ = try await downloader.download(version: "0.1.1", publicKey: server.key, origin: server.origin, progress: { _ in })
    }
    #expect(try Data(contentsOf: target) == original)
    #expect(!(try server.requests()).contains { ($0["path"] as? String)?.hasSuffix(".dmg") == true })
}

/// The check before an offer reads only the signed metadata: a genuine release passes without an image
/// request, and a forged one fails as an artifact problem, the case the offer treats as no release.
@Test(arguments: ["normal", "bad-signature", "foreign-key"])
func checkingAReleaseReadsOnlyItsSignedMetadata(mode: String) async throws {
    let server = try await DownloadServer(mode: mode == "foreign-key" ? "normal" : mode)
    defer { server.stop() }
    let key = mode == "foreign-key" ? Curve25519.Signing.PrivateKey().publicKey.rawRepresentation : server.key
    if mode == "normal" {
        let artifact = try await UpdateDownloader.authenticate(version: "0.1.1", publicKey: key, origin: server.origin)
        #expect(artifact.bytes == Int64(server.image.count))
    } else {
        await #expect(throws: ArtifactProblem.self) {
            _ = try await UpdateDownloader.authenticate(version: "0.1.1", publicKey: key, origin: server.origin)
        }
    }
    #expect(!(try server.requests()).contains { ($0["path"] as? String)?.hasSuffix(".dmg") == true })
    #expect(!FileManager.default.fileExists(atPath: server.cache.path))
}

/// Starting a download clears the other releases' folders, but never one whose download another
/// process holds, a link or what it points to, or a folder that is not a release's.
@Test func startingADownloadClearsOtherReleasesButNotAHeldOneOrALink() async throws {
    let server = try await DownloadServer(mode: "normal")
    defer { server.stop() }
    let cache = server.cache
    let manager = FileManager.default
    try manager.createDirectory(at: cache, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
    func release(_ name: String) throws -> URL {
        let folder = cache.appendingPathComponent(name)
        try manager.createDirectory(at: folder, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        try Data().write(to: folder.appendingPathComponent("download.lock"))
        try Data(count: 4096).write(to: folder.appendingPathComponent("RoleBand-image.dmg"))
        return folder
    }
    let finished = try release("update-0.1.0")
    let unlocked = cache.appendingPathComponent("update-0.0.7")
    try manager.createDirectory(at: unlocked, withIntermediateDirectories: true)
    let held = try release("update-0.0.9")
    let holder = open(held.appendingPathComponent("download.lock").path, O_RDWR)
    #expect(flock(holder, LOCK_EX | LOCK_NB) == 0)
    defer { close(holder) }
    let outside = server.root.appendingPathComponent("outside")
    try manager.createDirectory(at: outside, withIntermediateDirectories: true)
    try Data("keep".utf8).write(to: outside.appendingPathComponent("file"))
    try manager.createSymbolicLink(at: cache.appendingPathComponent("update-0.0.8"), withDestinationURL: outside)
    let notes = cache.appendingPathComponent("update-notes")
    try manager.createDirectory(at: notes, withIntermediateDirectories: true)

    let downloader = UpdateDownloader(cache: cache, pause: {})
    let result = try await downloader.download(version: "0.1.1", publicKey: server.key, origin: server.origin, progress: { _ in })
    #expect(try Data(contentsOf: result.image) == server.image)
    #expect(!manager.fileExists(atPath: finished.path))
    #expect(!manager.fileExists(atPath: unlocked.path))
    #expect(manager.fileExists(atPath: held.appendingPathComponent("RoleBand-image.dmg").path))
    #expect((try? manager.destinationOfSymbolicLink(atPath: cache.appendingPathComponent("update-0.0.8").path)) != nil)
    #expect(try Data(contentsOf: outside.appendingPathComponent("file")) == Data("keep".utf8))
    #expect(manager.fileExists(atPath: notes.path))
}
