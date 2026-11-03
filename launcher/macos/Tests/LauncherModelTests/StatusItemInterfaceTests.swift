import AppKit
import Testing
@testable import RoleBandLauncher

@MainActor
private final class SystemItem: NSObject {
    @objc weak var expandedInterfaceDelegate: NSObject?
    @objc var expandedInterfaceSession: NSObject?
}

@MainActor
private final class SystemSession: NSObject {
    var cancellations = 0
    @objc func cancel() { cancellations += 1 }
}

@MainActor
@Test func nativeOverflowEndsTheInterfaceEvenWhenTheAnchorGeometryDoesNotChange() {
    let item = SystemItem()
    let session = SystemSession()
    var shown = false
    let interface = StatusItemInterface(show: { shown = true }, hide: { shown = false })
    #expect(interface.install(on: item))
    #expect(item.expandedInterfaceDelegate === interface)
    let begin = NSSelectorFromString("statusItem:didBeginExpandedInterfaceSession:")
    let end = NSSelectorFromString("statusItemDidEndExpandedInterfaceSession:animated:")
    #expect(interface.responds(to: begin) && interface.responds(to: end))
    interface.perform(begin, with: item, with: session)
    #expect(shown && interface.active)
    typealias EndInterface = @convention(c) (AnyObject, Selector, AnyObject, Bool) -> Void
    let endInterface = unsafeBitCast(interface.method(for: end), to: EndInterface.self)
    endInterface(interface, end, item, false)
    #expect(!shown && !interface.active)
    #expect(session.cancellations == 0)
}

@MainActor
@Test func closingThePopoverCancelsItsNativeSessionOnceAndForeignCallbacksAreIgnored() {
    let item = SystemItem()
    let other = SystemItem()
    let session = SystemSession()
    var shows = 0
    var hides = 0
    let interface = StatusItemInterface(show: { shows += 1 }, hide: { hides += 1 })
    #expect(interface.install(on: item))
    interface.didBegin(other, session: session)
    #expect(shows == 0 && !interface.active)
    interface.didBegin(item, session: session)
    interface.didEnd(other, animated: true)
    #expect(shows == 1 && hides == 0 && interface.active)
    interface.cancel()
    interface.cancel()
    #expect(session.cancellations == 1 && !interface.active)
    interface.didEnd(item, animated: true)
    #expect(hides == 1)
}

@MainActor
@Test func aSystemWithoutTheExpandedInterfaceAPIRetainsTheLegacyPopoverPath() {
    let interface = StatusItemInterface(show: { Issue.record("Unexpected show") }, hide: { Issue.record("Unexpected hide") })
    #expect(!interface.install(on: NSObject()))
    #expect(!interface.installed && !interface.active)
    interface.cancel()
}
