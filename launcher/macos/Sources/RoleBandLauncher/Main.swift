import AppKit
import LauncherCore
import SwiftUI

@main
enum LauncherMain {
    @MainActor static func session(bundle: URL, home: URL,
                                   dependencies: (LaunchMode) -> LauncherDependencies) -> LauncherSession {
        let mode = LaunchMode.decide(bundle: bundle, home: home)
        return LauncherSession(mode: mode) { dependencies(mode) }
    }

    @MainActor static func main() {
        let arguments = CommandLine.arguments
        if arguments.count == 3, ["--apply-update", "--recover-update"].contains(arguments[1]),
           let id = UUID(uuidString: arguments[2]) {
            let home = FileManager.default.homeDirectoryForCurrentUser
            Task {
                let note: @Sendable (String) -> Void = { FileHandle.standardError.write(Data(("\(Date()) \($0)\n").utf8)) }
                guard let plan = try? UpdatePlan.load(home: home, id: id) else { note("update \(id): plan refused"); exit(2) }
                let helper = UpdateHelper(plan: plan, operations: UpdateHelper.live(plan: plan, open: AppOpener.open), note: note)
                let outcome = arguments[1] == "--apply-update" ? await helper.apply() : await helper.recover()
                note("update \(id): \(outcome.rawValue)")
                exit([.committed, .rolledBack, .unchanged].contains(outcome) ? 0 : 1)
            }
            dispatchMain()
        }
        if arguments.count == 6, arguments[1] == "--verify-update-bundle" {
            Task {
                do {
                    let verifier = UpdateBundleVerifier()
                    let trust = try await verifier.installed(at: URL(fileURLWithPath: arguments[2]))
                    try await verifier.validate(URL(fileURLWithPath: arguments[3]), version: arguments[4], commit: arguments[5], trust: trust)
                    print("{\"ok\":true}")
                    exit(0)
                } catch {
                    print("{\"ok\":false}")
                    exit(1)
                }
            }
            dispatchMain()
        }
        if arguments.count == 3, arguments[1] == "--check-engine" {
            guard Bundle.main.object(forInfoDictionaryKey: "RoleBandPackagedEngine") as? Bool == true,
                  let resources = Bundle.main.resourceURL else { exit(1) }
            let scratch = URL(fileURLWithPath: arguments[2]).standardizedFileURL
            let process = Process()
            process.executableURL = resources.appendingPathComponent("python/bin/python3")
            process.arguments = ["-I", resources.appendingPathComponent("engine/packaged.py").path,
                                 "probe", "--scratch", scratch.path]
            var environment = ProcessInfo.processInfo.environment.filter {
                !$0.key.hasPrefix("ROLEBAND_") && !["PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"].contains($0.key)
            }
            environment["HOME"] = scratch.appendingPathComponent("home").path
            environment["ROLEBAND_PGDATA"] = scratch.appendingPathComponent("db").path
            environment["ROLEBAND_DATABASE_URL"] = ""
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            process.environment = environment
            process.currentDirectoryURL = resources.appendingPathComponent("engine")
            process.standardInput = FileHandle.nullDevice
            process.standardOutput = FileHandle.standardOutput
            process.standardError = FileHandle.standardError
            do {
                try process.run()
                process.waitUntilExit()
                exit(process.terminationStatus)
            } catch {
                FileHandle.standardError.write(Data("Bundle probe failed: \(error)\n".utf8))
                exit(1)
            }
        }
        if arguments.count == 2, arguments[1] == "--check-copy" { exit(LauncherCopy.appCarriesCatalogs() ? 0 : 1) }
        if arguments.count >= 3, arguments[1] == "--render-launch-block" {
            let app = NSApplication.shared
            app.setActivationPolicy(.prohibited)
            let dark = arguments.contains("dark")
            app.appearance = NSAppearance(named: dark ? .darkAqua : .aqua)
            let language = arguments.first(where: { $0.hasPrefix("--lang=") }).map { String($0.dropFirst(7)) }
            let stopped = arguments.contains("--update-stopped") || arguments.contains("--update-unreadable")
            let block = LaunchBlock(mode: arguments.contains("--owned-elsewhere") ? .databaseOwnedElsewhere : .moveToApplications,
                                    bundle: Bundle.main.bundleURL, home: FileManager.default.homeDirectoryForCurrentUser,
                                    update: stopped ? .init(id: UUID(), retry: arguments.contains("--update-stopped")) : nil)
            let view = NSHostingView(rootView: BlockedLaunchView(block: block, copy: LauncherCopy(language: language), quit: {}, reveal: {})
                .environment(\.colorScheme, dark ? .dark : .light))
            view.frame = NSRect(origin: .zero, size: view.fittingSize)
            view.layoutSubtreeIfNeeded()
            guard let bitmap = view.bitmapImageRepForCachingDisplay(in: view.bounds) else { exit(1) }
            view.cacheDisplay(in: view.bounds, to: bitmap)
            do {
                try bitmap.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: arguments[2]))
                exit(0)
            } catch { exit(1) }
        }
        let renderPanel = arguments.count >= 3 && arguments[1] == "--render-panel"
        let renderNotes = arguments.count >= 3 && arguments[1] == "--render-notes"
        let renderOffered = arguments.count >= 3 && arguments[1] == "--render-offered"
        let renderStep = arguments.count >= 4 && arguments[1] == "--render-setup"
            ? Int(arguments[3]).flatMap(SetupStep.init(rawValue:)) : nil
        if renderPanel || renderNotes || renderOffered || renderStep != nil {
            let path = CommandLine.arguments[2]
            let app = NSApplication.shared
            app.setActivationPolicy(.prohibited)
            let dark = CommandLine.arguments.contains("dark")
            app.appearance = NSAppearance(named: dark ? .darkAqua : .aqua)
            Task {
                let preferences = UserDefaults.scratch("render")
                let language = CommandLine.arguments.first(where: { $0.hasPrefix("--lang=") }).map { String($0.dropFirst(7)) }
                let model: LauncherModel
                if renderStep != nil {
                    guard let preview = try? FirstOpenPreview.model(preferences: preferences, language: language, arguments: arguments) else { exit(1) }
                    model = preview
                    await model.launchAndWait()
                } else if (renderPanel || renderOffered) && arguments.contains(where: { $0.hasPrefix("--tab=") || $0.hasPrefix("--update=") || $0.hasPrefix("--scan=") || $0.hasPrefix("--setup=") }) {
                    guard let preview = try? await PanelPreview.model(preferences: preferences, language: language, arguments: arguments) else { exit(1) }
                    model = preview
                } else { model = LauncherModel(.live(preferences: preferences, language: language)) }
                var offered: OfferedRelease?
                if renderOffered {
                    guard let path = arguments.first(where: { $0.hasPrefix("--release-fixture=") }).map({ String($0.dropFirst(18)) }),
                          let data = try? Data(contentsOf: URL(fileURLWithPath: path)), let release = try? OfferedRelease.decode(data, from: .production) else { exit(1) }
                    // `--notice=` stands in for the notice a release's signed metadata would carry.
                    offered = release.signed(notice: arguments.first(where: { $0.hasPrefix("--notice=") }).map { String($0.dropFirst(9)) })
                }
                if let renderStep { model.step = renderStep }
                model.panelOpen = renderPanel
                model.setNotesVisible(renderNotes)
                await model.refreshAndWait(includeNotes: renderNotes)
                if renderStep == .done && arguments.contains("--browser-failed") { _ = await model.completeAndOpen() }
                model.stop()
                let content = Group {
                    if renderNotes { ReleaseNotesView(model: model, close: {}) }
                    else if let offered {
                        OfferedReleaseView(release: offered, copy: model.copy, openPage: {}, close: {}, install: model.installer.map { _ in {} })
                    }
                    else if renderPanel { MainPanel(model: model, notes: {}, offered: {}) }
                    else { SetupView(model: model, close: {}) }
                }
                let size = NSSize(width: renderPanel ? PanelMetrics.width : renderNotes || renderOffered ? 640 : 540,
                                  height: renderPanel || renderNotes || renderOffered ? 700 : 452)
                let view = NSHostingView(rootView: content
                    .environment(\.colorScheme, dark ? .dark : .light)
                    .frame(width: size.width, height: size.height, alignment: .top)
                    .background(Color(nsColor: .windowBackgroundColor)))
                view.frame = NSRect(origin: .zero, size: size)
                view.layoutSubtreeIfNeeded()
                guard let bitmap = view.bitmapImageRepForCachingDisplay(in: view.bounds) else { exit(1) }
                view.cacheDisplay(in: view.bounds, to: bitmap)
                do {
                    try bitmap.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: path))
                    exit(0)
                } catch { exit(1) }
            }
            app.run()
        }
        if arguments.count == 3, arguments[1] == "--inspect-engine" {
            Task {
                do {
                    let path = URL(fileURLWithPath: arguments[2])
                    let installation = try Installation.load(path)
                    let state = await EngineClient().inspect(installation, registration: path,
                                                            home: FileManager.default.homeDirectoryForCurrentUser)
                    FileHandle.standardOutput.write(Data((state.rawValue + "\n").utf8))
                    exit(0)
                } catch { exit(1) }
            }
            dispatchMain()
        }
        if CommandLine.arguments.count == 3, CommandLine.arguments[1] == "--verify-registration" {
            let path = CommandLine.arguments[2]
            Task {
                do {
                    let installation = try Installation.load(URL(fileURLWithPath: path))
                    let result = try await StatusClient.read(installation)
                    let data = try JSONEncoder().encode(result.presentation)
                    FileHandle.standardOutput.write(data)
                    exit(0)
                } catch {
                    FileHandle.standardError.write(Data("\(error)\n".utf8))
                    exit(1)
                }
            }
            dispatchMain()
        }
        let home = FileManager.default.homeDirectoryForCurrentUser
        let recover = { (id: UUID) throws in
            let paths = UpdateTransactionPaths(installed: Bundle.main.bundleURL, home: home, id: id)
            let executable = UpdateHelperProcess.executable(for: paths, fallback: Bundle.main.executableURL!)
            try UpdateHelperProcess.spawn(executable: executable, recovering: true, id: id, home: home)
        }
        var stopped: LaunchBlock.StoppedUpdate?
        if case .owned = LaunchMode.decide(bundle: Bundle.main.bundleURL, home: home),
           let version = Bundle.main.object(forInfoDictionaryKey: "RoleBandVersion") as? String {
            switch UpdateStartup.decide(installed: Bundle.main.bundleURL, home: home, version: version) {
            case .proceed: UpdatePlan.discardAbandoned(home: home)
            case .helperAtWork: exit(0)
            case .recover(let id):
                do { try recover(id); exit(0) } catch {
                    FileHandle.standardError.write(Data("Update \(id): the recovery helper did not start: \(error)\n".utf8))
                    stopped = .init(id: id, retry: true)
                }
            case .recoveryFailed(let id): stopped = .init(id: id, retry: true)
            case .untrustedJournal(let id):
                FileHandle.standardError.write(Data("Update \(id) left a journal this app cannot trust; starting nothing.\n".utf8))
                stopped = .init(id: id, retry: false)
            }
        }
        if let id = Bundle.main.bundleIdentifier,
           let existing = NSRunningApplication.runningApplications(withBundleIdentifier: id)
            .first(where: { $0.processIdentifier != ProcessInfo.processInfo.processIdentifier }) {
            existing.activate()
            return
        }
        let app = NSApplication.shared
        if let stopped {
            // The window starts nothing: the engine waits until the update is finished or put back.
            let block = LaunchBlock(mode: .owned(leftover: nil), bundle: Bundle.main.bundleURL, home: home, update: stopped)
            let delegate = BlockedLaunchDelegate(block: block, retry: { try recover(stopped.id) })
            app.delegate = delegate
            withExtendedLifetime(delegate) { app.run() }
            return
        }
        let session = Self.session(bundle: Bundle.main.bundleURL, home: home) { .live(mode: $0, home: home) }
        if let model = session.model {
            let delegate = LauncherDelegate(session: session, model: model)
            app.delegate = delegate
            withExtendedLifetime(delegate) { app.run() }
        } else {
            let delegate = BlockedLaunchDelegate(block: LaunchBlock(mode: session.mode, bundle: Bundle.main.bundleURL, home: home))
            app.delegate = delegate
            withExtendedLifetime(delegate) { app.run() }
        }
    }
}

enum AppOpener {
    /// Launch Services reports a real process id only once the app has started AppKit.
    @MainActor static func open(_ app: URL) async throws -> pid_t {
        let configuration = NSWorkspace.OpenConfiguration()
        configuration.createsNewApplicationInstance = true
        configuration.addsToRecentItems = false
        configuration.activates = false
        let pid = try await NSWorkspace.shared.openApplication(at: app, configuration: configuration).processIdentifier
        guard pid > 0 else { throw CocoaError(.executableLoad) }
        return pid
    }
}

@MainActor
final class LauncherWindow: NSWindow {
    override func cancelOperation(_ sender: Any?) { performClose(sender) }
}

@MainActor
final class LauncherDelegate: NSObject, NSApplicationDelegate, NSPopoverDelegate, NSWindowDelegate {
    private let session: LauncherSession
    private let model: LauncherModel
    private var terminating = false
    init(session: LauncherSession, model: LauncherModel) {
        self.session = session
        self.model = model
    }
    private var statusItem: NSStatusItem?
    private let popover = NSPopover()
    private let panelDismissal = PopoverDismissal()
    private lazy var statusInterface = StatusItemInterface(show: { [weak self] in self?.showPanel() },
        hide: { [weak self] in self?.popover.performClose(nil) })
    private var setupWindow: NSWindow?
    private var statusWindow: NSWindow?
    private var notesWindow: NSWindow?
    private var offeredWindow: NSWindow?
    private var wakeObserver: NSObjectProtocol?
    private var nativeNotifications: NativeUpdateNotifications?
    private var updateNotices: UpdateNotices?
    private var termination: DispatchSourceSignal?
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        // A rollback stops this app with SIGTERM; quitting through AppKit stops the engine first.
        signal(SIGTERM, SIG_IGN)
        let termination = DispatchSource.makeSignalSource(signal: SIGTERM, queue: .main)
        termination.setEventHandler { AppQuit.request() }
        termination.resume()
        self.termination = termination
        NSApp.mainMenu = AppMenu.make(model.copy)
        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        item.autosaveName = "RoleBandLauncher"
        statusItem = item
        if !statusInterface.install(on: item) {
            item.button?.target = self
            item.button?.action = #selector(togglePanel)
        }
        model.changed = { [weak self] in self?.updateIcon() }
        popover.behavior = .transient
        popover.delegate = self
        popover.contentViewController = NSHostingController(rootView: MainPanel(model: model,
            notes: { [weak self] in self?.showNotes() }, offered: { [weak self] in self?.showOffered() },
            setup: { [weak self] in self?.showSetup() }))
        updateIcon()
        session.launch()
        let native = NativeUpdateNotifications(copy: model.copy) { [weak self] version in
            guard let self else { return }
            if self.model.updates.offered?.version == version,
               self.model.updates.offersUpdate(launcher: self.model.launcherVersion, engine: self.model.verified?.engineVersion) {
                self.showOffered()
            } else { self.showAbout() }
        }
        nativeNotifications = native
        let eligible: (String) -> Bool = { [weak model] version in
            guard let model else { return false }
            return model.updates.automatic && model.updates.notices && model.updates.offered?.version == version &&
                model.updates.offersUpdate(launcher: model.launcherVersion, engine: model.verified?.engineVersion)
        }
        let notices = UpdateNotices(authorize: { [weak model] in
            let allowed = await native.authorize()
            model?.updates.notificationsDenied = await native.denied()
            return allowed
        }, deliver: { [weak model] version in
            model?.updates.notificationsDenied = await native.denied()
            return try await native.deliver(version: version, ifEligible: { eligible(version) })
        },
            eligible: eligible)
        updateNotices = notices
        model.updates.automaticChoiceChanged = { [weak notices] in notices?.automaticChoiceChanged($0) }
        model.updates.noticesChanged = { [weak notices, weak model] enabled in
            notices?.automaticChoiceChanged(enabled && model?.updates.automatic == true)
        }
        model.updates.didCheck = { [weak notices] release, automatic in
            Task { await notices?.checked(version: release.version, automatic: automatic) }
        }
        model.updates.start()
        wakeObserver = NSWorkspace.shared.notificationCenter.addObserver(forName: NSWorkspace.didWakeNotification, object: nil, queue: .main) { [weak self] _ in
            Task { @MainActor in self?.model.refresh(); self?.model.updates.start() }
        }
        if model.shouldShowSetupAtLaunch { showSetup() }
    }
    private func updateIcon() {
        let title = "RoleBand: \(model.text(model.titleKey))"
        statusItem?.button?.image = BrandGlyph.menuBar(badge: model.menuBarBadge)
        statusItem?.button?.setAccessibilityLabel(title)
        statusItem?.button?.toolTip = title
    }
    @objc private func togglePanel() {
        if popover.isShown { popover.performClose(nil) } else { showPanel() }
    }
    private func showPanel() {
        guard let button = statusItem?.button else { showSetup(); return }
        let anchor = statusInterface.installed ? nil : PopoverDismissal.visibleFrame(of: button)
        guard PanelPlacement.of(expandedInterface: statusInterface.installed, active: statusInterface.active,
                                anchor: anchor) == .popover else { showStatusWindow(); return }
        statusWindow?.close()
        NSApp.activate()
        popover.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)
        popover.contentViewController?.view.window?.makeKeyAndOrderFront(nil)
        if !statusInterface.installed { panelDismissal.watch(popover, anchoredTo: button) }
        model.panelShown()
    }
    private func showSetup() {
        guard model.ownsEngine else { return }
        statusWindow?.close()
        popover.closeAtOnce()
        if setupWindow?.isVisible != true { model.prepareSetup() }
        NSApp.setActivationPolicy(.regular)
        if setupWindow == nil {
            let window = LauncherWindow(contentRect: NSRect(x: 0, y: 0, width: 540, height: 452),
                                  styleMask: [.titled, .closable, .miniaturizable], backing: .buffered, defer: false)
            window.title = Bundle.main.object(forInfoDictionaryKey: "CFBundleDisplayName") as? String ?? "RoleBand Launcher"
            window.isReleasedWhenClosed = false
            window.delegate = self
            window.contentViewController = NSHostingController(rootView: SetupView(model: model, close: { [weak self] in
                self?.setupWindow?.close()
                if self?.model.step != .done { self?.showPanel() }
            }))
            window.center()
            setupWindow = window
        }
        model.refreshLogin()
        NSApp.activate()
        setupWindow?.makeKeyAndOrderFront(nil)
        model.setSetupVisible(true)
    }
    private func showStatusWindow() {
        popover.closeAtOnce()
        NSApp.setActivationPolicy(.regular)
        if statusWindow == nil {
            let window = LauncherWindow(contentRect: NSRect(x: 0, y: 0, width: PanelMetrics.width, height: 560),
                                        styleMask: [.titled, .closable, .miniaturizable], backing: .buffered, defer: false)
            window.title = "RoleBand"
            window.isReleasedWhenClosed = false
            window.delegate = self
            window.contentViewController = NSHostingController(rootView: ScrollView {
                MainPanel(model: model, notes: { [weak self] in self?.showNotes() }, offered: { [weak self] in self?.showOffered() },
                          setup: { [weak self] in self?.showSetup() })
            })
            window.center()
            statusWindow = window
        }
        NSApp.activate()
        statusWindow?.makeKeyAndOrderFront(nil)
        model.panelShown()
    }
    private func showNotes() {
        popover.closeAtOnce()
        statusWindow?.close()
        NSApp.setActivationPolicy(.regular)
        if notesWindow == nil {
            let window = LauncherWindow(contentRect: NSRect(x: 0, y: 0, width: 640, height: 640),
                                        styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
            window.title = model.text("notes-title")
            window.isReleasedWhenClosed = false
            window.delegate = self
            window.contentViewController = NSHostingController(rootView: ReleaseNotesView(model: model, close: { [weak self] in self?.notesWindow?.close() }))
            window.setContentSize(NSSize(width: 640, height: 640))
            window.center()
            notesWindow = window
        }
        model.setNotesVisible(true)
        model.refresh(includeNotes: true)
        NSApp.activate()
        notesWindow?.makeKeyAndOrderFront(nil)
    }
    func popoverDidClose(_ notification: Notification) {
        panelDismissal.stop()
        statusInterface.cancel()
        model.panelOpen = statusWindow?.isVisible == true
    }
    /// A notice that no longer leads to an offer, because it was installed or withdrawn, opens the
    /// panel where updates are checked.
    private func showAbout() {
        model.panelTab = .about
        showPanel()
    }
    private func showOffered() {
        guard let release = model.updates.offered else { return }
        popover.closeAtOnce()
        statusWindow?.close()
        offeredWindow?.close()
        NSApp.setActivationPolicy(.regular)
        let window = LauncherWindow(contentRect: NSRect(x: 0, y: 0, width: 640, height: 640),
                                    styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = model.text("notes-title")
        window.isReleasedWhenClosed = false
        window.delegate = self
        // Updating closes the window and opens the panel, where the update shows its progress.
        let install = model.installer.map { installer in
            { [weak self] in
                installer.install(release.version)
                self?.offeredWindow?.close()
                self?.showPanel()
            }
        }
        window.contentViewController = NSHostingController(rootView: OfferedReleaseView(release: release, copy: model.copy, demo: UpdateDemo.active,
            openPage: { NSWorkspace.shared.open(release.page) }, close: { [weak self] in self?.offeredWindow?.close() },
            install: install))
        window.center()
        offeredWindow = window
        NSApp.activate()
        window.makeKeyAndOrderFront(nil)
    }
    func windowShouldClose(_ sender: NSWindow) -> Bool {
        sender !== setupWindow || !model.completingSetup
    }
    func windowWillClose(_ notification: Notification) {
        if let window = notification.object as? NSWindow, window === notesWindow {
            model.setNotesVisible(false)
        }
        if let window = notification.object as? NSWindow, window === setupWindow {
            model.setSetupVisible(false)
            model.dismissSetup()
        }
        model.panelOpen = statusWindow?.isVisible == true && notification.object as? NSWindow !== statusWindow
        let closing = notification.object as? NSWindow
        if ![setupWindow, statusWindow, notesWindow, offeredWindow].contains(where: { $0 !== closing && $0?.isVisible == true }) {
            NSApp.setActivationPolicy(.accessory)
        }
    }
    func applicationDidBecomeActive(_ notification: Notification) {
        if let nativeNotifications {
            Task { [weak model] in model?.updates.notificationsDenied = await nativeNotifications.denied() }
        }
        model.refreshLogin()
        model.becameActive()
        if popover.isShown { popover.contentViewController?.view.window?.makeKeyAndOrderFront(nil) }
    }
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        if notesWindow?.isVisible == true { notesWindow?.makeKeyAndOrderFront(nil) }
        else if offeredWindow?.isVisible == true { offeredWindow?.makeKeyAndOrderFront(nil) }
        else if setupWindow?.isVisible == true { setupWindow?.makeKeyAndOrderFront(nil) }
        else if model.ownsEngine && !model.setupCompleted { showSetup() }
        else { showStatusWindow() }
        return true
    }
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard !terminating else { return .terminateLater }
        terminating = true
        // Stopping the engine takes seconds; an open panel would sit frozen over a menu bar item
        // that macOS may already have hidden.
        popover.close()
        Task {
            let stopped = await session.shutdown()
            terminating = false
            sender.reply(toApplicationShouldTerminate: stopped)
            if !stopped { showStatusWindow() }
        }
        return .terminateLater
    }
    func applicationWillTerminate(_ notification: Notification) {
        panelDismissal.stop()
        statusInterface.cancel()
        model.stop()
        model.updates.stop()
        if let wakeObserver { NSWorkspace.shared.notificationCenter.removeObserver(wakeObserver) }
    }
}
