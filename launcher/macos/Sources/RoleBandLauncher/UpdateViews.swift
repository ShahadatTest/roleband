import AppKit
import LauncherCore
import SwiftUI

// The explicit type alias selects the property wrapper when an SDK also exports a State macro.
typealias ViewState<Value> = SwiftUI.State<Value>

struct OfferedReleaseView: View {
    let release: OfferedRelease
    let copy: LauncherCopy
    var demo = false
    let openPage: () -> Void
    let close: () -> Void
    /// The app's own update, when it owns its engine; nil beside a source checkout, which updates
    /// with its own tools.
    var install: (() -> Void)?
    @ViewState private var instructions = false

    /// The window's default button: Update where the app installs updates, how to update elsewhere.
    var primaryKey: String { install == nil ? "update-how" : "update-install" }
    func primary() {
        if let install { install() } else { instructions = true }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            VStack(alignment: .leading, spacing: 8) {
                Text(copy.text("notes-title")).font(.system(size: 28, weight: .semibold)).accessibilityAddTraits(.isHeader)
                HStack {
                    Text(copy.text("update-offered")).foregroundStyle(.secondary)
                    Text(verbatim: release.version).font(.system(size: 14, weight: .semibold, design: .monospaced))
                }.accessibilityElement(children: .combine)
            }.padding(28).frame(maxWidth: .infinity, alignment: .leading)
                .background(Color(nsColor: .windowBackgroundColor)).zIndex(1)
            Divider()
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    if instructions {
                        VStack(alignment: .leading, spacing: 14) {
                            Text(copy.text("update-how")).fontWeight(.semibold)
                            Text(copy.text("update-engine-instructions"))
                            Text(copy.text("update-launcher-instructions"))
                            Button(copy.text("update-release-page"), action: openPage)
                                .disabled(demo)
                        }.padding(20).background(Color.accentColor.opacity(0.12), in: RoundedRectangle(cornerRadius: 12))
                    }
                    if let notice = release.beforeYouUpdate {
                        HStack(alignment: .top, spacing: 12) {
                            Image(systemName: "exclamationmark.circle.fill").foregroundStyle(.orange).accessibilityHidden(true)
                            VStack(alignment: .leading, spacing: 4) {
                                Text(copy.text("update-before-you-update")).fontWeight(.semibold)
                                Text(verbatim: notice.split(separator: "\n").map { $0.trimmingCharacters(in: .whitespaces) }.joined(separator: " "))
                                    .lineSpacing(4).textSelection(.enabled).fixedSize(horizontal: false, vertical: true)
                            }
                        }.padding(16).frame(maxWidth: .infinity, alignment: .leading)
                            .background(Color.orange.opacity(0.1), in: RoundedRectangle(cornerRadius: 12))
                            .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(Color.orange.opacity(0.3)))
                            .accessibilityElement(children: .combine)
                    }
                    ReleaseBody(notes: release.notes, empty: copy.text("notes-empty"))
                }.frame(maxWidth: .infinity, alignment: .leading).padding(28)
            }.clipped()
            Divider()
            HStack {
                Button(copy.text("update-later"), action: close)
                Spacer()
                Button(copy.text(primaryKey), action: primary).keyboardShortcut(.defaultAction)
            }.controlSize(.large).padding(20).background(Color(nsColor: .windowBackgroundColor)).zIndex(1)
        }.font(.system(size: 14)).frame(minWidth: 540, idealWidth: 640, minHeight: 420, idealHeight: 640).modifier(LauncherTheme())
    }
}

struct ReleaseBody: View {
    let notes: String?
    let empty: String
    var body: some View {
        if let notes, !notes.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            ForEach(Array(notes.replacingOccurrences(of: "\n- ", with: "\n\n- ").components(separatedBy: "\n\n").enumerated()), id: \.offset) { _, paragraph in
                let trimmed = paragraph.trimmingCharacters(in: .whitespacesAndNewlines)
                if trimmed.hasPrefix("#") {
                    let lines = trimmed.split(separator: "\n", maxSplits: 1)
                    Text(verbatim: lines[0].drop(while: { $0 == "#" || $0 == " " }).uppercased())
                        .font(.system(size: 12, weight: .semibold)).foregroundStyle(.secondary).accessibilityAddTraits(.isHeader)
                    if lines.count > 1 { item(String(lines[1])) }
                } else {
                    item(trimmed)
                }
            }
        } else { Text(empty) }
    }

    /// A paragraph, or a bullet when it starts with "- ".
    private func item(_ text: String) -> some View {
        let bullet = text.hasPrefix("- ")
        let clean = (bullet ? String(text.dropFirst(2)) : text).replacingOccurrences(of: "**", with: "")
            .split(separator: "\n").map { $0.trimmingCharacters(in: .whitespaces) }.joined(separator: " ")
        return HStack(alignment: .top, spacing: 12) {
            if bullet { Image(systemName: "plus.circle.fill").foregroundStyle(.tint).accessibilityHidden(true) }
            Text(verbatim: clean).lineSpacing(4).textSelection(.enabled).fixedSize(horizontal: false, vertical: true)
        }
    }
}
