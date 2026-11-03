import AppKit
import SwiftUI

/// Panel geometry: as wide as a typical menu-bar panel, with one 12 pt inset and rhythm.
enum PanelMetrics {
    static let width: CGFloat = 332
    static let inset: CGFloat = 12
    static let gap: CGFloat = 12
    static var contentWidth: CGFloat { width - inset * 2 }
    static let cardRadius: CGFloat = 10
    static let controlRadius: CGFloat = 7
    static let controlHeight: CGFloat = 28
    static let hairline: CGFloat = 0.7
    static let rowIcon: CGFloat = 22
    static let rowIconGap: CGFloat = 9
    static let rowInsetH: CGFloat = 10
    static let rowInsetV: CGFloat = 8
    /// Separators start under a row's title, not under its icon.
    static var separatorInset: CGFloat { rowInsetH + rowIcon + rowIconGap }
}

/// AppKit's own sizes: 13 for rows, 12 for controls, 11 for secondary facts and 10 for
/// uppercase group labels.
enum PanelType {
    static let title = Font.system(size: 13, weight: .semibold)
    static let row = Font.system(size: 13, weight: .medium)
    static let control = Font.system(size: 12, weight: .medium)
    static let controlStrong = Font.system(size: 12, weight: .semibold)
    static let fact = Font.system(size: 11)
    static let link = Font.system(size: 11, weight: .medium)
    static let label = Font.system(size: 10, weight: .semibold)
}

/// The panel's tokens beyond the launch windows' palette. Light gold and cyan are a step deeper
/// than the dashboard's because they measure lighter on screen, and every text pair keeps 4.5:1.
extension LaunchPalette {
    private func hex(_ value: UInt32) -> Color {
        Color(.sRGB, red: Double((value >> 16) & 255) / 255,
              green: Double((value >> 8) & 255) / 255, blue: Double(value & 255) / 255, opacity: 1)
    }
    /// The gold of marks and washes; `gold` stays the filled action.
    var accent: Color { hex(dark ? 0xDBCB90 : 0x7C6C22) }
    var goldText: Color { hex(dark ? 0xE8DCAC : 0x5E5113) }
    var goldWash: Color { accent.opacity(dark ? 0.17 : 0.12) }
    var goldLine: Color { accent.opacity(dark ? 0.36 : 0.38) }
    var base: Color { dark ? .black.opacity(0.40) : .white.opacity(0.62) }
    var control: Color { dark ? .white.opacity(0.085) : .black.opacity(0.05) }
    var hover: Color { dark ? .white.opacity(0.06) : .black.opacity(0.045) }
    var track: Color { dark ? .white.opacity(0.10) : .black.opacity(0.08) }
    var sunken: Color { dark ? .black.opacity(0.22) : .black.opacity(0.035) }
    var lineStrong: Color { dark ? .white.opacity(0.20) : .black.opacity(0.16) }
}

struct PaletteReader<Content: View>: View {
    @Environment(\.colorScheme) private var scheme
    @Environment(\.colorSchemeContrast) private var contrast
    @ViewBuilder var content: (LaunchPalette) -> Content
    var body: some View { content(LaunchPalette(dark: scheme == .dark, increasedContrast: contrast == .increased)) }
}

private struct PanelCard: ViewModifier {
    var padded = true
    var tinted = false
    func body(content: Content) -> some View {
        PaletteReader { p in
            let shape = RoundedRectangle(cornerRadius: PanelMetrics.cardRadius, style: .continuous)
            content
                .padding(padded ? 10 : 0)
                .background(shape.fill(tinted ? p.goldWash : p.card))
                .overlay(shape.strokeBorder(tinted ? p.goldLine : p.line, lineWidth: PanelMetrics.hairline))
        }
    }
}

extension View {
    /// One card style for every group: 10 pt corners and a hairline. A tinted card asks something.
    func panelCard(padded: Bool = true, tinted: Bool = false) -> some View {
        modifier(PanelCard(padded: padded, tinted: tinted))
    }
}

/// The uppercase label above a group, outside its card.
struct SectionLabel: View {
    let text: String
    var body: some View {
        PaletteReader { p in
            Text(text.uppercased()).font(PanelType.label).kerning(0.6).foregroundStyle(p.secondary)
                .frame(maxWidth: .infinity, alignment: .leading).padding(.horizontal, 2)
                .accessibilityAddTraits(.isHeader)
        }
    }
}

/// A card of rows; place a `RowDivider` between rows.
struct RowGroup<Content: View>: View {
    @ViewBuilder var content: Content
    var body: some View {
        VStack(spacing: 0) { content }
            .clipShape(RoundedRectangle(cornerRadius: PanelMetrics.cardRadius, style: .continuous))
            .panelCard(padded: false)
    }
}

struct RowDivider: View {
    var body: some View {
        Divider().padding(.leading, PanelMetrics.separatorInset).padding(.trailing, PanelMetrics.rowInsetH)
            .accessibilityHidden(true)
    }
}

/// One row: a fixed icon column, a title with an optional caption, and a trailing control.
struct PanelRow<Trailing: View, Caption: View>: View {
    let symbol: String
    let title: String
    var caption: String? = nil
    var symbolTint: Color? = nil
    var captionTint: Color? = nil
    @ViewBuilder var trailing: Trailing
    @ViewBuilder var captionView: Caption

    var body: some View {
        PaletteReader { p in
            HStack(spacing: PanelMetrics.rowIconGap) {
                Image(systemName: symbol).font(.system(size: 14, weight: .medium))
                    .foregroundStyle(symbolTint ?? p.secondary).frame(width: PanelMetrics.rowIcon)
                    .accessibilityHidden(true)
                VStack(alignment: .leading, spacing: 1) {
                    Text(title).font(PanelType.row).foregroundStyle(p.ink)
                    if let caption {
                        Text(caption).font(PanelType.fact).foregroundStyle(captionTint ?? p.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    captionView
                }
                .accessibilityElement(children: .combine)
                Spacer(minLength: 8)
                trailing
            }
            .padding(.horizontal, PanelMetrics.rowInsetH).padding(.vertical, PanelMetrics.rowInsetV)
            .frame(minHeight: 36).contentShape(Rectangle())
        }
    }
}

extension PanelRow where Caption == EmptyView {
    init(symbol: String, title: String, caption: String? = nil, symbolTint: Color? = nil,
         captionTint: Color? = nil, @ViewBuilder trailing: () -> Trailing) {
        self.init(symbol: symbol, title: title, caption: caption, symbolTint: symbolTint,
                  captionTint: captionTint, trailing: trailing, captionView: { EmptyView() })
    }
}

extension PanelRow {
    init(symbol: String, title: String, symbolTint: Color? = nil,
         @ViewBuilder trailing: () -> Trailing, @ViewBuilder caption: () -> Caption) {
        self.init(symbol: symbol, title: title, caption: nil, symbolTint: symbolTint, captionTint: nil,
                  trailing: trailing, captionView: caption)
    }
}

/// A row that opens a browser page: the whole row is the target.
struct LinkRow: View {
    let symbol: String
    let title: String
    let help: String
    let action: () -> Void
    @ViewState private var hovering = false

    var body: some View {
        PaletteReader { p in
            Button(action: action) {
                PanelRow(symbol: symbol, title: title, caption: nil) {
                    Image(systemName: "arrow.up.right").font(.system(size: 10, weight: .semibold))
                        .foregroundStyle(hovering ? p.ink : p.secondary)
                }
                .background(hovering ? p.hover : .clear)
            }
            .buttonStyle(.plain).onHover { hovering = $0 }.help(help)
        }
    }
}

/// The one filled action on a surface. While a request waits it turns to a gold tint: still
/// readable, plainly not something to press.
struct GoldButtonStyle: ButtonStyle {
    var busy = false
    @Environment(\.isEnabled) private var enabled
    @ViewState private var hovering = false
    func makeBody(configuration: Configuration) -> some View {
        PaletteReader { p in
            let shape = RoundedRectangle(cornerRadius: PanelMetrics.controlRadius, style: .continuous)
            configuration.label.font(PanelType.controlStrong).labelStyle(.titleAndIcon)
                .foregroundStyle(busy ? p.goldText : p.goldInk)
                .frame(maxWidth: .infinity, minHeight: PanelMetrics.controlHeight)
                .background(shape.fill(busy ? p.goldWash : p.gold))
                .overlay(shape.strokeBorder(busy ? p.goldLine : .clear, lineWidth: 0.8))
                .overlay(shape.fill(Color.white.opacity(hovering && !busy && !configuration.isPressed ? (p.dark ? 0.10 : 0.08) : 0)))
                .overlay(shape.fill(Color.black.opacity(configuration.isPressed ? 0.12 : 0)))
                .opacity(busy || enabled ? 1 : 0.45).contentShape(shape).onHover { hovering = $0 }
        }
    }
}

/// A secondary control on the panel surface: Pause, Show logs.
struct QuietButtonStyle: ButtonStyle {
    @Environment(\.isEnabled) private var enabled
    @ViewState private var hovering = false
    func makeBody(configuration: Configuration) -> some View {
        PaletteReader { p in
            let shape = RoundedRectangle(cornerRadius: PanelMetrics.controlRadius, style: .continuous)
            configuration.label.font(PanelType.control).labelStyle(.titleAndIcon)
                .foregroundStyle(hovering ? p.ink : p.secondary).padding(.horizontal, 10)
                .frame(maxWidth: .infinity, minHeight: PanelMetrics.controlHeight)
                .background(shape.fill(hovering ? p.control : p.card))
                .overlay(shape.strokeBorder(p.line, lineWidth: 0.8))
                .opacity(configuration.isPressed ? 0.7 : (enabled ? 1 : 0.45)).contentShape(shape)
                .onHover { hovering = $0 }
        }
    }
}

/// A small in-row action such as Check now.
struct MiniButtonStyle: ButtonStyle {
    var tint: Color? = nil
    @Environment(\.isEnabled) private var enabled
    @ViewState private var hovering = false
    func makeBody(configuration: Configuration) -> some View {
        PaletteReader { p in
            let shape = RoundedRectangle(cornerRadius: 5, style: .continuous)
            configuration.label.font(PanelType.link).foregroundStyle(tint ?? p.ink).padding(.horizontal, 8).frame(height: 20)
                .background(shape.fill(hovering ? p.control.opacity(1.6) : p.control))
                .overlay(shape.strokeBorder(p.line, lineWidth: 0.6))
                .opacity(configuration.isPressed ? 0.7 : (enabled ? 1 : 0.45)).contentShape(Rectangle()).onHover { hovering = $0 }
        }
    }
}

/// A gold pill for a choice the person is invited to make, such as installing an update.
struct PillButtonStyle: ButtonStyle {
    @Environment(\.isEnabled) private var enabled
    @ViewState private var hovering = false
    func makeBody(configuration: Configuration) -> some View {
        PaletteReader { p in
            configuration.label.font(.system(size: 11, weight: .semibold)).foregroundStyle(p.goldText)
                .padding(.horizontal, 10).frame(height: 22)
                .background(Capsule(style: .continuous).fill(hovering ? p.accent.opacity(p.dark ? 0.28 : 0.2) : p.goldWash))
                // An opaque base under the wash: on the gold banner two washes would stack and the
                // label would fall under 4.5:1.
                .background(Capsule(style: .continuous).fill(Color(nsColor: .controlBackgroundColor)))
                .overlay(Capsule(style: .continuous).strokeBorder(p.goldLine, lineWidth: 0.7))
                .opacity(configuration.isPressed ? 0.7 : (enabled ? 1 : 0.45)).contentShape(Capsule()).onHover { hovering = $0 }
        }
    }
}

struct LinkButtonStyle: ButtonStyle {
    var font: Font = PanelType.link
    @Environment(\.isEnabled) private var enabled
    @ViewState private var hovering = false
    func makeBody(configuration: Configuration) -> some View {
        PaletteReader { p in
            configuration.label.font(font).foregroundStyle(p.goldText)
                .underline(hovering && enabled, color: p.goldText.opacity(0.6))
                .opacity(configuration.isPressed ? 0.6 : (enabled ? 1 : 0.45)).contentShape(Rectangle()).onHover { hovering = $0 }
        }
    }
}

/// Panel chrome below the content: plain until hovered, so it never competes with actions.
struct FooterButtonStyle: ButtonStyle {
    @Environment(\.isEnabled) private var enabled
    @ViewState private var hovering = false
    func makeBody(configuration: Configuration) -> some View {
        PaletteReader { p in
            configuration.label.font(PanelType.control).foregroundStyle(hovering ? p.ink : p.secondary)
                .padding(.horizontal, 8).frame(height: 24)
                .background(RoundedRectangle(cornerRadius: 6, style: .continuous).fill(hovering ? p.hover : .clear))
                .opacity(configuration.isPressed ? 0.6 : (enabled ? 1 : 0.4)).contentShape(Rectangle())
                .onHover { hovering = $0 }
        }
    }
}

/// On is ink, never gold: a thing's own on/off state. Off is an outlined track with a grey knob,
/// both at 3:1 against the card, so the two differ by more than the knob's side.
struct InkSwitchStyle: ToggleStyle {
    @Environment(\.isEnabled) private var enabled
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    /// The knob jumps instead of sliding when the person turned on Reduce Motion.
    static func animation(reduceMotion: Bool) -> Animation? { reduceMotion ? nil : .snappy(duration: 0.18) }
    func makeBody(configuration: Configuration) -> some View {
        PaletteReader { p in
            let on = configuration.isOn
            Button {
                withAnimation(Self.animation(reduceMotion: reduceMotion)) { configuration.isOn.toggle() }
            } label: {
                ZStack(alignment: on ? .trailing : .leading) {
                    Capsule(style: .continuous).fill(on ? p.ink : .clear)
                        .overlay(Capsule(style: .continuous).strokeBorder(on ? .clear : p.graphic, lineWidth: 1))
                    Circle().fill(on ? (p.dark ? Color(white: 0.11) : .white) : p.graphic).padding(on ? 2 : 3.5)
                }
                .frame(width: 30, height: 17).opacity(enabled ? 1 : 0.55).saturation(enabled ? 1 : 0)
                .contentShape(Capsule())
            }
            .buttonStyle(.plain)
            .accessibilityRepresentation { Toggle(isOn: configuration.$isOn) { configuration.label } }
        }
    }
}

struct ProgressLine: View {
    let fraction: Double
    let color: Color
    let track: Color
    var body: some View {
        GeometryReader { proxy in
            ZStack(alignment: .leading) {
                Capsule().fill(track)
                Capsule().fill(color).frame(width: proxy.size.width * min(max(fraction, 0), 1))
            }
        }
        .frame(height: 3)
    }
}

struct GapLabelStyle: LabelStyle {
    var gap: CGFloat = 6
    var iconSize: CGFloat = 10
    func makeBody(configuration: Configuration) -> some View {
        HStack(spacing: gap) {
            configuration.icon.font(.system(size: iconSize, weight: .semibold))
            configuration.title
        }
    }
}

enum PanelTab: Int, CaseIterable, Identifiable {
    case scan, settings, about
    var id: Int { rawValue }
    var key: String { ["panel-scan", "panel-settings", "panel-about"][rawValue] }
    var symbol: String { ["dot.radiowaves.left.and.right", "gearshape", "info.circle"][rawValue] }
}
