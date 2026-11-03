import Darwin
import Foundation

public enum DownloadProblem: Error, Sendable {
    case invalidSource, response, unsafeCache, alreadyDownloading
    /// The server's image is not the size the signed metadata names, so it is not the signed release.
    case wrongSize
    case insufficientSpace(required: Int64)
}

public struct DownloadProgress: Sendable, Equatable {
    public enum Phase: Sendable { case metadata, downloading, offline, verifying, ready }
    public let phase: Phase
    public let received: Int64
    public let total: Int64
}

public struct DownloadedUpdate: Sendable {
    public let artifact: VerifiedArtifact
    public let image: URL
}

public enum UpdateRepository: String, Sendable {
    case production = "roleband/roleband"

    /// The feed a sealed app was built for. Sealing stamps it and the app never reads it from a setting.
    /// An app without the stamp follows production; an app stamped with any other repository follows nothing.
    public static func stamped(in bundle: Bundle = .main) -> Self? {
        guard let value = bundle.object(forInfoDictionaryKey: "RoleBandUpdateFeed") else { return .production }
        return (value as? String).flatMap(Self.init(rawValue:))
    }

    public func releaseURL(version: String) throws -> URL {
        guard ReleaseVersion(version) != nil else { throw DownloadProblem.invalidSource }
        return URL(string: "https://github.com/\(rawValue)/releases/download/v\(version)/")!
    }
}

struct AssetOrigin: Sendable {
    let base: URL
    let loopback: Bool

    func permits(_ url: URL) -> Bool {
        guard url.user == nil, url.password == nil, url.fragment == nil else { return false }
        if loopback { return url.scheme == "http" && url.host == "127.0.0.1" && url.port == base.port }
        let prefix = base.path + (base.path.hasSuffix("/") ? "" : "/")
        return url.scheme == "https" && (url.port == nil || url.port == 443)
            && (url.host == "release-assets.githubusercontent.com" ||
                (url.host == "github.com" && url.path.hasPrefix(prefix)))
    }
}

private final class AssetTransfer: NSObject, URLSessionDataDelegate, @unchecked Sendable {
    private let lock = NSLock()
    private var continuation: CheckedContinuation<Data, Error>?
    private var task: URLSessionDataTask?
    private var session: URLSession?
    private var cancelled = false
    private var finished = false
    private var body = Data()
    private var received: Int64
    private var redirects = 0
    private let file: FileHandle?
    private let origin: AssetOrigin
    private let maximum: Int64
    private let exact: Bool
    private let offset: Int64
    private let report: @Sendable (Int64) -> Void

    init(file: FileHandle?, origin: AssetOrigin, maximum: Int64, exact: Bool, offset: Int64,
         report: @escaping @Sendable (Int64) -> Void) {
        self.file = file; self.origin = origin; self.maximum = maximum; self.exact = exact
        self.offset = offset; self.received = offset; self.report = report
    }

    func read(_ url: URL) async throws -> Data {
        guard origin.permits(url) else { throw DownloadProblem.invalidSource }
        return try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { continuation in
                lock.lock()
                if cancelled { lock.unlock(); continuation.resume(throwing: CancellationError()); return }
                self.continuation = continuation
                let config = URLSessionConfiguration.ephemeral
                config.urlCache = nil; config.httpCookieStorage = nil; config.urlCredentialStorage = nil
                config.timeoutIntervalForRequest = 60; config.timeoutIntervalForResource = 3600
                let session = URLSession(configuration: config, delegate: self, delegateQueue: nil)
                self.session = session
                var request = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData)
                request.httpShouldHandleCookies = false
                request.setValue("identity", forHTTPHeaderField: "Accept-Encoding")
                request.setValue("RoleBand-Launcher", forHTTPHeaderField: "User-Agent")
                if offset > 0 { request.setValue("bytes=\(offset)-", forHTTPHeaderField: "Range") }
                let task = session.dataTask(with: request)
                self.task = task
                lock.unlock()
                task.resume()
            }
        } onCancel: { self.cancel() }
    }

    private func cancel() {
        lock.lock(); cancelled = true; let task = task; lock.unlock()
        task?.cancel()
    }

    private func finish(_ error: Error?) {
        lock.lock()
        guard !finished else { lock.unlock(); return }
        finished = true
        let continuation = continuation; self.continuation = nil
        let session = session; self.session = nil
        let cancelled = cancelled
        lock.unlock()
        session?.invalidateAndCancel()
        if cancelled { continuation?.resume(throwing: CancellationError()) }
        else if let error { continuation?.resume(throwing: error) }
        else { continuation?.resume(returning: body) }
    }

    private var active: Bool { lock.lock(); defer { lock.unlock() }; return !finished }

    func urlSession(_ session: URLSession, task: URLSessionTask,
                    willPerformHTTPRedirection response: HTTPURLResponse, newRequest request: URLRequest,
                    completionHandler: @escaping @Sendable (URLRequest?) -> Void) {
        redirects += 1
        guard active, redirects <= 5, let url = request.url, origin.permits(url) else {
            completionHandler(nil); finish(DownloadProblem.invalidSource); return
        }
        var clean = URLRequest(url: url)
        clean.httpShouldHandleCookies = false
        clean.setValue("identity", forHTTPHeaderField: "Accept-Encoding")
        clean.setValue("RoleBand-Launcher", forHTTPHeaderField: "User-Agent")
        if offset > 0 { clean.setValue("bytes=\(offset)-", forHTTPHeaderField: "Range") }
        completionHandler(clean)
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didReceive challenge: URLAuthenticationChallenge,
                    completionHandler: @escaping @Sendable (URLSession.AuthChallengeDisposition, URLCredential?) -> Void) {
        completionHandler(challenge.protectionSpace.authenticationMethod == NSURLAuthenticationMethodServerTrust
                          ? .performDefaultHandling : .cancelAuthenticationChallenge, nil)
    }

    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive response: URLResponse,
                    completionHandler: @escaping @Sendable (URLSession.ResponseDisposition) -> Void) {
        do {
            guard active else { completionHandler(.cancel); return }
            guard let response = response as? HTTPURLResponse, let url = response.url, origin.permits(url),
                  response.value(forHTTPHeaderField: "Content-Encoding").map({ $0 == "identity" }) ?? true else {
                throw DownloadProblem.response
            }
            // For the image, every size the server states is checked against the signed size: a file of
            // another size is not the signed release, whereas a broken reply is a download problem.
            if response.statusCode == 206 && offset > 0 && exact {
                let range = response.value(forHTTPHeaderField: "Content-Range") ?? ""
                guard range == "bytes \(offset)-\(maximum - 1)/\(maximum)" else {
                    throw range.hasSuffix("/\(maximum)") ? DownloadProblem.response : DownloadProblem.wrongSize
                }
            } else if response.statusCode == 200 {
                received = 0
                try file?.truncate(atOffset: 0)
                try file?.seek(toOffset: 0)
            } else if response.statusCode == 416 && offset > 0 && exact {
                // A resume inside the signed size asked for bytes past the end of a shorter file.
                throw DownloadProblem.wrongSize
            } else { throw DownloadProblem.response }
            let length = response.expectedContentLength
            if exact && length >= 0 && length != maximum - received { throw DownloadProblem.wrongSize }
            guard length <= maximum - received else { throw DownloadProblem.response }
            report(received)
            completionHandler(.allow)
        } catch { completionHandler(.cancel); finish(error) }
    }

    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive data: Data) {
        guard active else { return }
        do {
            guard Int64(data.count) <= maximum - received else { throw exact ? DownloadProblem.wrongSize : DownloadProblem.response }
            if let file { try file.write(contentsOf: data) } else { body.append(data) }
            received += Int64(data.count)
            report(received)
        } catch { finish(error) }
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        finish(error ?? (exact && received != maximum ? URLError(.networkConnectionLost) : nil))
    }
}

public actor UpdateDownloader {
    private let cache: URL
    private let pause: @Sendable () async throws -> Void
    private let available: @Sendable (URL) throws -> Int64
    private var busy = false

    public init(cache: URL) {
        self.cache = cache
        pause = { try await Task.sleep(for: .seconds(15)) }
        available = Self.capacity
    }

    init(cache: URL, pause: @escaping @Sendable () async throws -> Void,
         available: @escaping @Sendable (URL) throws -> Int64 = UpdateDownloader.capacity) {
        self.cache = cache; self.pause = pause; self.available = available
    }

    public func download(version: String, in bundle: Bundle = .main,
                         reserveBytes: Int64 = 0,
                         progress: @escaping @Sendable (DownloadProgress) -> Void) async throws -> DownloadedUpdate {
        guard let repository = UpdateRepository.stamped(in: bundle) else { throw ArtifactProblem.untrustedKey }
        let base = try repository.releaseURL(version: version)
        let publicKey = try VerifiedArtifact.installedPublicKey(in: bundle)
        let spareKey = try VerifiedArtifact.installedSpareKey(in: bundle)
        return try await download(version: version, publicKey: publicKey, spareKey: spareKey, origin: AssetOrigin(base: base, loopback: false),
                                  reserveBytes: reserveBytes, progress: progress)
    }

    /// Reads a release's signed metadata and checks it against this app's release keys, without the
    /// image: an update check offers only a release that passes, because the release listing is not signed.
    @discardableResult
    public static func authenticate(version: String, in bundle: Bundle = .main) async throws -> VerifiedArtifact {
        guard let repository = UpdateRepository.stamped(in: bundle) else { throw ArtifactProblem.untrustedKey }
        let origin = AssetOrigin(base: try repository.releaseURL(version: version), loopback: false)
        return try await authenticate(version: version, publicKey: try VerifiedArtifact.installedPublicKey(in: bundle),
                                   spareKey: try VerifiedArtifact.installedSpareKey(in: bundle), origin: origin)
    }

    static func authenticate(version: String, publicKey: Data, spareKey: Data? = nil, origin: AssetOrigin) async throws -> VerifiedArtifact {
        guard ReleaseVersion(version) != nil else { throw ArtifactProblem.untrustedKey }
        return try await signedMetadata(version: version, publicKey: publicKey, spareKey: spareKey) { name, limit in
            try await AssetTransfer(file: nil, origin: origin, maximum: limit, exact: false, offset: 0, report: { _ in })
                .read(origin.base.appendingPathComponent(name))
        }
    }

    /// Runs on the caller's actor, so the download can read through its own retrying transfer.
    private static func signedMetadata(version: String, publicKey: Data, spareKey: Data?,
                                       isolation: isolated (any Actor)? = #isolation,
                                       read: (String, Int64) async throws -> Data) async throws -> VerifiedArtifact {
        let prefix = ReleaseFiles.prefix(version)
        let checksum = try await read(prefix + ".sha256", 512)
        let manifest = try await read(prefix + ".json", 4096)
        let signature = try await read(prefix + ".sig", 64)
        return try VerifiedArtifact.authenticate(checksum: checksum, metadata: manifest, signature: signature,
                                                 publicKey: publicKey, spareKey: spareKey, version: version)
    }

    func download(version: String, publicKey: Data, spareKey: Data? = nil, origin: AssetOrigin,
                  reserveBytes: Int64 = 0,
                  progress: @escaping @Sendable (DownloadProgress) -> Void) async throws -> DownloadedUpdate {
        guard !busy else { throw DownloadProblem.alreadyDownloading }
        guard ReleaseVersion(version) != nil, publicKey.count == 32, reserveBytes >= 0 else { throw ArtifactProblem.untrustedKey }
        busy = true
        defer { busy = false }
        let folder = cache.appendingPathComponent("update-" + version)
        try privateDirectory(cache); try privateDirectory(folder)
        let descriptor = open(folder.appendingPathComponent("download.lock").path, O_CREAT | O_RDWR | O_CLOEXEC | O_NOFOLLOW, 0o600)
        guard descriptor >= 0 else { throw DownloadProblem.unsafeCache }
        defer { flock(descriptor, LOCK_UN); close(descriptor) }
        var lockInfo = stat()
        guard fstat(descriptor, &lockInfo) == 0, lockInfo.st_mode & S_IFMT == S_IFREG,
              lockInfo.st_uid == getuid(), lockInfo.st_mode & 0o077 == 0 else { throw DownloadProblem.unsafeCache }
        guard flock(descriptor, LOCK_EX | LOCK_NB) == 0 else { throw DownloadProblem.alreadyDownloading }
        removeOtherDownloads(keeping: folder.lastPathComponent)
        progress(DownloadProgress(phase: .metadata, received: 0, total: 0))
        let artifact = try await Self.signedMetadata(version: version, publicKey: publicKey, spareKey: spareKey) { name, limit in
            try await retry(progress: progress, received: { 0 }, total: 0) {
                progress(DownloadProgress(phase: .metadata, received: 0, total: 0))
                return try await AssetTransfer(file: nil, origin: origin, maximum: limit, exact: false, offset: 0, report: { _ in })
                    .read(origin.base.appendingPathComponent(name))
            }
        }
        let image = folder.appendingPathComponent(artifact.imageName)
        let part = folder.appendingPathComponent(artifact.imageName + ".part")
        if FileManager.default.fileExists(atPath: image.path) {
            do {
                try artifact.verifyImage(at: image)
                progress(DownloadProgress(phase: .ready, received: artifact.bytes, total: artifact.bytes))
                return DownloadedUpdate(artifact: artifact, image: image)
            } catch is CancellationError { throw CancellationError() }
            catch { try FileManager.default.removeItem(at: image) }
        }
        let fd = open(part.path, O_CREAT | O_RDWR | O_NOFOLLOW | O_CLOEXEC | O_NONBLOCK, 0o600)
        guard fd >= 0 else { throw DownloadProblem.unsafeCache }
        let file = FileHandle(fileDescriptor: fd, closeOnDealloc: true)
        defer { try? file.close() }
        var info = stat()
        guard fstat(fd, &info) == 0, info.st_mode & S_IFMT == S_IFREG, info.st_uid == getuid(),
              info.st_mode & 0o077 == 0, info.st_size <= artifact.bytes else { throw DownloadProblem.unsafeCache }
        let (required, overflow) = (artifact.bytes - info.st_size).addingReportingOverflow(reserveBytes)
        guard !overflow else { throw ArtifactProblem.invalidMetadata }
        guard try available(folder) >= required else { throw DownloadProblem.insufficientSpace(required: required) }
        do {
            if info.st_size < artifact.bytes {
                _ = try await retry(progress: progress, received: { Int64((try? file.offset()) ?? 0) }, total: artifact.bytes) {
                    let offset = Int64(try file.seekToEnd())
                    return try await AssetTransfer(file: file, origin: origin, maximum: artifact.bytes, exact: true, offset: offset) {
                        progress(DownloadProgress(phase: .downloading, received: $0, total: artifact.bytes))
                    }.read(origin.base.appendingPathComponent(artifact.imageName))
                }
            }
            try Task.checkCancellation()
            progress(DownloadProgress(phase: .verifying, received: artifact.bytes, total: artifact.bytes))
            try file.synchronize()
            try artifact.verifyImage(at: part)
            try FileManager.default.moveItem(at: part, to: image)
        } catch is CancellationError { throw CancellationError() }
        catch {
            if error is ArtifactProblem || error is DownloadProblem { try? FileManager.default.removeItem(at: part) }
            throw error
        }
        progress(DownloadProgress(phase: .ready, received: artifact.bytes, total: artifact.bytes))
        return DownloadedUpdate(artifact: artifact, image: image)
    }

    /// Timeouts in a row, with no byte arriving between them, before the download gives up.
    static let stallLimit = 8

    /// Waits out a lost connection for as long as it lasts, so the download resumes where it stopped.
    /// A server that keeps answering too slowly is not a lost connection: after `stallLimit` timeouts
    /// with no progress the error ends the download, which the person can retry.
    func retry<T: Sendable>(progress: @escaping @Sendable (DownloadProgress) -> Void,
                            received: () -> Int64, total: Int64,
                            operation: () async throws -> T) async throws -> T {
        var stalls = 0
        var last = received()
        while true {
            try Task.checkCancellation()
            do { return try await operation() }
            catch let error as URLError where [.notConnectedToInternet, .networkConnectionLost, .timedOut,
                .cannotFindHost, .cannotConnectToHost, .dnsLookupFailed].contains(error.code) {
                let now = received()
                stalls = error.code == .timedOut && now == last ? stalls + 1 : 0
                last = now
                if stalls >= Self.stallLimit { throw error }
                progress(DownloadProgress(phase: .offline, received: now, total: total))
                try await pause()
            }
        }
    }

    /// Deletes the cache's other update folders. A staged update never reads its image again, so the
    /// release being downloaded is the only one worth keeping. A folder whose download lock another
    /// process holds stays, and a link is never followed.
    private func removeOtherDownloads(keeping current: String) {
        guard let names = try? FileManager.default.contentsOfDirectory(atPath: cache.path) else { return }
        for name in names where name != current && name.hasPrefix("update-") && ReleaseVersion(String(name.dropFirst(7))) != nil {
            let folder = cache.appendingPathComponent(name)
            var info = stat()
            guard lstat(folder.path, &info) == 0, info.st_mode & S_IFMT == S_IFDIR, info.st_uid == getuid() else { continue }
            let lock = open(folder.appendingPathComponent("download.lock").path, O_RDWR | O_CLOEXEC | O_NOFOLLOW)
            if lock >= 0 {
                defer { close(lock) }
                guard flock(lock, LOCK_EX | LOCK_NB) == 0 else { continue }
            }
            try? FileManager.default.removeItem(at: folder)
        }
    }

    private func privateDirectory(_ path: URL) throws {
        try FileManager.default.createDirectory(at: path, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        let info = try FileManager.default.attributesOfItem(atPath: path.path)
        guard info[.type] as? FileAttributeType == .typeDirectory,
              (info[.ownerAccountID] as? NSNumber)?.uint32Value == getuid(),
              (info[.posixPermissions] as? NSNumber)?.intValue ?? 0o777 == 0o700 else { throw DownloadProblem.unsafeCache }
    }

    private static func capacity(_ path: URL) throws -> Int64 {
        let info = try path.resourceValues(forKeys: [.volumeAvailableCapacityForImportantUsageKey])
        guard let capacity = info.volumeAvailableCapacityForImportantUsage else { throw DownloadProblem.unsafeCache }
        return capacity
    }
}
