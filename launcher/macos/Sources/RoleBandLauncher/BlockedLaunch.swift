import AppKit
import LauncherCore
import SwiftUI

struct LaunchBlock {
    /// An earlier update this app may not finish by itself. `retry` starts its recovery helper again.
    struct StoppedUpdate: Equatable {
        let id: UUID
        let retry: Bool
    }
    let mode: LaunchMode
    let bundle: URL
    let home: URL
    var update: StoppedUpdate?
    var moving: Bool { update == nil && mode == .moveToApplications }
    var size: NSSize {
        if update != nil { return NSSize(width: 480, height: 320) }
        return moving ? NSSize(width: 440, height: 372) : NSSize(width: 480, height: 404)
    }
    var titleKey: String { update != nil ? "update-stopped-title" : moving ? "installer-copy" : "elsewhere-title" }
    var finderFolder: URL { moving ? URL(fileURLWithPath: "/Applications") : HomeLayout(home).data }
    var helperLog: URL { HomeLayout(home).data.appendingPathComponent("logs/update-helper.log") }

    func reveal(select: (URL) -> Void, open: (URL) -> Void) {
        if update != nil { return select(helperLog) }
        if moving { select(bundle) }
        open(finderFolder)
    }
}

struct LaunchPalette {
    let dark: Bool
    var increasedContrast = false
    private func color(_ value: UInt32) -> Color {
        Color(.sRGB, red: Double((value >> 16) & 255) / 255,
              green: Double((value >> 8) & 255) / 255, blue: Double(value & 255) / 255, opacity: 1)
    }
    var ink: Color { color(dark ? 0xECEAE4 : 0x1B1A16) }
    var secondary: Color { color(dark ? (increasedContrast ? 0xDCDAD4 : 0xC8C6C0) : (increasedContrast ? 0x3A3833 : 0x4F4D47)) }
    var graphic: Color { color(dark ? (increasedContrast ? 0xB8B6B0 : 0x9C9A94) : (increasedContrast ? 0x5E5C56 : 0x77756F)) }
    var gold: Color { color(dark ? 0xDBCB90 : 0x6A5C16) }
    var cyan: Color { color(dark ? 0x6FC9E6 : 0x08607D) }
    var warning: Color { color(dark ? 0xEFA85E : 0x7E4309) }
    var goldInk: Color { dark ? color(0x1A1705) : .white }
    var card: Color { dark ? .white.opacity(0.07) : .white.opacity(0.55) }
    var line: Color { dark ? .white.opacity(increasedContrast ? 0.28 : 0.11) : .black.opacity(increasedContrast ? 0.24 : 0.09) }
}

struct LaunchButtonStyle: ButtonStyle {
    let palette: LaunchPalette
    var primary = false
    @Environment(\.isEnabled) private var enabled
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.font(.system(size: 12, weight: primary ? .semibold : .medium))
            .padding(.horizontal, 14).frame(minWidth: primary ? 0 : 92, minHeight: 28)
            .foregroundStyle(primary ? palette.goldInk : palette.ink)
            .background(primary ? palette.gold : palette.card, in: RoundedRectangle(cornerRadius: 7))
            .overlay(RoundedRectangle(cornerRadius: 7).strokeBorder(primary ? .clear : palette.line, lineWidth: 0.7))
            .opacity(configuration.isPressed ? 0.75 : (enabled ? 1 : 0.45))
    }
}

struct BlockedLaunchView: View {
    let block: LaunchBlock
    let copy: LauncherCopy
    let quit: () -> Void
    let reveal: () -> Void
    var retry: () -> Void = {}
    @Environment(\.colorScheme) private var scheme
    @Environment(\.colorSchemeContrast) private var contrast
    private var palette: LaunchPalette { LaunchPalette(dark: scheme == .dark, increasedContrast: contrast == .increased) }

    var body: some View {
        VStack(spacing: 0) {
            if let update = block.update { stoppedContent(update).padding(.bottom, 24) }
            else if block.moving { moveContent } else { elsewhereContent.padding(.bottom, 24) }
            Spacer(minLength: 0)
            Divider()
            HStack(spacing: 8) {
                Button(copy.text("quit"), action: quit)
                    .buttonStyle(LaunchButtonStyle(palette: palette)).keyboardShortcut(.cancelAction)
                Spacer()
                let retrying = block.update?.retry == true
                Button(copy.text("install-reveal"), action: reveal)
                    .buttonStyle(LaunchButtonStyle(palette: palette, primary: !retrying))
                    .keyboardShortcut(retrying ? nil : .defaultAction)
                    .help(copy.text(block.update != nil ? "update-stopped-finder-help"
                                    : block.moving ? "move-finder-help" : "elsewhere-finder-help"))
                if retrying {
                    Button(copy.text("retry"), action: retry)
                        .buttonStyle(LaunchButtonStyle(palette: palette, primary: true)).keyboardShortcut(.defaultAction)
                }
            }.padding(.horizontal, 20).frame(height: 60)
        }.frame(width: block.size.width).frame(minHeight: block.size.height)
            .fixedSize(horizontal: false, vertical: true)
            .foregroundStyle(palette.ink).background(Color(nsColor: .windowBackgroundColor))
    }

    private var moveContent: some View {
        VStack(spacing: 20) {
            HStack(spacing: 18) {
                Image(nsImage: NSWorkspace.shared.icon(forFile: block.bundle.path)).resizable().frame(width: 64, height: 64)
                Image(systemName: "arrow.right").font(.system(size: 17, weight: .semibold)).foregroundStyle(palette.graphic)
                Image(nsImage: NSWorkspace.shared.icon(forFile: "/Applications")).resizable().frame(width: 68, height: 68)
            }.accessibilityHidden(true)
            VStack(spacing: 8) {
                title
                Text(copy.text("move-body")).font(.system(size: 13)).foregroundStyle(palette.secondary)
                    .multilineTextAlignment(.center).fixedSize(horizontal: false, vertical: true)
            }
        }.padding(.top, 52).padding(.horizontal, 40)
    }

    private var elsewhereContent: some View {
        VStack(alignment: .leading, spacing: 18) {
            Image(systemName: "externaldrive.badge.person.crop").font(.system(size: 40))
                .foregroundStyle(palette.graphic).accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 8) {
                title
                Text(copy.text("elsewhere-body")).font(.system(size: 13)).foregroundStyle(palette.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            VStack(spacing: 0) {
                row("elsewhere-keep", caption: "elsewhere-keep-body", symbol: "terminal")
                Divider().padding(.leading, 41).padding(.trailing, 10)
                row("elsewhere-fresh", caption: "elsewhere-fresh-body", symbol: "plus.circle")
            }.background(palette.card, in: RoundedRectangle(cornerRadius: 10))
                .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(palette.line, lineWidth: 0.7))
        }.padding(.top, 44).padding(.horizontal, 32)
    }

    private func stoppedContent(_ update: LaunchBlock.StoppedUpdate) -> some View {
        VStack(alignment: .leading, spacing: 18) {
            Image(systemName: "exclamationmark.arrow.triangle.2.circlepath").font(.system(size: 40))
                .foregroundStyle(palette.warning).accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 8) {
                title
                ForEach(["update-stopped-body", update.retry ? "update-stopped-retry-body" : "update-stopped-unreadable-body"],
                        id: \.self) { key in
                    Text(copy.text(key)).font(.system(size: 13)).foregroundStyle(palette.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }.padding(.top, 44).padding(.horizontal, 32).frame(maxWidth: .infinity, alignment: .leading)
    }

    private var title: some View {
        Text(copy.text(block.titleKey)).font(.system(size: 22, weight: .bold))
            .fixedSize(horizontal: false, vertical: true).accessibilityAddTraits(.isHeader)
    }

    private func row(_ key: String, caption: String, symbol: String) -> some View {
        HStack(spacing: 9) {
            Image(systemName: symbol).font(.system(size: 14)).foregroundStyle(palette.secondary)
                .frame(width: 22).accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 2) {
                Text(copy.text(key)).font(.system(size: 13, weight: .medium))
                Text(copy.text(caption)).font(.system(size: 11)).foregroundStyle(palette.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 0)
        }.padding(.horizontal, 10).padding(.vertical, 8).accessibilityElement(children: .combine)
    }
}

@MainActor
final class BlockedLaunchDelegate: NSObject, NSApplicationDelegate {
    private let block: LaunchBlock
    private let copy = LauncherCopy()
    private let retry: () throws -> Void
    private var window: NSWindow?
    init(block: LaunchBlock, retry: @escaping () throws -> Void = {}) { self.block = block; self.retry = retry }

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        NSApp.mainMenu = AppMenu.make(copy)
        let window = LauncherWindow(contentRect: NSRect(origin: .zero, size: block.size),
                                    styleMask: [.titled, .closable, .miniaturizable], backing: .buffered, defer: false)
        window.title = "RoleBand"
        window.isReleasedWhenClosed = false
        window.contentViewController = NSHostingController(rootView: BlockedLaunchView(block: block, copy: copy,
            quit: { NSApp.terminate(nil) }, reveal: { [block] in
                block.reveal(select: { NSWorkspace.shared.activateFileViewerSelecting([$0]) },
                             open: { NSWorkspace.shared.open($0) })
            }, retry: { [retry] in
                do { try retry(); NSApp.terminate(nil) } catch { NSSound.beep() }
            }))
        if let content = window.contentViewController { window.setContentSize(content.view.fittingSize) }
        window.center()
        self.window = window
        NSApp.activate()
        window.makeKeyAndOrderFront(nil)
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        window?.makeKeyAndOrderFront(nil)
        return false
    }
}
