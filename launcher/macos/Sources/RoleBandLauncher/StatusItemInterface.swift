import AppKit
import ObjectiveC

/// Public Objective-C entry points keep the expanded-interface lifecycle available to
/// binaries built with an SDK that does not declare it yet.
@MainActor
final class StatusItemInterface: NSObject {
    private weak var item: NSObject?
    private var session: NSObject?
    private let show: () -> Void
    private let hide: () -> Void
    private(set) var installed = false
    var active: Bool { session != nil }

    init(show: @escaping () -> Void, hide: @escaping () -> Void) {
        self.show = show
        self.hide = hide
    }

    @discardableResult func install(on item: NSObject) -> Bool {
        let setter = NSSelectorFromString("setExpandedInterfaceDelegate:")
        guard item.responds(to: setter), item.responds(to: NSSelectorFromString("expandedInterfaceSession")) else { return false }
        if let lifecycle = NSProtocolFromString("NSStatusItemExpandedInterfaceDelegate") {
            class_addProtocol(Self.self, lifecycle)
        }
        self.item = item
        item.perform(setter, with: self)
        installed = true
        return true
    }

    func cancel() {
        guard let session else { return }
        self.session = nil
        let cancel = NSSelectorFromString("cancel")
        if session.responds(to: cancel) { session.perform(cancel) }
    }

    @objc(statusItem:didBeginExpandedInterfaceSession:)
    func didBegin(_ item: NSObject, session: NSObject) {
        guard item === self.item else { return }
        self.session = session
        show()
    }

    @objc(statusItemDidEndExpandedInterfaceSession:animated:)
    func didEnd(_ item: NSObject, animated: Bool) {
        guard item === self.item else { return }
        session = nil
        hide()
    }
}
