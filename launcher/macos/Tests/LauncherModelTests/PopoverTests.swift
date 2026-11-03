import AppKit
import Testing
@testable import RoleBandLauncher

@MainActor
private final class OutsideMouse {
    var callbacks: [PopoverDismissal.Action] = []
    var removals = 0
    func watch(_ action: @escaping PopoverDismissal.Action) -> (() -> Void) {
        callbacks.append(action)
        return { self.removals += 1 }
    }
}

@MainActor
@Test func anOutsideClickClosesThePopoverAndRemovesItsWatchExactlyOnce() {
    let outside = OutsideMouse()
    let dismissal = PopoverDismissal(watchOutside: outside.watch)
    var closes = 0
    dismissal.start(anchor: { NSRect(x: 400, y: 880, width: 24, height: 24) }, close: { closes += 1 })
    #expect(closes == 0 && outside.callbacks.count == 1)
    dismissal.checkAnchor()
    #expect(closes == 0)
    outside.callbacks[0]()
    #expect(closes == 1 && outside.removals == 1)
    outside.callbacks[0]()
    dismissal.stop()
    #expect(closes == 1 && outside.removals == 1)
}

@MainActor
@Test(arguments: ["collapsed", "moved", "removed"])
func aPopoverClosesWhenItsMenuBarAnchorDisappearsOrMoves(change: String) {
    let outside = OutsideMouse()
    let dismissal = PopoverDismissal(watchOutside: outside.watch)
    var anchor: NSRect? = NSRect(x: 400, y: 880, width: 24, height: 24)
    var closes = 0
    dismissal.start(anchor: { anchor }, close: { closes += 1 })
    if change == "collapsed" { anchor = NSRect(x: -1000, y: 880, width: 24, height: 24) }
    else if change == "moved" { anchor?.origin.x = 500 }
    else { anchor = nil }
    dismissal.checkAnchor()
    #expect(closes == 1 && outside.removals == 1)
    dismissal.checkAnchor()
    #expect(closes == 1)
}

@MainActor
@Test func reopeningReplacesTheWatchAndAnUnavailableAnchorNeverLeavesAPopoverOpen() {
    let outside = OutsideMouse()
    let dismissal = PopoverDismissal(watchOutside: outside.watch)
    var closes = 0
    let anchor = NSRect(x: 400, y: 880, width: 24, height: 24)
    dismissal.start(anchor: { anchor }, close: { closes += 1 })
    dismissal.stop()
    dismissal.start(anchor: { anchor }, close: { closes += 1 })
    #expect(outside.callbacks.count == 2 && outside.removals == 1 && closes == 0)
    outside.callbacks[0]()
    #expect(closes == 0 && outside.removals == 1)
    outside.callbacks[1]()
    #expect(closes == 1 && outside.removals == 2)
    dismissal.start(anchor: { nil }, close: { closes += 1 })
    #expect(closes == 2 && outside.callbacks.count == 2 && outside.removals == 2)
}

/// A 14-inch notched display: the menu bar's unobscured areas leave a housing between x 662 and 850.
private let notched = MenuBarScreen(frame: NSRect(x: 0, y: 0, width: 1512, height: 982),
    housing: MenuBarScreen.housing(frame: NSRect(x: 0, y: 0, width: 1512, height: 982),
                                   left: NSRect(x: 0, y: 950, width: 662, height: 32),
                                   right: NSRect(x: 850, y: 950, width: 662, height: 32)))

@MainActor
@Test func aMenuBarButtonBehindTheCameraHousingOrOffScreenHasNoAnchor() {
    #expect(notched.housing == NSRect(x: 662, y: 950, width: 188, height: 32))
    let beside = NSRect(x: 900, y: 954, width: 24, height: 24)
    #expect(PopoverDismissal.visible(beside, on: [notched]) == beside)
    #expect(PopoverDismissal.visible(NSRect(x: 740, y: 954, width: 24, height: 24), on: [notched]) == nil)
    #expect(PopoverDismissal.visible(NSRect(x: -1000, y: 954, width: 24, height: 24), on: [notched]) == nil)
    let plain = MenuBarScreen(frame: NSRect(x: 0, y: 0, width: 1512, height: 982), housing: nil)
    #expect(PopoverDismissal.visible(NSRect(x: 740, y: 954, width: 24, height: 24), on: [plain]) != nil)
}

@MainActor
@Test func aNotchedDisplayBesideTheMainOneFindsItsHousingInGlobalCoordinates() {
    let frame = NSRect(x: -1512, y: 0, width: 1512, height: 982)
    let fromDisplay = MenuBarScreen.housing(frame: frame, left: NSRect(x: 0, y: 950, width: 662, height: 32),
                                            right: NSRect(x: 850, y: 950, width: 662, height: 32))
    let fromGlobal = MenuBarScreen.housing(frame: frame, left: NSRect(x: -1512, y: 950, width: 662, height: 32),
                                           right: NSRect(x: -662, y: 950, width: 662, height: 32))
    #expect(fromDisplay == NSRect(x: -850, y: 950, width: 188, height: 32))
    #expect(fromGlobal == fromDisplay)
    #expect(MenuBarScreen.housing(frame: frame, left: nil, right: nil) == nil)
}

@Test func aHiddenMenuBarButtonOpensTheStatusWindowInsteadOfAPopoverThatClosesAtOnce() {
    let anchor = NSRect(x: 900, y: 954, width: 24, height: 24)
    #expect(PanelPlacement.of(expandedInterface: false, active: false, anchor: anchor) == .popover)
    #expect(PanelPlacement.of(expandedInterface: false, active: false, anchor: nil) == .window)
    #expect(PanelPlacement.of(expandedInterface: true, active: true, anchor: nil) == .popover)
    #expect(PanelPlacement.of(expandedInterface: true, active: false, anchor: anchor) == .window)
}

/// A popover shown from a small window, as the panel is shown from its menu-bar button.
@MainActor private func shownPopover() -> (NSPopover, NSWindow) {
    _ = NSApplication.shared
    let anchor = NSWindow(contentRect: NSRect(x: 200, y: 200, width: 40, height: 40), styleMask: [.borderless],
                          backing: .buffered, defer: false)
    anchor.isReleasedWhenClosed = false
    anchor.orderFront(nil)
    let popover = NSPopover()
    popover.behavior = .transient
    let content = NSViewController()
    content.view = NSView(frame: NSRect(x: 0, y: 0, width: 200, height: 120))
    popover.contentViewController = content
    popover.show(relativeTo: anchor.contentView!.bounds, of: anchor.contentView!, preferredEdge: .minY)
    return (popover, anchor)
}

@MainActor
@Test func thePanelIsGoneBeforeAWindowOpensFromItSoItCannotBlinkOverThatWindow() {
    let (fading, fadingAnchor) = shownPopover()
    #expect(fading.isShown)
    fading.performClose(nil)
    #expect(fading.isShown, "the animated close leaves the panel shown while it fades")
    fading.closeAtOnce()
    fadingAnchor.close()

    let (popover, anchor) = shownPopover()
    defer { anchor.close() }
    #expect(popover.isShown)
    popover.closeAtOnce()
    #expect(!popover.isShown)
    #expect(popover.animates, "the next close from the menu-bar item still fades")
}
