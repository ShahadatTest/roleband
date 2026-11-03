import Combine
import Foundation
import Testing
@testable import LauncherCore
@testable import RoleBandLauncher

private enum Injected: Error { case handOff }

/// A release server and stager the test steps through: it reports progress, can hold the download
/// open, and records every call the installer makes.
private actor FakeRelease {
    var downloads: [(version: String, reserve: Int64)] = []
    var prepared = 0
    var discarded: [String] = []
    var downloadFailure: (any Error)?
    var prepareFailure: (any Error)?
    var progress: [DownloadProgress] = []
    var ignoresCancellation = false
    private var holding = false
    private var held: CheckedContinuation<Void, Never>?
    private var reports: [@Sendable (DownloadProgress) -> Void] = []

    func set(downloadFailure: (any Error)?) { self.downloadFailure = downloadFailure }
    func set(prepareFailure: (any Error)?) { self.prepareFailure = prepareFailure }
    func set(progress: [DownloadProgress]) { self.progress = progress }
    func hold() { holding = true }
    func release() { holding = false; held?.resume(); held = nil }
    func set(ignoresCancellation: Bool) { self.ignoresCancellation = ignoresCancellation }
    /// Reports through the given download's callback, the latest one by default.
    func send(_ value: DownloadProgress, download: Int? = nil) { reports[download ?? reports.count - 1](value) }
    var isHeld: Bool { held != nil }
    func discard(_ version: String) { discarded.append(version) }

    func download(_ version: String, _ reserve: Int64, _ report: @escaping @Sendable (DownloadProgress) -> Void) async throws -> DownloadedUpdate {
        downloads.append((version, reserve))
        reports.append(report)
        for value in progress { report(value) }
        if holding { await withCheckedContinuation { held = $0 } }
        if !ignoresCancellation { try Task.checkCancellation() }
        if let downloadFailure { throw downloadFailure }
        let artifact = VerifiedArtifact(version: version, commit: String(repeating: "b", count: 40),
                                        imageName: "RoleBand-\(version)-macOS-arm64.dmg", bytes: 280_000_000,
                                        sha256: String(repeating: "d", count: 64))
        return DownloadedUpdate(artifact: artifact, image: URL(fileURLWithPath: "/nonexistent/" + artifact.imageName))
    }

    func prepare(_ home: URL) throws -> UpdatePlan {
        prepared += 1
        if let prepareFailure { throw prepareFailure }
        let trust = InstalledUpdateIdentity(version: "0.1.0", commit: String(repeating: "a", count: 40),
                                            publicKey: Data(repeating: 7, count: 32), certificateSHA256: String(repeating: "c", count: 64))
        let plan = try UpdatePlan(id: UUID(), installed: home.appendingPathComponent("Applications/RoleBand.app"), home: home,
                                  trust: trust, to: "0.1.1", toCommit: String(repeating: "b", count: 40), parent: getpid())
        try FileManager.default.createDirectory(at: plan.candidate, withIntermediateDirectories: true)
        return plan
    }
}

/// Which threads computed the space reserve.
private final class ReserveThreads: @unchecked Sendable {
    private let lock = NSLock()
    private var main: [Bool] = []
    func record(_ isMain: Bool) { lock.withLock { main.append(isMain) } }
    var onMain: [Bool] { lock.withLock { main } }
}

@MainActor private final class Harness {
    let release: FakeRelease
    let reserveThreads = ReserveThreads()
    let home = FileManager.default.temporaryDirectory.appendingPathComponent("update-installer-" + UUID().uuidString)
    var handedOff: [UpdatePlan] = []
    var handOffFails = false
    private(set) var installer: UpdateInstaller!
    init() {
        let release = FakeRelease()
        let home = home
        let reserveThreads = reserveThreads
        self.release = release
        installer = UpdateInstaller(operations: UpdateInstallerOperations(
            reserve: { reserveThreads.record(Thread.isMainThread); return 5_000_000_000 },
            download: { try await release.download($0, $1, $2) },
            prepare: { _ in try await release.prepare(home) },
            discard: { version in Task { await release.discard(version) } },
            handOff: { [unowned self] plan in
                if handOffFails { throw Injected.handOff }
                handedOff.append(plan)
            }))
    }
    deinit { try? FileManager.default.removeItem(at: home) }
}

@MainActor private func eventually(_ condition: @MainActor () async -> Bool) async -> Bool {
    let deadline = ContinuousClock.now.advanced(by: .seconds(5))
    while ContinuousClock.now < deadline {
        if await condition() { return true }
        try? await Task.sleep(for: .milliseconds(5))
    }
    return await condition()
}

@MainActor @Test func withNoScanRunningAVerifiedUpdateHandsOverAtOnceWithItsSpaceReserve() async throws {
    let h = Harness()
    await h.release.set(progress: [DownloadProgress(phase: .downloading, received: 96_000_000, total: 280_000_000)])
    await h.release.hold()
    h.installer.install("0.1.1")
    #expect(await eventually { await h.release.isHeld })
    #expect(await eventually { h.installer.activity == .downloading(received: 96_000_000, total: 280_000_000) })
    #expect(h.installer.version == "0.1.1")
    await h.release.release()
    #expect(await eventually { h.installer.activity == .restarting })
    #expect(h.handedOff.count == 1)
    #expect(await h.release.downloads.map(\.reserve) == [5_000_000_000])
    #expect(await h.release.discarded.isEmpty)
    #expect(h.reserveThreads.onMain == [false], "the reserve walk ran on the main thread")
}

/// A download reports every network chunk; the line hears the newest of them, once per megabyte it shows.
@MainActor @Test func aFastDownloadRedrawsTheLineOncePerMegabyteAndEndsOnItsLastReport() async throws {
    let h = Harness()
    let total: Int64 = 280_000_000
    let chunks = (1...10_000).map { DownloadProgress(phase: .downloading, received: Int64($0) * 16_384, total: total) }
    await h.release.set(progress: [DownloadProgress(phase: .metadata, received: 0, total: 0)] + chunks)
    await h.release.hold()
    var published = 0
    let watch = h.installer.$activity.dropFirst().sink { _ in published += 1 }
    defer { watch.cancel() }
    h.installer.install("0.1.1")
    let last = try #require(chunks.last).received
    func shown() -> Double? {
        guard case .downloading(let received, total) = h.installer.activity else { return nil }
        return UpdateSize.wholeMegabytes(received)
    }
    #expect(await eventually { shown() == UpdateSize.wholeMegabytes(last) })
    #expect(published <= 170, "\(published) redraws for \(last / 1_000_000) megabytes")
    await h.release.release()
    #expect(await eventually { h.installer.activity == .restarting })
}

@MainActor @Test func failuresKeepTheRunningVersionAndOnlyAFailedCheckDeletesTheDownload() async throws {
    let space = Harness()
    await space.release.set(downloadFailure: DownloadProblem.insufficientSpace(required: 5_600_000_000))
    await space.installer.installAndWait("0.1.1")
    #expect(space.installer.activity == .failed(.space(required: 5_600_000_000)))

    let offline = Harness()
    await offline.release.set(downloadFailure: URLError(.badServerResponse))
    await offline.installer.installAndWait("0.1.1")
    #expect(offline.installer.activity == .failed(.download))

    let forged = Harness()
    await forged.release.set(downloadFailure: ArtifactProblem.invalidImage)
    await forged.installer.installAndWait("0.1.1")
    #expect(forged.installer.activity == .failed(.check))

    let unsigned = Harness()
    await unsigned.release.set(prepareFailure: BundleInstallProblem.signature)
    await unsigned.installer.installAndWait("0.1.1")
    #expect(unsigned.installer.activity == .failed(.check))

    #expect(await eventually { await forged.release.discarded == ["0.1.1"] })
    #expect(await eventually { await unsigned.release.discarded == ["0.1.1"] })
    #expect(await space.release.discarded.isEmpty)
    #expect(await offline.release.discarded.isEmpty)
    for harness in [space, offline, forged, unsigned] { #expect(harness.handedOff.isEmpty) }

    await offline.release.set(downloadFailure: nil)
    await offline.installer.installAndWait("0.1.1")
    #expect(offline.installer.activity == .restarting && offline.handedOff.count == 1)
}

@MainActor @Test func cancelStopsTheDownloadAndNothingThatArrivesLaterRestartsTheApp() async throws {
    let h = Harness()
    await h.release.set(ignoresCancellation: true)
    await h.release.hold()
    h.installer.install("0.1.1")
    #expect(await eventually { await h.release.isHeld })
    h.installer.cancel()
    #expect(h.installer.activity == nil)
    await h.release.send(DownloadProgress(phase: .downloading, received: 200_000_000, total: 280_000_000))
    await h.release.release()
    try await Task.sleep(for: .milliseconds(100))
    #expect(h.installer.activity == nil)
    #expect(await h.release.prepared == 0)
    #expect(h.handedOff.isEmpty)
}

@MainActor @Test func goingOfflinePausesTheDownloadAndComingBackResumesIt() async throws {
    let h = Harness()
    await h.release.hold()
    h.installer.install("0.1.1")
    #expect(await eventually { await h.release.isHeld })
    await h.release.send(DownloadProgress(phase: .offline, received: 96_000_000, total: 280_000_000))
    #expect(await eventually { h.installer.activity == .paused(received: 96_000_000, total: 280_000_000) })
    await h.release.send(DownloadProgress(phase: .downloading, received: 120_000_000, total: 280_000_000))
    #expect(await eventually { h.installer.activity == .downloading(received: 120_000_000, total: 280_000_000) })
    await h.release.release()
    #expect(await eventually { h.installer.activity == .restarting })
}

@MainActor @Test func aSecondPressWhileUpdatingStartsNothingAndAFailedHandOverLeavesNoPlan() async throws {
    let h = Harness()
    await h.release.hold()
    h.installer.install("0.1.1")
    #expect(await eventually { await h.release.isHeld })
    h.installer.install("0.1.1")
    await h.release.release()
    #expect(await eventually { h.installer.activity == .restarting })
    #expect(await h.release.downloads.count == 1)

    let broken = Harness()
    broken.handOffFails = true
    await broken.installer.installAndWait("0.1.1")
    #expect(broken.installer.activity == .failed(.restart))
    let updates = HomeLayout(broken.home).data.appendingPathComponent("updates")
    #expect(((try? FileManager.default.contentsOfDirectory(atPath: updates.path)) ?? []).isEmpty)
}

@MainActor @Test func progressFromACancelledDownloadNeverShowsOnTheNextOne() async throws {
    let h = Harness()
    await h.release.hold()
    h.installer.install("0.1.1")
    #expect(await eventually { await h.release.isHeld })
    h.installer.cancel()
    await h.release.release()
    await h.release.hold()
    h.installer.install("0.1.1")
    #expect(await eventually { await h.release.isHeld && h.installer.activity == .downloading(received: 0, total: 0) })
    await h.release.send(DownloadProgress(phase: .offline, received: 250_000_000, total: 280_000_000), download: 0)
    try await Task.sleep(for: .milliseconds(100))
    #expect(h.installer.activity == .downloading(received: 0, total: 0))
    await h.release.send(DownloadProgress(phase: .downloading, received: 10_000_000, total: 280_000_000), download: 1)
    #expect(await eventually { h.installer.activity == .downloading(received: 10_000_000, total: 280_000_000) })
    await h.release.release()
    #expect(await eventually { h.installer.activity == .restarting })
}
