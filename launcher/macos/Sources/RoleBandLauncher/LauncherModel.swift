import AppKit
import LauncherCore
import ServiceManagement
import SwiftUI

@MainActor
struct LoginService {
    var state: () -> LoginState
    var setEnabled: (Bool) async throws -> Void
    var openSettings: () -> Void
    /// macOS answers `notFound` for an app that has never registered, ad hoc signed or not,
    /// and `register()` then succeeds, so it is off rather than unavailable.
    static func state(for status: SMAppService.Status) -> LoginState {
        switch status {
        case .enabled: .on
        case .notRegistered, .notFound: .off
        case .requiresApproval: .approval
        @unknown default: .unknown
        }
    }
    static var system: Self {
        Self(state: { state(for: SMAppService.mainApp.status) }, setEnabled: { enabled in
            if enabled { try SMAppService.mainApp.register() }
            else { try await unregisterMainApp() }
        }, openSettings: { SMAppService.openSystemSettingsLoginItems() })
    }
    // SMAppService is not Sendable in every SDK, so it is awaited only off the main actor.
    private nonisolated static func unregisterMainApp() async throws {
        try await SMAppService.mainApp.unregister()
    }
}

/// Everything the model reaches outside itself. Only `live` touches this Mac's registration,
/// preferences, browser and login item; tests build their own.
@MainActor
struct LauncherDependencies {
    var mode: LaunchMode = .attach
    var ownedEngine: OwnedEngineService?
    var registration: URL
    var installation: InstallationSource
    var readStatus: @Sendable (Installation) async throws -> VerifiedStatus = StatusClient.read
    var performScan: @Sendable (ScanAction, Installation, InstallationSource) async throws -> ScanOutcome = ScanClient.perform
    var readSchedule: @Sendable (VerifiedStatus, InstallationSource, String) async throws -> ScheduleState = ScheduleClient.read
    var performPause: @Sendable (PauseAction, Installation, InstallationSource, String) async throws -> ScheduleState = ScheduleClient.perform
    var timezone: @Sendable () -> String = { TimeZone.current.identifier }
    var engine = EngineClient()
    var readNotes: @Sendable (VerifiedStatus, InstallationSource) async throws -> InstalledNotes = ReleaseClient.read
    var launcherVersion: String?
    var openBrowser: (URL) -> Bool
    var preferences: UserDefaults
    var loginService: LoginService
    var bundleURL: URL
    var homeURL: URL
    var language: String?
    var updates: LauncherUpdates?
    /// Owned mode only: an app that does not own its engine cannot replace itself.
    var installOperations: UpdateInstallerOperations?
    var updateNotice: UpdateNotice?

    static func live(mode: LaunchMode = .attach, bundle: Bundle = .main,
                     home: URL = FileManager.default.homeDirectoryForCurrentUser,
                     port: Int = Installation.ownedPort,
                     preferences: UserDefaults = .standard, language: String? = nil) -> Self {
        let configured = ProcessInfo.processInfo.environment["ROLEBAND_LAUNCHER_REGISTRATION"]
            ?? bundle.object(forInfoDictionaryKey: "RoleBandRegistration") as? String
        let registration = configured.map { URL(fileURLWithPath: $0) } ?? HomeLayout(home).registration
        var dependencies = Self(mode: mode, registration: registration, installation: .registration(registration),
                    launcherVersion: bundle.object(forInfoDictionaryKey: "RoleBandVersion") as? String
                        ?? bundle.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String,
                    openBrowser: { NSWorkspace.shared.open($0) }, preferences: preferences, loginService: .system,
                    bundleURL: bundle.bundleURL, homeURL: home, language: language)
        if case .owned = mode {
            if let configuration = try? HostConfiguration(bundle: bundle, home: home, port: port) {
                dependencies.installation = .fixed(configuration.installation)
                dependencies.ownedEngine = .live(configuration)
            } else { dependencies.ownedEngine = .unavailable }
            let caches = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
            dependencies.installOperations = .live(installed: bundle.bundleURL, home: home,
                                                   cache: caches.appendingPathComponent("RoleBand"), bundle: bundle)
            if let version = dependencies.launcherVersion {
                dependencies.updateNotice = UpdateNotice.latest(installed: bundle.bundleURL, home: home, version: version)
            }
        }
        return dependencies
    }
}

@MainActor
final class LauncherModel: ObservableObject {
    let mode: LaunchMode
    private let ownedEngine: OwnedEngineService?
    @Published private(set) var hostState: HostState?
    @Published private(set) var diagnosticLines = ""
    @Published private(set) var preparation: EnginePreparation?
    @Published private(set) var setupLoginChoice = true
    var preparationReady: Bool { verified != nil && (ownedEngine == nil || hostState == .running) }
    var preparationFailed: Bool { preparation?.failed == true || hostState == .needsAttention }
    var preparationBytes: String {
        guard let preparation else { return "" }
        let format = ByteCountFormatStyle(style: .file, spellsOutZero: false).locale(copy.locale)
        return preparation.downloadedBytes.formatted(format) + " / " + preparation.totalBytes.formatted(format)
    }
    private var hostMonitor: Task<Void, Never>?
    private var launched = false
    private var shuttingDown = false
    private var shutdownTask: Task<Bool, Never>?
    var attached: Bool { mode == .attach }
    var ownsEngine: Bool { if case .owned = mode { true } else { false } }
    private var permitsActivity: Bool { (attached || ownsEngine) && !shuttingDown }
    private var mayReadStatus: Bool {
        guard permitsActivity else { return false }
        guard ownedEngine != nil else { return true }
        return hostState == .running
    }
    let copy: LauncherCopy
    let updates: LauncherUpdates
    @Published private(set) var verified: VerifiedStatus?
    private(set) var installer: UpdateInstaller?
    @Published private(set) var updateNotice: UpdateNotice?
    @Published var panelTab: PanelTab = .scan
    @Published private(set) var problem: ConnectionProblem?
    @Published private(set) var checking = false
    @Published private(set) var controlBusy = false
    /// The scan request in flight, so the panel can say Sending request or Stop requested.
    @Published private(set) var requestedScan: ScanAction?
    @Published private(set) var controlMessage: String?
    var scanAction: ScanAction? { verified?.scanAction }
    var scanPhase: ScanPhase? { verified.map { ScanPhase.of($0.presentation, picture: $0.scan, requested: requestedScan) } }
    /// The scan picture stands in for the status card while the engine is healthy and has something
    /// to draw: a scan underway, or a finished one. Holds and updates keep the card, which says why.
    var scanPicture: ScanPicture? {
        guard hostTitleKey == nil, !(attached && engineState == .stopped), let verified, let picture = verified.scan,
              let phase = scanPhase else { return nil }
        let status = verified.presentation
        guard status.hold == nil, status.activity != .updating else { return nil }
        return phase == .scanning || phase == .stopping || picture.lastCompanies != nil ? picture : nil
    }
    @Published private(set) var scheduleState: ScheduleState?
    @Published private(set) var scheduleFailed = false
    @Published private(set) var engineState: EngineState?
    @Published private(set) var engineLogDirectory: URL?
    @Published private(set) var installedNotes: InstalledNotes?
    @Published private(set) var notesFailed = false
    @Published private(set) var hasNewRelease = false
    let launcherVersion: String?
    var launcherBehind: Bool {
        guard let current = verified.flatMap({ ReleaseVersion($0.engineVersion) }),
              let local = launcherVersion.flatMap(ReleaseVersion.init) else { return false }
        return local < current
    }
    var mayStartEngine: Bool { ownsEngine && ownedEngine != nil && hostState == .stopped && !shuttingDown }
    var mayRestartEngine: Bool { ownsEngine && ownedEngine != nil && (hostState == .running || hostState == .needsAttention) && !shuttingDown }
    var engineActionKey: String? { mayStartEngine ? "engine-start" : mayRestartEngine ? "engine-restart" : nil }
    @Published var step: SetupStep {
        didSet {
            preferences.set(step.id, forKey: "setupStep")
            updateLoginMonitoring()
            if launched && engineHeld(at: oldValue) && !engineHeld { startEngine() }
        }
    }
    @Published private(set) var setupCompleted: Bool
    @Published private(set) var completingSetup = false
    @Published private(set) var setupOpenFailed = false
    @Published private(set) var loginState = LoginState.unknown
    var loginEnabled: Bool { loginState == .on }
    @Published private(set) var loginBusy = false
    @Published private(set) var loginError = false
    var changed: (() -> Void)?
    var panelOpen = false
    private var failures = 0
    private var pending = false
    private var forceScheduleRead = false
    private var forceNotesRead = false
    private var notesVisible = false
    private var notesFor: String?
    private var scheduleReadAt: Date?
    private var scheduleInstallation: Installation?
    private var openAfterRead: BrowserRoute?
    private var task: Task<Void, Never>?
    private var controlTask: Task<Void, Never>?
    private var timer: Timer?
    private(set) var loginTimer: Timer?
    private var setupVisible = false
    let registrationURL: URL
    private let installationSource: InstallationSource
    private let readStatus: @Sendable (Installation) async throws -> VerifiedStatus
    private let performScan: @Sendable (ScanAction, Installation, InstallationSource) async throws -> ScanOutcome
    private let readSchedule: @Sendable (VerifiedStatus, InstallationSource, String) async throws -> ScheduleState
    private let performPause: @Sendable (PauseAction, Installation, InstallationSource, String) async throws -> ScheduleState
    private let timezone: @Sendable () -> String
    private let engine: EngineClient
    private let readNotes: @Sendable (VerifiedStatus, InstallationSource) async throws -> InstalledNotes
    private let openBrowser: (URL) -> Bool
    private let preferences: UserDefaults
    private let loginService: LoginService
    let bundleURL: URL
    private let homeURL: URL
    var installed: Bool { AppLocation.isInstalled(bundleURL, home: homeURL) }
    var shouldShowSetupAtLaunch: Bool { ownsEngine && !setupCompleted && !preferences.bool(forKey: "setupDeferred") }
    /// An owned engine, and with it every scheduled scan, waits until setup has begun in a copy
    /// inside Applications: past Welcome, or finished. Opening the download or leaving Welcome
    /// unanswered starts nothing.
    var engineHeld: Bool { engineHeld(at: step) }
    var setupPending: Bool { ownsEngine && !setupCompleted }
    private func engineHeld(at step: SetupStep) -> Bool {
        ownsEngine && !setupCompleted && (step == .welcome || !installed)
    }
    private(set) var lastGood: VerifiedStatus?
    init(_ dependencies: LauncherDependencies) {
        mode = dependencies.mode
        if case .owned = dependencies.mode { ownedEngine = dependencies.ownedEngine }
        else { ownedEngine = nil }
        hostState = ownedEngine == nil ? nil : .stopped
        copy = LauncherCopy(language: dependencies.language)
        updates = dependencies.updates
            ?? UpdateDemo.updates(preferences: dependencies.preferences, copy: LauncherCopy(language: dependencies.language))
        registrationURL = dependencies.registration
        installationSource = dependencies.installation
        readStatus = dependencies.readStatus
        performScan = dependencies.performScan
        readSchedule = dependencies.readSchedule
        performPause = dependencies.performPause
        timezone = dependencies.timezone
        engine = dependencies.engine
        readNotes = dependencies.readNotes
        launcherVersion = dependencies.launcherVersion
        openBrowser = dependencies.openBrowser
        preferences = dependencies.preferences
        loginService = dependencies.loginService
        bundleURL = dependencies.bundleURL
        homeURL = dependencies.homeURL
        setupCompleted = preferences.bool(forKey: "setupCompleted")
        setupLoginChoice = preferences.object(forKey: "setupLoginChoice") as? Bool ?? true
        let saved = preferences.string(forKey: "setupStep").flatMap(SetupStep.init(id:)) ?? .welcome
        step = saved == .installation && AppLocation.isInstalled(bundleURL, home: homeURL) ? .connection : saved
        if let notice = dependencies.updateNotice, preferences.string(forKey: "updateNoticeDismissed") != notice.id.uuidString {
            updateNotice = notice
            if notice.kind == .rolledBack { updates.suppress(notice.to) }
        }
        if ownsEngine, let operations = dependencies.installOperations {
            installer = UpdateInstaller(operations: operations)
        }
    }
    func dismissUpdateNotice() {
        guard let notice = updateNotice else { return }
        preferences.set(notice.id.uuidString, forKey: "updateNoticeDismissed")
        updateNotice = nil
    }
    func open(_ route: BrowserRoute) { refresh(open: route) }
    var preview: Bool { Bundle.main.object(forInfoDictionaryKey: "RoleBandPreview") as? Bool ?? false }
    var titleKey: String {
        if let key = hostTitleKey { return key }
        if attached && engineState == .stopped { return "attached-stopped-title" }
        if let verified { return verified.presentation.titleKey }
        switch problem {
        case .invalidResponse: return "incorrect"
        case .none: return "connecting"
        default: return "disconnected"
        }
    }
    var helpKey: String? {
        if hostState == .needsAttention { return "host-attention-body" }
        if case .backingOff = hostState { return "host-recovering-body" }
        if attached && engineState == .stopped { return "attached-stopped-body" }
        if let verified { return verified.presentation.reasonKey }
        switch problem {
        case .missingInstallation: return "missing"
        case .upgradeRequired: return "upgrade"
        case .identityMismatch, .invalidInstallation: return "invalid"
        default: return nil
        }
    }
    private var hostTitleKey: String? {
        switch hostState {
        case .starting: preparation == nil ? "host-starting" : "first-preparing-title"
        case .backingOff: "host-recovering"
        case .needsAttention: "host-attention"
        case .stopped: "host-stopped"
        default: nil
        }
    }
    var symbol: String {
        switch hostState {
        case .needsAttention: "exclamationmark.triangle"
        case .starting, .backingOff: "arrow.triangle.2.circlepath"
        default: verified?.presentation.symbol ?? "network.slash"
        }
    }
    /// The menu bar always shows the product mark; a state other than at rest adds its own
    /// symbol as a badge on it.
    var menuBarBadge: String? {
        switch symbol {
        case "checkmark.circle": nil
        case "arrow.triangle.2.circlepath": "arrow.triangle.2.circlepath.circle.fill"
        case "pause.circle": "pause.circle.fill"
        case "exclamationmark.circle": "exclamationmark.circle.fill"
        case "exclamationmark.triangle": "exclamationmark.triangle.fill"
        case "network.slash": "xmark.circle.fill"
        default: symbol
        }
    }
    func text(_ key: String) -> String { copy.text(key) }
    func text(_ key: String, _ values: [String: String]) -> String { copy.text(key, values) }

    func refresh(open route: BrowserRoute? = nil, includeSchedule: Bool = false, includeNotes: Bool = false) {
        guard mayReadStatus else { return }
        timer?.invalidate()
        if let route { openAfterRead = route }
        forceScheduleRead = forceScheduleRead || includeSchedule
        forceNotesRead = forceNotesRead || includeNotes
        if checking || controlBusy { pending = true; return }
        let loadSchedule = forceScheduleRead
        let loadNotes = forceNotesRead
        forceScheduleRead = false
        forceNotesRead = false
        checking = true
        changed?()
        task = Task {
            var candidate: Installation?
            do {
                let installation = try installationSource.current()
                candidate = installation
                let result = try await readStatus(installation)
                try Task.checkCancellation()
                // A replacement registration invalidates an in-flight reply.
                try installationSource.confirm(installation)
                if scheduleInstallation != installation {
                    scheduleState = nil
                    scheduleReadAt = nil
                    scheduleFailed = false
                }
                // The status says how scans start; only an engine that does not is asked for its
                // roster-bearing schedule, at most once a minute while visible, apart from explicit refreshes.
                if let schedule = result.scan?.schedule {
                    scheduleState = schedule
                    scheduleFailed = false
                    scheduleInstallation = installation
                } else if loadSchedule || (panelOpen && (scheduleReadAt.map { Date().timeIntervalSince($0) >= 60 } ?? true)) {
                    do {
                        scheduleState = try await readSchedule(result, installationSource, timezone())
                        scheduleFailed = false
                    } catch is CancellationError { throw CancellationError() }
                    catch { scheduleState = nil; scheduleFailed = true }
                    scheduleReadAt = Date()
                    scheduleInstallation = installation
                    try installationSource.confirm(installation)
                }
                verified = result
                // The engine answering is the response a start request waits for.
                if controlMessage == "engine-requested" { controlMessage = nil }
                observeVersion(result)
                if notesVisible && (loadNotes || (installedNotes == nil && !notesFailed)) {
                    do {
                        installedNotes = try await readNotes(result, installationSource)
                        notesFailed = false
                    } catch is CancellationError { throw CancellationError() }
                    catch { installedNotes = nil; notesFailed = true }
                    try installationSource.confirm(installation)
                }
                engineState = nil
                if !ownsEngine { engineLogDirectory = nil }
                lastGood = result
                problem = nil
                failures = 0
                // A browser that does not open says nothing about the engine, which just answered.
                if let route = openAfterRead, !openBrowser(try route.url(for: installation)) {
                    controlMessage = "setup-browser-error"
                }
            } catch is CancellationError {
                // Only `stop()` cancels a read; the next `refresh()` must find the model idle.
                openAfterRead = nil
                pending = false
                checking = false
                changed?()
                return
            }
            catch {
                verified = nil
                installedNotes = nil
                notesFor = nil
                notesFailed = notesVisible
                hasNewRelease = false
                scheduleState = nil
                scheduleInstallation = nil
                scheduleReadAt = nil
                problem = error as? ConnectionProblem ?? .unavailable
                engineState = nil
                engineLogDirectory = HomeLayout(homeURL).data.appendingPathComponent("logs")
                if attached, problem == .unavailable, let candidate {
                    engineState = await engine.inspect(candidate, registration: registrationURL, home: homeURL)
                    engineLogDirectory = engine.logDirectory(candidate, registration: registrationURL, home: homeURL) ?? engineLogDirectory
                }
                failures = min(6, failures + 1)
            }
            openAfterRead = nil
            checking = false
            changed?()
            if pending {
                pending = false
                refresh()
            } else {
                schedule()
            }
        }
    }
    private func schedule() {
        let active = verified.map { $0.presentation.isActive } ?? false
        let delay = PollPolicy.delay(panelOpen: panelOpen, active: active, failures: failures)
        let next = Timer(timeInterval: delay, repeats: false) { [weak self] _ in
            Task { @MainActor in self?.refresh() }
        }
        next.tolerance = min(5, delay / 10)
        RunLoop.main.add(next, forMode: .common)
        timer = next
    }
    func stop() {
        task?.cancel(); controlTask?.cancel(); timer?.invalidate(); loginTimer?.invalidate(); loginTimer = nil
        hostMonitor?.cancel(); hostMonitor = nil
    }

    func launch() {
        guard permitsActivity, !launched else { return }
        launched = true
        refreshLogin()
        if ownsEngine {
            engineLogDirectory = HomeLayout(homeURL).data.appendingPathComponent("logs")
            monitorHost()
            if !engineHeld { startEngine() }
        } else { refresh() }
    }

    private func monitorHost() {
        guard ownedEngine != nil, hostMonitor == nil else { return }
        hostMonitor = Task { [weak self] in
            while !Task.isCancelled {
                await self?.refreshHost()
                do { try await Task.sleep(for: .seconds(1)) } catch { return }
            }
        }
    }

    func refreshHost() async {
        guard let ownedEngine, !shuttingDown else { return }
        let snapshot = await ownedEngine.snapshot()
        guard !shuttingDown, !Task.isCancelled else { return }
        let previous = hostState
        // This runs every second; a published value is set only when it changes, so an idle
        // engine redraws nothing.
        if hostState != snapshot.state { hostState = snapshot.state }
        if preparation != snapshot.preparation { preparation = snapshot.preparation }
        if diagnosticLines != snapshot.diagnostics { diagnosticLines = snapshot.diagnostics }
        if snapshot.state != .running {
            task?.cancel()
            timer?.invalidate()
            if verified != nil { verified = nil }
            if scheduleState != nil { scheduleState = nil }
            scheduleInstallation = nil
            scheduleReadAt = nil
            if scheduleFailed { scheduleFailed = false }
            if installedNotes != nil { installedNotes = nil }
            notesFor = nil
            if hasNewRelease { hasNewRelease = false }
            if problem != .unavailable { problem = .unavailable }
        }
        if previous != hostState {
            failures = 0
            changed?()
            if mayReadStatus, !controlBusy { refresh() }
        }
    }

    func shutdown() async -> Bool {
        if let shutdownTask { return await shutdownTask.value }
        let next = Task { await stopForQuit() }
        shutdownTask = next
        let stopped = await next.value
        if !stopped { shutdownTask = nil }
        return stopped
    }

    private func stopForQuit() async -> Bool {
        shuttingDown = true
        stop()
        updates.stop()
        guard ownsEngine, let ownedEngine else { return true }
        do {
            try await ownedEngine.stop()
            hostState = .stopped
            return true
        } catch {
            let snapshot = await ownedEngine.snapshot()
            hostState = .needsAttention
            diagnosticLines = snapshot.diagnostics
            controlMessage = "host-stop-failed"
            shuttingDown = false
            controlBusy = false
            monitorHost()
            updates.start()
            installer?.quitRefused()
            changed?()
            return false
        }
    }

    func launchAndWait() async { launch(); await controlTask?.value; await task?.value }
    /// Showing the panel or the status window and returning to the app read the roster-bearing
    /// schedule only through the once-a-minute throttle; a read already in flight answers for the
    /// activation that showing the panel causes.
    func panelShown() {
        panelOpen = true
        refresh()
    }
    func becameActive() {
        if !checking { refresh() }
    }
    func refreshAndWait(includeSchedule: Bool = false, includeNotes: Bool = false) async {
        refresh(includeSchedule: includeSchedule, includeNotes: includeNotes); await task?.value
    }
    private func observeVersion(_ status: VerifiedStatus) {
        let key = status.installation.instance + "@" + status.installation.apiOrigin + "#" + status.engineVersion
        if notesFor != key {
            installedNotes = nil
            notesFailed = false
            notesFor = key
        }
        guard let version = ReleaseVersion(status.engineVersion) else { hasNewRelease = false; return }
        var seen = preferences.dictionary(forKey: "seenInstalledReleases") as? [String: String] ?? [:]
        if let previous = seen[status.installation.instance].flatMap(ReleaseVersion.init) {
            hasNewRelease = previous < version
        } else {
            seen[status.installation.instance] = status.engineVersion
            preferences.set(seen, forKey: "seenInstalledReleases")
            hasNewRelease = false
        }
    }
    func setNotesVisible(_ visible: Bool) {
        notesVisible = visible
        if visible { notesFailed = false }
    }
    func acknowledgeNotes() {
        guard notesVisible, let notes = installedNotes, let status = verified,
              notes.version == status.engineVersion, notes.identity.instance == status.installation.instance,
              notes.identity.apiOrigin == status.installation.apiOrigin,
              (try? installationSource.current()) == status.installation else { return }
        var seen = preferences.dictionary(forKey: "seenInstalledReleases") as? [String: String] ?? [:]
        if let version = ReleaseVersion(notes.version),
           seen[notes.identity.instance].flatMap(ReleaseVersion.init).map({ $0 < version }) ?? true {
            seen[notes.identity.instance] = notes.version
            preferences.set(seen, forKey: "seenInstalledReleases")
        }
        hasNewRelease = false
    }
    func scan(_ action: ScanAction) {
        guard permitsActivity, !controlBusy, let status = verified, status.scanAction == action else { return }
        requestedScan = action
        control(prefix: "scan", refreshSchedule: false) {
            try await self.performScan(action, status.installation, self.installationSource).key
        }
    }
    /// Puts a scan request in flight for renders only.
    func showRequest(_ action: ScanAction) { requestedScan = action }
    func pause(_ action: PauseAction) {
        guard permitsActivity, !controlBusy, let status = verified, let plan = scheduleState,
              (action == .resume) == plan.isPaused(), action == .resume || plan.pausable else { return }
        control(prefix: "pause", refreshSchedule: true) {
            _ = try await self.performPause(action, status.installation, self.installationSource, self.timezone())
            return action == .resume ? "pause-resumed" : "pause-confirmed"
        }
    }
    func startEngine() {
        guard !controlBusy, let ownedEngine, mayStartEngine || mayRestartEngine else { return }
        let restarting = mayRestartEngine
        task?.cancel()
        timer?.invalidate()
        control(prefix: "engine", refreshSchedule: false) {
            do {
                if restarting { try await ownedEngine.restart() }
                else { try await ownedEngine.start() }
            } catch {
                await self.refreshHost()
                throw error
            }
            await self.refreshHost()
            self.failures = 0
            return "engine-requested"
        }
    }
    private func control(prefix: String, refreshSchedule: Bool, operation: @escaping @MainActor () async throws -> String?) {
        timer?.invalidate()
        controlBusy = true
        controlMessage = nil
        controlTask = Task {
            do {
                let message = try await operation()
                try Task.checkCancellation()
                controlMessage = message
            } catch is CancellationError {
                controlBusy = false
                requestedScan = nil
                return
            } catch ControlProblem.stateChanged { controlMessage = prefix + "-state-changed" }
            catch ControlProblem.refused { controlMessage = prefix + "-refused" }
            catch { controlMessage = prefix + "-unconfirmed" }
            controlBusy = false
            requestedScan = nil
            guard !Task.isCancelled else { return }
            pending = false
            refresh(includeSchedule: refreshSchedule)
        }
    }
    func scanAndWait(_ action: ScanAction) async { scan(action); await controlTask?.value; await task?.value }
    func pauseAndWait(_ action: PauseAction) async { pause(action); await controlTask?.value; await task?.value }
    func startEngineAndWait() async { startEngine(); await controlTask?.value; await task?.value }
    func refreshLogin() {
        guard permitsActivity else { return }
        loginState = loginService.state()
    }
    func setSetupVisible(_ visible: Bool) {
        setupVisible = visible
        updateLoginMonitoring()
    }
    private func updateLoginMonitoring() {
        loginTimer?.invalidate()
        loginTimer = nil
        guard setupVisible, step == .login else { return }
        refreshLogin()
        let next = Timer(timeInterval: 1, repeats: true) { [weak self] _ in
            Task { @MainActor in
                guard let self, self.setupVisible, self.step == .login else { return }
                self.refreshLogin()
            }
        }
        next.tolerance = 0.2
        RunLoop.main.add(next, forMode: .common)
        loginTimer = next
    }
    func setLogin(_ enabled: Bool, openApprovalSettings: Bool = true) async {
        guard permitsActivity, !loginBusy, !enabled || installed else { return }
        loginError = false
        refreshLogin()
        // Unregistering an app that never registered is not a request macOS has to answer.
        if !enabled, loginState == .off { return }
        loginBusy = true
        defer { loginBusy = false }
        do {
            try await loginService.setEnabled(enabled)
            refreshLogin()
            if enabled && loginState == .approval && openApprovalSettings { openLoginSettings() }
        } catch {
            refreshLogin()
            loginError = true
        }
    }
    func openLoginSettings() {
        refreshLogin()
        loginService.openSettings()
    }
    func prepareSetup() {
        guard ownsEngine, permitsActivity else { return }
        setupOpenFailed = false
        if setupCompleted { step = .welcome }
        if step == .installation && installed { step = .connection }
        preferences.set(false, forKey: "setupDeferred")
        refreshLogin()
        if setupCompleted { setupLoginChoice = loginState == .on || loginState == .approval }
        refresh()
    }
    func deferSetup() { preferences.set(true, forKey: "setupDeferred") }
    func advance() { step = step.next(connected: preparationReady, installed: installed) }
    func chooseSetupLogin(_ enabled: Bool) async {
        guard ownsEngine, permitsActivity else { return }
        setupLoginChoice = enabled
        preferences.set(enabled, forKey: "setupLoginChoice")
        await setLogin(enabled, openApprovalSettings: false)
    }
    func advanceSetup() async {
        guard ownsEngine, permitsActivity, !loginBusy else { return }
        if step == .login {
            let registered = loginState == .on || loginState == .approval
            if registered != setupLoginChoice { await setLogin(setupLoginChoice, openApprovalSettings: false) }
            guard !loginError else { return }
        }
        advance()
    }
    func goBack() { step = step.previous(installed: installed) }
    func dismissSetup() {
        if step != .done || !finish() { deferSetup() }
    }
    func completeAndOpen() async -> Bool {
        guard !completingSetup, !checking, !controlBusy, step == .done else { return false }
        guard installed else { step = .installation; return false }
        completingSetup = true
        setupOpenFailed = false
        defer { completingSetup = false }
        await refreshAndWait()
        guard let status = verified else { step = .connection; return false }
        do {
            try installationSource.confirm(status.installation)
            let url = try BrowserRoute.radar.url(for: status.installation)
            guard finish() else { return false }
            setupOpenFailed = !openBrowser(url)
            return !setupOpenFailed
        } catch {
            verified = nil
            problem = error as? ConnectionProblem ?? .unavailable
            step = .connection
            return false
        }
    }
    @discardableResult func finish() -> Bool {
        guard installed, verified != nil else {
            step = installed ? .connection : .installation
            return false
        }
        setupCompleted = true
        preferences.set(true, forKey: "setupCompleted")
        return true
    }
}
