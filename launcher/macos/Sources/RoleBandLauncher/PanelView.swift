import AppKit
import LauncherCore
import SwiftUI

/// The menu-bar panel: an update line above everything on every tab, the header, the tab strip,
/// the selected tab, and Quit below a hairline.
struct MainPanel: View {
    @ObservedObject var model: LauncherModel
    @ObservedObject var updates: LauncherUpdates
    let notes: () -> Void
    let offered: () -> Void
    let setup: () -> Void

    init(model: LauncherModel, notes: @escaping () -> Void, offered: @escaping () -> Void, setup: @escaping () -> Void = {}) {
        self.model = model
        updates = model.updates
        self.notes = notes
        self.offered = offered
        self.setup = setup
    }

    var body: some View {
        PaletteReader { p in
            VStack(spacing: PanelMetrics.gap) {
                PanelUpdateBanner(model: model, notes: notes, offered: offered)
                PanelHeader(model: model)
                PanelTabStrip(model: model)
                Group {
                    switch model.panelTab {
                    case .scan: ScanTab(model: model, setup: setup)
                    case .settings: SettingsTab(model: model)
                    case .about: AboutTab(model: model, updates: updates, notes: notes)
                    }
                }
                .frame(width: PanelMetrics.contentWidth)
                PanelFooter(model: model)
            }
            .padding(PanelMetrics.inset)
            .frame(width: PanelMetrics.width)
            .fixedSize(horizontal: false, vertical: true)
            .background(PanelSurface(palette: p))
            .tint(p.accent)
        }
    }
}

/// The popover draws its own material and corners. From macOS 26 it hosts content across the
/// whole balloon, so a neutral base over the material reaches the arrow; earlier systems keep
/// the plain popover material.
private struct PanelSurface: View {
    let palette: LaunchPalette
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    var body: some View {
        if #available(macOS 26.0, *) {
            Rectangle()
                .fill(reduceTransparency ? AnyShapeStyle(Color(nsColor: .windowBackgroundColor)) : AnyShapeStyle(.regularMaterial))
                .overlay(Rectangle().fill(palette.base))
                .ignoresSafeArea()
        } else {
            Color.clear
        }
    }
}

private struct PanelHeader: View {
    @ObservedObject var model: LauncherModel
    var body: some View {
        PaletteReader { p in
            VStack(spacing: 3) {
                Image(nsImage: BrandGlyph.menuBar).renderingMode(.template).resizable()
                    .frame(width: 24, height: 24).foregroundStyle(p.accent)
                    .accessibilityLabel(Text(verbatim: "RoleBand")).accessibilityAddTraits(.isHeader)
                // Attach mode on every tab: the engine belongs to the source install, so Quit here
                // leaves it scanning and there is nothing to restart.
                if model.attached {
                    Label(model.text("attached-notice"), systemImage: "link")
                        .labelStyle(GapLabelStyle(gap: 5, iconSize: 9))
                        .font(PanelType.fact).foregroundStyle(p.secondary)
                        .help(model.text("attached-help"))
                }
                if model.preview {
                    Text(model.text("preview")).font(PanelType.fact).foregroundStyle(p.secondary)
                }
            }
            .frame(maxWidth: .infinity)
            .accessibilityElement(children: .combine)
        }
    }
}

private struct PanelTabStrip: View {
    @ObservedObject var model: LauncherModel
    var body: some View {
        PaletteReader { p in
            HStack(spacing: 2) {
                ForEach(PanelTab.allCases) { tab in
                    PanelTabButton(title: model.text(tab.key), symbol: tab.symbol, selected: model.panelTab == tab,
                                   badge: tab == .about && model.panelTab != .about && model.updateAsks,
                                   badgeLabel: model.text("panel-about-offer")) { model.panelTab = tab }
                }
            }
            .padding(4)
            .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(p.card))
            .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).strokeBorder(p.line, lineWidth: PanelMetrics.hairline))
        }
    }
}

private struct PanelTabButton: View {
    let title: String
    let symbol: String
    let selected: Bool
    let badge: Bool
    let badgeLabel: String
    let action: () -> Void
    @ViewState private var hovering = false
    var body: some View {
        PaletteReader { p in
            Button(action: action) {
                HStack(spacing: 6) {
                    Image(systemName: symbol).font(.system(size: 12, weight: .semibold))
                        .overlay(alignment: .topTrailing) {
                            if badge { Circle().fill(p.accent).frame(width: 6, height: 6).offset(x: 3, y: -2) }
                        }
                    Text(title).font(PanelType.control)
                }
                .foregroundStyle(selected ? p.goldText : (hovering ? p.ink : p.secondary))
                .frame(maxWidth: .infinity).frame(height: 28)
                .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(selected ? p.goldWash : (hovering ? p.hover : .clear)))
                .contentShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
            }
            .buttonStyle(.plain).onHover { hovering = $0 }
            .accessibilityLabel(badge ? badgeLabel : title)
            .accessibilityAddTraits(selected ? .isSelected : [])
        }
    }
}

private struct PanelFooter: View {
    @ObservedObject var model: LauncherModel
    var body: some View {
        VStack(spacing: 8) {
            Divider().padding(.horizontal, -PanelMetrics.inset)
            HStack(spacing: 4) {
                Spacer()
                Button { NSApp.terminate(nil) } label: {
                    Label(model.text("quit"), systemImage: "power").labelStyle(GapLabelStyle())
                }
                .buttonStyle(FooterButtonStyle()).keyboardShortcut("q")
                .help(model.ownsEngine ? model.text("host-quit-note") : "")
            }
            .padding(.horizontal, -6)
        }
        .padding(.bottom, -4)
    }
}

/// What the panel is for: the Scan tab's gold action. A status read in flight does not disable it,
/// because opening waits for that read; only an engine that has never answered does.
struct OpenRadarButton: View {
    @ObservedObject var model: LauncherModel
    var body: some View {
        Button { model.open(.radar) } label: {
            Label(model.text("first-open"), systemImage: "arrow.up.right").labelStyle(GapLabelStyle(gap: 6, iconSize: 9))
        }
        .buttonStyle(GoldButtonStyle())
        .disabled(model.verified == nil)
        .help(model.text(model.verified == nil ? "panel-open-radar-waiting" : "panel-open-radar-help"))
    }
}

// MARK: - Update line

extension LauncherModel {
    /// An offer the person can act on: a newer release than this app or its engine.
    var updateOffered: Bool { updates.offersUpdate(launcher: launcherVersion, engine: verified?.engineVersion) }
    /// Something asks the person to decide: the banner is tinted gold and the About tab has a dot.
    /// A newer offer takes the banner from the last update's result, which says nothing about it.
    var updateAsks: Bool { installer?.activity == nil && updateOffered }
}

/// The update above everything, on every tab: the offer, its progress or failure, and the notice
/// on the first open afterwards. Every state is two lines, so the panel keeps its height. Attach
/// mode has no installer: Update opens the release, which says how to update the source install.
private struct PanelUpdateBanner: View {
    @ObservedObject var model: LauncherModel
    let notes: () -> Void
    let offered: () -> Void
    var body: some View {
        if let installer = model.installer {
            InstallerUpdateLine(model: model, installer: installer, notes: notes, offered: offered)
        } else {
            UpdateLine(model: model, updates: model.updates, installer: nil, activity: nil, notes: notes, offered: offered)
        }
    }
}

private struct InstallerUpdateLine: View {
    @ObservedObject var model: LauncherModel
    @ObservedObject var installer: UpdateInstaller
    let notes: () -> Void
    let offered: () -> Void
    var body: some View {
        UpdateLine(model: model, updates: model.updates, installer: installer, activity: installer.activity, notes: notes, offered: offered)
    }
}

private struct UpdateLine: View {
    @ObservedObject var model: LauncherModel
    @ObservedObject var updates: LauncherUpdates
    let installer: UpdateInstaller?
    let activity: UpdateActivity?
    let notes: () -> Void
    let offered: () -> Void
    /// Where the pointer is along the progress line, while it is there.
    @ViewState private var sizeHover: CGFloat?

    private var version: String { installer?.version ?? model.updates.offered?.version ?? "" }

    var body: some View {
        PaletteReader { p in
            if let activity {
                card(tinted: false) { activityRow(activity, p) }
            } else if model.updateOffered {
                card(tinted: true) {
                    switch OfferButton.of(model.updates.offered) {
                    case .install:
                        PanelRow(symbol: "arrow.down.circle.fill", title: model.text("update-ready", ["version": version]), symbolTint: p.accent) {
                            Button(model.text("update-install")) {
                                if let installer { installer.install(version) } else { offered() }
                            }
                            .buttonStyle(PillButtonStyle())
                        } caption: {
                            Button(model.text("notes-title"), action: offered).buttonStyle(LinkButtonStyle())
                        }
                    case .readFirst:
                        PanelRow(symbol: "arrow.down.circle.fill", title: model.text("update-ready", ["version": version]),
                                 caption: model.updates.offered?.published.map {
                                     model.text("update-released", ["date": $0.formatted(.dateTime.day().month(.wide).locale(model.copy.locale))])
                                 }, symbolTint: p.accent) {
                            Button(model.text("update-read-first"), action: offered).buttonStyle(PillButtonStyle())
                        }
                    }
                }
            } else if let notice = model.updateNotice {
                card(tinted: false) { noticeRow(notice, p) }
            }
        }
    }

    private func card<Content: View>(tinted: Bool, @ViewBuilder _ content: () -> Content) -> some View {
        content().panelCard(padded: false, tinted: tinted)
    }

    @ViewBuilder
    private func noticeRow(_ notice: UpdateNotice, _ p: LaunchPalette) -> some View {
        switch notice.kind {
        case .updated:
            PanelRow(symbol: "checkmark.circle.fill", title: model.text("update-updated", ["version": notice.to]), symbolTint: p.cyan) {
                dismiss(p)
            } caption: {
                Button(model.text("notes-title"), action: notes).buttonStyle(LinkButtonStyle())
            }
        case .rolledBack:
            PanelRow(symbol: "arrow.uturn.backward.circle.fill", title: model.text("update-rolled-back", ["version": notice.from]),
                     caption: model.text("update-rolled-back-caption", ["version": notice.to]), symbolTint: p.warning) {
                dismiss(p)
            }
        }
    }

    @ViewBuilder
    private func activityRow(_ activity: UpdateActivity, _ p: LaunchPalette) -> some View {
        switch activity {
        case .downloading(let received, let total):
            downloading(UpdateStep.title(activity, version: version, copy: model.copy), received: received, total: total, p)
        case .verifying, .restarting:
            downloading(UpdateStep.title(activity, version: version, copy: model.copy), received: 1, total: 1, working: true, p)
        case .paused:
            PanelRow(symbol: "wifi.slash", title: model.text("update-paused"), caption: model.text("update-paused-caption")) {
                Button(model.text("update-cancel")) { installer?.cancel() }.buttonStyle(MiniButtonStyle())
            }
        case .failed(let failure):
            failed(failure, p)
        }
    }

    @ViewBuilder
    private func failed(_ failure: UpdateFailure, _ p: LaunchPalette) -> some View {
        let (title, caption, help): (String, String, String?) = switch failure {
        case .download: (model.text("update-download-failed", ["version": version]), model.text("update-download-failed-caption"), nil)
        case .check: (model.text("update-check-failed", ["version": version]), model.text("update-nothing-installed"),
                      model.text("update-check-failed-help"))
        case .space(let required): (model.text("update-no-space"),
                                    model.text("update-no-space-caption", ["size": UpdateSize.bytes(required, locale: model.copy.locale)]),
                                    model.text("update-no-space-help"))
        case .restart: (model.text("update-restart-failed"), model.text("update-nothing-installed"), nil)
        case .signer: (model.text("update-signer-changed", ["version": version]), model.text("update-signer-changed-caption"),
                       model.text("update-signer-changed-help"))
        }
        PanelRow(symbol: "exclamationmark.circle.fill", title: title, caption: caption, symbolTint: p.warning) {
            if failure == .signer, let page = model.updates.offered?.page {
                Button(model.text("update-release-page")) { NSWorkspace.shared.open(page) }.buttonStyle(PillButtonStyle())
            } else {
                Button(model.text("retry")) { installer?.install(version) }.buttonStyle(PillButtonStyle())
            }
        }
        .help(help ?? "")
    }

    /// A full line with a spinner, not a byte count, says the download is done and a later step is at work.
    private func downloading(_ title: String, received: Int64, total: Int64, working: Bool = false, _ p: LaunchPalette) -> some View {
        HStack(spacing: PanelMetrics.rowIconGap) {
            Image(systemName: "arrow.down.circle").font(.system(size: 14, weight: .medium)).foregroundStyle(p.cyan)
                .frame(width: PanelMetrics.rowIcon).accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 3) {
                HStack(alignment: .firstTextBaseline) {
                    Text(title).font(PanelType.row).foregroundStyle(p.ink).lineLimit(1)
                    Spacer(minLength: 6)
                    if working {
                        ProgressView().controlSize(.mini).accessibilityHidden(true)
                    }
                }
                // The megabytes would crowd the title, so they wait on the line for a hover. The
                // padding gives the thin line a target a pointer can find. The label is drawn here,
                // not a system tooltip: a tooltip restarts its delay whenever its text changes,
                // and during a download the text changes several times a second.
                let megabytes = UpdateSize.progress(received: received, total: total, copy: model.copy)
                ProgressLine(fraction: total > 0 ? Double(received) / Double(total) : 0, color: p.cyan, track: p.track)
                    .padding(.vertical, 6).contentShape(Rectangle())
                    .onContinuousHover { phase in
                        if case .active(let point) = phase { sizeHover = point.x } else { sizeHover = nil }
                    }
                    .overlay(alignment: .topLeading) {
                        if let x = sizeHover, let megabytes {
                            GeometryReader { proxy in
                                SizeTip(text: megabytes, palette: p)
                                    .position(x: min(max(x, 44), proxy.size.width - 44), y: -8)
                            }
                            .allowsHitTesting(false)
                        }
                    }
                    .accessibilityValue(megabytes.map { Text($0) }
                        ?? Text((total > 0 ? Double(received) / Double(total) : 0).formatted(.percent.precision(.fractionLength(0)).locale(model.copy.locale))))
                    .padding(.bottom, -6)
            }
            if activity?.inProgress == true {
                Button(model.text("update-cancel")) { installer?.cancel() }.buttonStyle(MiniButtonStyle())
            }
        }
        .padding(.horizontal, PanelMetrics.rowInsetH).padding(.vertical, PanelMetrics.rowInsetV + 1.5)
        .accessibilityElement(children: .contain)
    }

    private func dismiss(_ p: LaunchPalette) -> some View {
        Button { model.dismissUpdateNotice() } label: {
            Image(systemName: "xmark").font(.system(size: 9, weight: .bold))
        }
        .buttonStyle(MiniButtonStyle(tint: p.secondary)).help(model.text("update-dismiss"))
        .accessibilityLabel(model.text("update-dismiss"))
    }
}

enum UpdateStep {
    /// The title over the progress line. The steps after the download name themselves, so a full
    /// line never reads as a download that stopped.
    static func title(_ activity: UpdateActivity, version: String, copy: LauncherCopy) -> String {
        switch activity {
        case .verifying: copy.text("update-verifying", ["version": version])
        case .restarting: copy.text("update-restarting")
        default: copy.text("update-downloading", ["version": version])
        }
    }
}

/// The download's megabytes under the pointer on the progress line, shaped like a tooltip. Its base
/// is opaque because it sits over the title, and the palette's surfaces are translucent.
private struct SizeTip: View {
    let text: String
    let palette: LaunchPalette
    var body: some View {
        let shape = RoundedRectangle(cornerRadius: 5, style: .continuous)
        Text(text).font(PanelType.fact).monospacedDigit().foregroundStyle(palette.ink)
            .lineLimit(1).fixedSize()
            .padding(.horizontal, 7).padding(.vertical, 3)
            .background(shape.fill(palette.control).background(shape.fill(Color(nsColor: .windowBackgroundColor))))
            .overlay(shape.strokeBorder(palette.lineStrong, lineWidth: 0.7))
            .shadow(color: .black.opacity(palette.dark ? 0.35 : 0.12), radius: 4, y: 1)
            .accessibilityHidden(true)
    }
}

enum SystemSettings {
    /// This app's own page in Notifications; without `id` the pane opens on its list of apps.
    static let notifications = URL(string: "x-apple.systempreferences:com.apple.Notifications-Settings.extension?id="
                                   + LaunchMode.bundleIdentifier)!
}

enum UpdateSize {
    /// The download's progress in whole megabytes, the unit only once: "31 of 181 MB". Nil until
    /// the size is known, and for the steps after the download.
    static func progress(received: Int64, total: Int64, copy: LauncherCopy) -> String? {
        guard total > 1 else { return nil }
        return copy.text("update-progress", ["received": megabytes(received, unit: false, locale: copy.locale),
                                             "total": megabytes(total, unit: true, locale: copy.locale)])
    }

    static func wholeMegabytes(_ bytes: Int64) -> Double { (Double(max(0, bytes)) / 1_000_000).rounded() }

    static func megabytes(_ bytes: Int64, unit: Bool, locale: Locale) -> String {
        let value = wholeMegabytes(bytes)
        let format = FloatingPointFormatStyle<Double>.number.precision(.fractionLength(0)).locale(locale)
        guard unit else { return value.formatted(format) }
        return Measurement(value: value, unit: UnitInformationStorage.megabytes)
            .formatted(.measurement(width: .abbreviated, usage: .asProvided, numberFormatStyle: format).locale(locale))
    }

    /// A free-space need, as the Finder writes sizes.
    static func bytes(_ bytes: Int64, locale: Locale) -> String {
        bytes.formatted(ByteCountFormatStyle(style: .file, spellsOutZero: false).locale(locale))
    }
}

// MARK: - Tabs

struct SettingsTab: View {
    /// The browser pages the panel links to. The settings page opens on its first tab, so a row
    /// for that tab would repeat All settings.
    static let browserLinks: [(symbol: String, title: String, route: BrowserRoute)] = [
        ("clock", "panel-scan-times", .schedule),
        ("slider.horizontal.3", "panel-all-settings", .settings),
    ]

    @ObservedObject var model: LauncherModel
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionLabel(text: model.text("panel-on-mac"))
            RowGroup { LoginRow(model: model) }
            SectionLabel(text: model.text("panel-in-browser")).padding(.top, 4)
            RowGroup {
                ForEach(Array(Self.browserLinks.enumerated()), id: \.offset) { index, link in
                    if index > 0 { RowDivider() }
                    LinkRow(symbol: link.symbol, title: model.text(link.title), help: model.text("panel-opens-browser")) { model.open(link.route) }
                }
            }
            .disabled(model.verified == nil)
        }
    }
}

/// Open at login in its real states. The setup's At login step reads the same login service.
private struct LoginRow: View {
    @ObservedObject var model: LauncherModel
    private var binding: Binding<Bool> {
        Binding(get: { model.loginState == .on || model.loginState == .approval },
                set: { enabled in Task { await model.setLogin(enabled) } })
    }
    var body: some View {
        PaletteReader { p in
            switch model.loginState {
            case .approval:
                VStack(alignment: .leading, spacing: 6) {
                    PanelRow(symbol: "exclamationmark.circle", title: model.text("first-login-toggle"),
                             caption: model.text("panel-login-approval"), symbolTint: p.warning, captionTint: p.warning) {
                        toggle
                    }
                    Button(model.text("login-settings")) { model.openLoginSettings() }
                        .buttonStyle(MiniButtonStyle())
                        .padding(.leading, PanelMetrics.separatorInset).padding(.bottom, 9).padding(.top, -4)
                }
            default:
                PanelRow(symbol: "person.crop.circle", title: model.text("first-login-toggle"), caption: model.text("first-login-caption"),
                         symbolTint: model.loginState == .on ? p.ink : nil) {
                    toggle
                }
            }
        }
    }
    private var toggle: some View {
        Toggle(model.text("first-login-toggle"), isOn: binding).toggleStyle(InkSwitchStyle()).labelsHidden()
            .disabled(model.loginBusy)
    }
}

private struct AboutTab: View {
    @ObservedObject var model: LauncherModel
    @ObservedObject var updates: LauncherUpdates
    let notes: () -> Void

    var body: some View {
        PaletteReader { p in
            VStack(alignment: .leading, spacing: 8) {
                identity(p)
                SectionLabel(text: model.text("panel-updates")).padding(.top, 4)
                RowGroup {
                    status(p)
                    RowDivider()
                    PanelRow(symbol: "arrow.triangle.2.circlepath", title: model.text("panel-check-automatically"),
                             caption: model.text("panel-check-automatically-caption"), symbolTint: updates.automatic ? p.ink : nil) {
                        Toggle(model.text("panel-check-automatically"),
                               isOn: Binding(get: { updates.automatic }, set: { updates.setAutomaticChecks($0) }))
                            .toggleStyle(InkSwitchStyle()).labelsHidden()
                    }
                    RowDivider()
                    notices(p)
                }
            }
        }
    }

    /// Where updates stand, as a row like the switches under it: what the last check found, and
    /// when. Check now stays on every state, so a failed check is one press from a retry.
    private func status(_ p: LaunchPalette) -> some View {
        let checked = updates.lastSuccess.map {
            model.text("panel-checked", ["time": $0.formatted(.relative(presentation: .named).locale(model.copy.locale))])
        }
        let state = UpdateStatus.of(updates, offered: model.updateOffered ? updates.offered?.version : nil)
        let row: (symbol: String, title: String, caption: String?, tint: Color?) = switch state {
        case .checking: ("arrow.clockwise.circle", model.text("panel-status-checking"), checked, nil)
        case .failed(let rateLimited):
            ("exclamationmark.triangle", model.text("panel-status-failed"),
             rateLimited ? model.text("update-rate-limited") : checked, p.warning)
        case .never: ("circle.dashed", model.text("update-idle"), nil, nil)
        case .offered(let version): ("arrow.down.circle", model.text("update-ready", ["version": version]), checked, p.accent)
        case .current: ("checkmark.circle", model.text("panel-status-up-to-date"), checked, p.ink)
        }
        return PanelRow(symbol: row.symbol, title: row.title, caption: row.caption, symbolTint: row.tint) {
            HStack(spacing: 8) {
                if state == .checking { ProgressView().controlSize(.mini) }
                Button(model.text("update-check-now")) { updates.checkManually() }
                    .buttonStyle(MiniButtonStyle()).disabled(state == .checking)
            }
        }
    }

    /// Turning notices on is the only moment the app asks macOS for permission. If the person
    /// refused it there, the row says so and offers the way back.
    @ViewBuilder
    private func notices(_ p: LaunchPalette) -> some View {
        let toggle = Toggle(model.text("panel-notices"), isOn: Binding(get: { updates.notices }, set: { updates.setNotices($0) }))
            .toggleStyle(InkSwitchStyle()).labelsHidden()
        if updates.notices && updates.notificationsDenied {
            VStack(alignment: .leading, spacing: 6) {
                PanelRow(symbol: "bell.slash", title: model.text("panel-notices"), caption: model.text("panel-notices-refused"),
                         symbolTint: p.warning, captionTint: p.warning) { toggle }
                Button(model.text("update-notification-settings")) {
                    NSWorkspace.shared.open(SystemSettings.notifications)
                }
                .buttonStyle(MiniButtonStyle())
                .padding(.leading, PanelMetrics.separatorInset).padding(.bottom, 9).padding(.top, -4)
            }
        } else {
            PanelRow(symbol: "bell", title: model.text("panel-notices"), caption: model.text("panel-notices-caption"),
                     symbolTint: updates.notices ? p.ink : nil) { toggle }
        }
    }

    private func identity(_ p: LaunchPalette) -> some View {
        HStack(spacing: 11) {
            Image(nsImage: NSApp.applicationIconImage ?? NSImage()).resizable().frame(width: 38, height: 38).accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 2) {
                Text(verbatim: "RoleBand").font(PanelType.title).foregroundStyle(p.ink)
                if let version = model.launcherVersion {
                    Text(model.text("panel-version", ["version": version])).font(PanelType.fact).foregroundStyle(p.secondary)
                }
            }
            Spacer(minLength: 8)
            VStack(alignment: .trailing, spacing: 5) {
                Button(model.text("notes-title"), action: notes).buttonStyle(LinkButtonStyle()).disabled(model.verified == nil)
                if let licences = Self.licences {
                    Button(model.text("panel-licences")) { NSWorkspace.shared.activateFileViewerSelecting([licences]) }
                        .buttonStyle(LinkButtonStyle())
                }
            }
        }
        .panelCard()
    }

    /// The bundled engine's third-party notices, present in a packaged app only.
    private static var licences: URL? {
        guard let resources = Bundle.main.resourceURL else { return nil }
        let folder = resources.appendingPathComponent("python/licenses")
        return FileManager.default.fileExists(atPath: folder.path) ? folder : nil
    }
}

/// Unfinished setup leads back to the setup window from the panel. While the engine waits for
/// setup to begin, the card stands alone: there is no engine yet to report on or to start.
private struct SetupPendingCard: View {
    @ObservedObject var model: LauncherModel
    let setup: () -> Void
    var body: some View {
        PaletteReader { p in
            PanelRow(symbol: "checklist", title: model.text("setup-pending"),
                     caption: model.engineHeld ? model.text("setup-pending-held") : nil, symbolTint: p.accent) {
                Button(model.text("setup-finish"), action: setup).buttonStyle(PillButtonStyle())
            }
            .panelCard(padded: false, tinted: true)
        }
    }
}

/// The scan tab: the scan picture while the engine is healthy and has a scan to draw, otherwise
/// its state, the first model download, the last scan and coverage, Open Radar, Scan now or Stop,
/// Pause, and recovery when the engine needs it.
private struct ScanTab: View {
    @ObservedObject var model: LauncherModel
    let setup: () -> Void
    var body: some View {
        PaletteReader { p in
            TimelineView(.periodic(from: .now, by: 30)) { timeline in
                VStack(alignment: .leading, spacing: 10) {
                    if model.setupPending { SetupPendingCard(model: model, setup: setup) }
                    if !model.engineHeld {
                        if let picture = model.scanPicture, let phase = model.scanPhase {
                            ScanPictureCard(model: model, picture: picture, phase: phase, now: timeline.date)
                            ScanPictureActions(model: model, now: timeline.date)
                        } else {
                            status(p)
                            controls(p, now: timeline.date)
                            schedule(p, now: timeline.date)
                            recovery(p)
                        }
                    }
                    if let key = model.controlMessage {
                        Text(model.text(key)).font(PanelType.fact).foregroundStyle(p.secondary)
                            .fixedSize(horizontal: false, vertical: true).accessibilityAddTraits(.updatesFrequently)
                    }
                }
            }
        }
    }

    private var attention: Bool { model.hostState == .needsAttention || model.hostState == .stopped }

    private func status(_ p: LaunchPalette) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .top, spacing: PanelMetrics.rowIconGap) {
                Image(systemName: model.symbol).font(.system(size: 15, weight: .medium))
                    .foregroundStyle(attention ? p.warning : p.ink).frame(width: PanelMetrics.rowIcon)
                    .accessibilityHidden(true)
                VStack(alignment: .leading, spacing: 2) {
                    Text(model.text(model.titleKey)).font(PanelType.title).foregroundStyle(p.ink)
                    if let key = model.helpKey {
                        Text(model.text(key)).font(PanelType.fact).foregroundStyle(p.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                .accessibilityElement(children: .combine).accessibilityAddTraits(.updatesFrequently)
                Spacer(minLength: 0)
                if let start = model.verified.flatMap({ Stamp.date($0.presentation.activitySince) }), model.verified?.presentation.isActive == true {
                    Text(start, style: .timer).font(.system(size: 12, weight: .medium)).monospacedDigit().foregroundStyle(p.cyan)
                } else if model.checking {
                    ProgressView().controlSize(.mini).accessibilityLabel(model.text("connecting"))
                }
            }
            if let progress = model.preparation, !progress.modelComplete, progress.totalBytes > 0 {
                VStack(alignment: .leading, spacing: 5) {
                    HStack {
                        Text(model.text("first-model")).font(PanelType.control).foregroundStyle(p.ink)
                        Spacer()
                        Text(model.preparationBytes).font(PanelType.fact).monospacedDigit().foregroundStyle(p.cyan)
                    }
                    ProgressLine(fraction: progress.fraction, color: p.cyan, track: p.track)
                    if progress.reason == "offline" {
                        Text(model.text("first-model-offline")).font(PanelType.fact).foregroundStyle(p.secondary)
                    }
                }
                .padding(.leading, PanelMetrics.rowIcon + PanelMetrics.rowIconGap)
            }
            if let status = model.verified?.presentation {
                Divider()
                fact("last-scan", date: Stamp.date(status.lastScanAt), p)
                fact("coverage", date: Stamp.date(status.coverageAt), p)
            } else if let last = model.lastGood {
                Divider()
                fact("checked", date: last.receivedAt, p)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .panelCard()
    }

    private func fact(_ key: String, date: Date?, _ p: LaunchPalette) -> some View {
        HStack(alignment: .firstTextBaseline) {
            Text(model.text(key)).foregroundStyle(p.secondary)
            Spacer()
            if let date {
                Text(date.formatted(.dateTime.month(.abbreviated).day().hour().minute().locale(model.copy.locale))).foregroundStyle(p.ink)
            }
            else { Text(model.text("not-scanned")).foregroundStyle(p.secondary) }
        }
        .font(PanelType.fact)
    }

    /// Restarting a stopped engine is the one thing the tab is for while it needs attention;
    /// otherwise Open Radar leads and the scan controls follow, quiet.
    private func controls(_ p: LaunchPalette, now: Date) -> some View {
        VStack(spacing: 8) {
            if !attention || model.engineActionKey == nil { OpenRadarButton(model: model) }
            scanControls(now: now)
        }
    }

    private func scanControls(now: Date) -> some View {
        HStack(spacing: 8) {
            if attention, let key = model.engineActionKey {
                Button { model.startEngine() } label: {
                    Label(model.text(key), systemImage: "arrow.clockwise").labelStyle(GapLabelStyle())
                }
                .buttonStyle(GoldButtonStyle(busy: model.controlBusy))
                if let directory = model.engineLogDirectory {
                    Button { NSWorkspace.shared.activateFileViewerSelecting([directory]) } label: {
                        Label(model.text("engine-logs"), systemImage: "doc.text").labelStyle(GapLabelStyle())
                    }
                    .buttonStyle(QuietButtonStyle())
                }
            } else {
                if let action = model.scanAction {
                    Button { model.scan(action) } label: {
                        Label(model.text(action == .start ? "scan-now" : "scan-stop"), systemImage: action == .start ? "play.fill" : "stop.fill")
                            .labelStyle(GapLabelStyle())
                    }
                    .buttonStyle(QuietButtonStyle())
                } else if model.verified == nil {
                    Button(model.text("retry")) { model.refresh(includeSchedule: true) }.buttonStyle(QuietButtonStyle())
                    if model.attached, let directory = model.engineLogDirectory {
                        Button(model.text("engine-logs")) { NSWorkspace.shared.activateFileViewerSelecting([directory]) }
                            .buttonStyle(QuietButtonStyle())
                    }
                }
                if let plan = model.scheduleState {
                    if plan.isPaused(at: now) {
                        Button { model.pause(.resume) } label: {
                            Label(model.text("pause-resume"), systemImage: "play").labelStyle(GapLabelStyle())
                        }
                        .buttonStyle(QuietButtonStyle())
                    } else if plan.pausable {
                        Menu {
                            ForEach([PauseAction.hour, .threeHours, .tomorrow], id: \.rawValue) { action in
                                Button(model.text(action.key)) { model.pause(action) }
                            }
                        } label: {
                            Label(model.text("pause-menu"), systemImage: "pause").labelStyle(GapLabelStyle())
                        }
                        .menuStyle(.button).buttonStyle(QuietButtonStyle()).menuIndicator(.hidden)
                        .frame(maxWidth: .infinity)
                    }
                }
            }
        }
        .disabled(model.controlBusy)
        .accessibilityElement(children: .contain)
        .accessibilityValue(model.controlBusy ? model.text("scan-sending") : "")
    }

    @ViewBuilder
    private func schedule(_ p: LaunchPalette, now: Date) -> some View {
        Group {
            if let plan = model.scheduleState {
                if let until = plan.pausedUntil, plan.isPaused(at: now) {
                    HStack(spacing: 4) {
                        Text(model.text("pause-until"))
                        Text(until.formatted(.dateTime.month(.abbreviated).day().hour().minute().locale(model.copy.locale)))
                    }
                    .accessibilityElement(children: .combine)
                } else if !plan.enabled {
                    Text(model.text("pause-off"))
                }
            } else if model.verified != nil {
                Text(model.text(model.scheduleFailed ? "pause-unavailable" : "pause-loading"))
            }
        }
        .font(PanelType.fact).foregroundStyle(p.secondary).fixedSize(horizontal: false, vertical: true)
    }

    /// The engine's own last lines when it stopped and will not restart by itself.
    @ViewBuilder
    private func recovery(_ p: LaunchPalette) -> some View {
        if model.hostState == .needsAttention, !model.diagnosticLines.isEmpty {
            ScrollView {
                Text(verbatim: model.diagnosticLines).font(.system(size: 10, design: .monospaced)).foregroundStyle(p.secondary)
                    .textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading)
            }
            .frame(maxHeight: 120).panelCard()
            .accessibilityLabel(model.text("engine-diagnostics"))
        }
    }
}

/// What the offer's button does. A read-first release opens its notes, where Update installs it.
enum OfferButton: Equatable {
    case install, readFirst
    static func of(_ release: OfferedRelease?) -> OfferButton { release?.beforeYouUpdate == nil ? .install : .readFirst }
}
