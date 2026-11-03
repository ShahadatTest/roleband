import AppKit
import Foundation
import LauncherCore

struct OwnedEngineSnapshot: Equatable, Sendable {
    var state: HostState
    var diagnostics = ""
    var preparation: EnginePreparation?
}

/// The process boundary stays injectable; the model and its lifecycle remain real in tests.
struct OwnedEngineService: Sendable {
    var start: @Sendable () async throws -> Void
    var restart: @Sendable () async throws -> Void
    var stop: @Sendable () async throws -> Void
    var snapshot: @Sendable () async -> OwnedEngineSnapshot

    static func live(_ configuration: HostConfiguration) -> Self {
        let host = EngineHost(configuration: configuration)
        let tails = DiagnosticTails { await host.diagnosticLines() }
        return Self(start: { try await host.start() }, restart: { try await host.restart() },
                    stop: { try await host.stop() }, snapshot: {
            let state = await host.state
            return OwnedEngineSnapshot(state: state, diagnostics: await tails.lines(for: state), preparation: await host.preparation)
        })
    }

    static var unavailable: Self {
        Self(start: { throw HostProblem.invalidConfiguration }, restart: { throw HostProblem.invalidConfiguration },
             stop: {}, snapshot: { OwnedEngineSnapshot(state: .needsAttention) })
    }
}

/// The engine's log tails, read once each time the host enters needs-attention. Nothing runs
/// while it stays there, so the logs do not change, and the snapshot is taken every second.
actor DiagnosticTails {
    private let read: @Sendable () async -> String
    private var lines: String?
    init(read: @escaping @Sendable () async -> String) { self.read = read }

    func lines(for state: HostState) async -> String {
        guard state == .needsAttention else { lines = nil; return "" }
        if let lines { return lines }
        let tails = await read()
        lines = tails
        return tails
    }
}

@MainActor
final class LauncherSession {
    let mode: LaunchMode
    let model: LauncherModel?

    init(mode: LaunchMode, dependencies: () -> LauncherDependencies) {
        self.mode = mode
        switch mode {
        case .moveToApplications, .databaseOwnedElsewhere:
            model = nil
        case .attach, .owned:
            var dependencies = dependencies()
            dependencies.mode = mode
            model = LauncherModel(dependencies)
        }
    }

    func launch() { model?.launch() }
    func shutdown() async -> Bool { await model?.shutdown() ?? true }
}

/// The menu bar while one of this app's windows is in front. Besides Quit it carries the standard
/// Edit and Window items, so Command-W closes a window, Command-M minimizes it and Command-C copies
/// selected diagnostics or release notes.
@MainActor
enum AppMenu {
    static func make(_ copy: LauncherCopy) -> NSMenu {
        func item(_ key: String, _ action: Selector, _ shortcut: String) -> NSMenuItem {
            NSMenuItem(title: copy.text(key), action: action, keyEquivalent: shortcut)
        }
        func section(_ title: String, _ items: [NSMenuItem]) -> NSMenuItem {
            let menu = NSMenu(title: title)
            items.forEach(menu.addItem)
            let entry = NSMenuItem(title: title, action: nil, keyEquivalent: "")
            entry.submenu = menu
            return entry
        }
        let quit = item("quit", #selector(NSApplication.terminate(_:)), "q")
        quit.target = NSApp
        let bar = NSMenu()
        bar.addItem(section("RoleBand", [quit]))
        bar.addItem(section(copy.text("menu-edit"), [
            item("menu-cut", #selector(NSText.cut(_:)), "x"), item("menu-copy", #selector(NSText.copy(_:)), "c"),
            item("menu-paste", #selector(NSText.paste(_:)), "v"), item("menu-select-all", #selector(NSText.selectAll(_:)), "a"),
        ]))
        bar.addItem(section(copy.text("menu-window"), [
            item("menu-minimize", #selector(NSWindow.performMiniaturize(_:)), "m"),
            item("menu-close", #selector(NSWindow.performClose(_:)), "w"),
        ]))
        return bar
    }
}

/// Quits through AppKit from code that is not handling an event. AppKit waits for
/// `applicationShouldTerminate`'s shutdown task in a nested run loop, and that loop cannot run main
/// actor work while it is itself inside main queue work (a task, a dispatch block or a dispatch
/// source handler): the shutdown never runs and the quit never finishes. A run loop block is
/// outside the main queue, so the quit starts from one.
enum AppQuit {
    static func request(_ quit: @escaping @MainActor () -> Void = { NSApp.terminate(nil) }) {
        RunLoop.main.perform(inModes: [.common]) { MainActor.assumeIsolated(quit) }
    }
}
