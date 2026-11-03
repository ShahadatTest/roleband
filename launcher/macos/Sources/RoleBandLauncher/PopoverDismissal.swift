import AppKit

@MainActor
final class PopoverDismissal {
    typealias Action = @MainActor @Sendable () -> Void
    typealias WatchOutside = @MainActor (@escaping Action) -> (() -> Void)

    private let watchOutside: WatchOutside
    private var removeWatch: (() -> Void)?
    private var timer: Timer?
    private var anchor: (() -> NSRect?)?
    private var originalFrame: NSRect?
    private var close: (() -> Void)?
    private var generation = 0

    init(watchOutside: @escaping WatchOutside = PopoverDismissal.systemWatch) {
        self.watchOutside = watchOutside
    }

    func watch(_ popover: NSPopover, anchoredTo view: NSView) {
        let anchor = WeakAnchor(view: view, popover: popover)
        start(anchor: anchor.frame, close: anchor.close)
    }

    /// Where a menu-bar button sits on screen, or nil when the person cannot see it: its window is
    /// hidden or off every screen, or a notched display's camera housing covers it.
    static func visibleFrame(of view: NSView) -> NSRect? {
        guard let window = view.window, window.isVisible,
              !view.isHiddenOrHasHiddenAncestor, !view.visibleRect.isEmpty else { return nil }
        let frame = window.convertToScreen(view.convert(view.bounds, to: nil))
        return visible(frame, on: NSScreen.screens.map(MenuBarScreen.init))
    }

    static func visible(_ frame: NSRect, on screens: [MenuBarScreen]) -> NSRect? {
        guard !frame.isEmpty, let screen = screens.first(where: { $0.frame.intersects(frame) }) else { return nil }
        if let housing = screen.housing, housing.contains(NSPoint(x: frame.midX, y: frame.midY)) { return nil }
        return frame
    }

    func start(anchor: @escaping () -> NSRect?, close: @escaping () -> Void) {
        stop()
        guard let frame = anchor() else { close(); return }
        self.anchor = anchor
        self.originalFrame = frame
        self.close = close
        let generation = generation
        removeWatch = watchOutside { [weak self] in
            guard let self, self.generation == generation else { return }
            self.dismiss()
        }
        // Menu-bar managers can move the positioning window off screen without removing it.
        let timer = Timer(timeInterval: 0.2, repeats: true) { [weak self] timer in
            guard let self else { timer.invalidate(); return }
            Task { @MainActor in self.checkAnchor() }
        }
        RunLoop.main.add(timer, forMode: .common)
        self.timer = timer
    }

    func checkAnchor() {
        guard let anchor else { return }
        if anchor() != originalFrame { dismiss() }
    }

    func stop() {
        generation &+= 1
        removeWatch?()
        removeWatch = nil
        timer?.invalidate()
        timer = nil
        anchor = nil
        originalFrame = nil
        close = nil
    }

    private func dismiss() {
        let close = close
        stop()
        close?()
    }

    private static func systemWatch(_ action: @escaping Action) -> (() -> Void) {
        // Transient popovers can stay open for clicks on other menus and nonactivating panels.
        let mouse = NSEvent.addGlobalMonitorForEvents(matching: [.leftMouseDown, .rightMouseDown, .otherMouseDown]) { _ in
            Task { @MainActor in action() }
        }
        let resign = NotificationCenter.default.addObserver(forName: NSApplication.didResignActiveNotification,
                                                            object: NSApp, queue: .main) { _ in
            Task { @MainActor in action() }
        }
        return {
            if let mouse { NSEvent.removeMonitor(mouse) }
            NotificationCenter.default.removeObserver(resign)
        }
    }
}

extension NSPopover {
    /// Closes without the fade. A window opened during the fade appears under the closing popover
    /// until the fade ends, so the panel blinks over it.
    func closeAtOnce() {
        let animates = animates
        self.animates = false
        close()
        self.animates = animates
    }
}

/// The button and popover a watch refers to, held weakly. Closures that capture them weakly here
/// crash the optimizer of a release build (its AllocBoxToStack pass); methods keep the same references.
@MainActor
private final class WeakAnchor {
    weak var view: NSView?
    weak var popover: NSPopover?

    init(view: NSView, popover: NSPopover) {
        self.view = view
        self.popover = popover
    }

    func frame() -> NSRect? { view.flatMap(PopoverDismissal.visibleFrame) }
    func close() { popover?.performClose(nil) }
}

struct MenuBarScreen: Equatable {
    let frame: NSRect
    /// The camera housing in global coordinates, on a display that has one.
    let housing: NSRect?

    init(frame: NSRect, housing: NSRect?) {
        self.frame = frame
        self.housing = housing
    }

    init(_ screen: NSScreen) {
        self.init(frame: screen.frame,
                  housing: Self.housing(frame: screen.frame, left: screen.auxiliaryTopLeftArea, right: screen.auxiliaryTopRightArea))
    }

    /// The gap between the two unobscured areas beside the housing. AppKit does not say whether those
    /// areas are in global or display coordinates, so one that does not fit the display's global frame
    /// is read as display-relative.
    static func housing(frame: NSRect, left: NSRect?, right: NSRect?) -> NSRect? {
        guard let left, let right else { return nil }
        let global = { (area: NSRect) in
            frame.insetBy(dx: -1, dy: -1).contains(area) ? area : area.offsetBy(dx: frame.minX, dy: frame.minY)
        }
        let l = global(left), r = global(right)
        guard r.minX > l.maxX else { return nil }
        let bottom = min(l.minY, r.minY)
        return NSRect(x: l.maxX, y: bottom, width: r.minX - l.maxX, height: max(l.maxY, r.maxY) - bottom)
    }
}

/// Where the panel opens. With the expanded interface the system opens the popover from the item
/// itself, so every other open uses the window; without it the popover needs a button the person can
/// see, or it would close as soon as it opened.
enum PanelPlacement: Equatable {
    case popover, window

    static func of(expandedInterface installed: Bool, active: Bool, anchor: NSRect?) -> PanelPlacement {
        if installed { return active ? .popover : .window }
        return anchor == nil ? .window : .popover
    }
}
