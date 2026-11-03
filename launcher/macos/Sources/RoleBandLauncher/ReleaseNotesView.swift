import LauncherCore
import SwiftUI

struct ReleaseNotesView: View {
    @ObservedObject var model: LauncherModel
    let close: () -> Void
    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                VStack(alignment: .leading, spacing: 8) {
                    Text(model.text("notes-title")).font(.system(size: 28, weight: .semibold)).accessibilityAddTraits(.isHeader)
                    if let version = model.verified?.engineVersion {
                        HStack {
                            Text(model.text("notes-installed")).foregroundStyle(.secondary)
                            Text(verbatim: version).font(.system(size: 14, weight: .semibold, design: .monospaced))
                        }.accessibilityElement(children: .combine)
                    }
                }
                Spacer()
                Image(nsImage: BrandGlyph.master).renderingMode(.template).resizable().scaledToFit()
                    .frame(width: 52, height: 52).accessibilityHidden(true)
            }.padding(28).frame(maxWidth: .infinity)
                .background(Color(nsColor: .windowBackgroundColor)).zIndex(1)
            Divider()
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    if model.launcherBehind {
                        VStack(alignment: .leading, spacing: 8) {
                            Text(model.text("notes-launcher-behind")).fontWeight(.semibold)
                            Text(model.text("notes-rebuild")).fixedSize(horizontal: false, vertical: true)
                        }.padding(16).background(Color.accentColor.opacity(0.12), in: RoundedRectangle(cornerRadius: 12))
                    }
                    if let release = model.installedNotes {
                        ReleaseBody(notes: release.notes, empty: model.text("notes-empty"))
                    } else if model.notesFailed {
                        Text(model.text("notes-failed"))
                        Button(model.text("retry")) { model.refresh(includeNotes: true) }.disabled(model.checking)
                    } else { ProgressView().accessibilityLabel(model.text("notes-loading")) }
                }.frame(maxWidth: .infinity, alignment: .leading).padding(28)
            }.clipped()
            Divider()
            HStack { Spacer(); Button(model.text("notes-done"), action: close).keyboardShortcut(.defaultAction) }
                .controlSize(.large).padding(20).background(Color(nsColor: .windowBackgroundColor)).zIndex(1)
        }.font(.system(size: 14)).frame(minWidth: 540, idealWidth: 640, minHeight: 420, idealHeight: 640).modifier(LauncherTheme())
            .task(id: model.installedNotes?.version) { model.acknowledgeNotes() }
    }
}
