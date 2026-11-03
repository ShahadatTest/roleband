import AppKit
import LauncherCore
import SwiftUI

struct SetupView: View {
    @ObservedObject var model: LauncherModel
    let close: () -> Void
    @Environment(\.colorScheme) private var scheme
    @Environment(\.colorSchemeContrast) private var contrast
    private var palette: LaunchPalette { LaunchPalette(dark: scheme == .dark, increasedContrast: contrast == .increased) }
    private let steps: [SetupStep] = [.welcome, .connection, .login, .done]

    private func stepName(_ step: SetupStep) -> String {
        switch step {
        case .welcome, .installation: "step-welcome"
        case .connection: "first-step-preparing"
        case .login: "step-login"
        case .done: "step-done"
        }
    }
    private var heading: String {
        switch model.step {
        case .welcome, .installation: "first-welcome-title"
        case .connection:
            if model.preparationFailed { "first-failed-title" }
            else if model.preparationReady && model.preparation?.modelComplete == true { "first-prepared-title" }
            else { "first-preparing-title" }
        case .login: "first-login-title"
        case .done: "first-done-title"
        }
    }
    private var subtitle: String {
        switch model.step {
        case .welcome, .installation: "first-welcome-body"
        case .connection:
            if model.preparation?.database == "failed" { "first-database-failed" }
            else if model.preparationFailed { "first-service-failed" }
            else if model.preparationReady && model.preparation?.reason == "offline" { "first-offline-body" }
            else if model.preparationReady && model.preparation?.modelComplete == true { "first-prepared-body" }
            else { "first-preparing-body" }
        case .login: "first-login-body"
        case .done: "first-done-body"
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .top, spacing: 8) {
                ForEach(steps, id: \.rawValue) { step in
                    VStack(alignment: .leading, spacing: 7) {
                        Capsule().fill(step.rawValue <= model.step.rawValue ? palette.gold : palette.line).frame(height: 3)
                        Text(model.text(stepName(step)))
                            .font(.system(size: 11, weight: step == model.step ? .semibold : .regular))
                            .foregroundStyle(step == model.step ? palette.ink : palette.secondary)
                    }.frame(maxWidth: .infinity, alignment: .leading)
                }
            }.padding(.top, 38).padding(.horizontal, 32)
                .accessibilityElement(children: .combine).accessibilityValue(model.text(stepName(model.step)))
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    VStack(alignment: .leading, spacing: 6) {
                        Text(model.text(heading)).font(.system(size: 22, weight: .bold))
                            .fixedSize(horizontal: false, vertical: true).accessibilityAddTraits(.isHeader)
                        Text(model.text(subtitle)).font(.system(size: 13)).foregroundStyle(palette.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    content
                }.padding(.horizontal, 32).padding(.top, 28).padding(.bottom, 20)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }.id(model.step.id)
            Divider()
            footer.padding(.horizontal, 20).frame(height: 60)
        }.frame(width: 540, height: 452).foregroundStyle(palette.ink)
            .background(Color(nsColor: .windowBackgroundColor)).modifier(LauncherTheme())
    }

    @ViewBuilder private var content: some View {
        switch model.step {
        case .welcome, .installation:
            group {
                row("externaldrive", title: "first-prepare", caption: "first-prepare-caption") { EmptyView() }
                rowDivider
                row("person.crop.circle", title: "first-login-choice", caption: "first-login-caption") { EmptyView() }
                rowDivider
                row("arrow.up.right.square", title: "first-open", caption: "first-open-caption") { EmptyView() }
            }
        case .connection:
            group {
                preparationRow("externaldrive", title: "first-database", state: model.preparation?.database ?? "creating")
                rowDivider
                VStack(spacing: 0) {
                    row("arrow.down.circle", title: "first-model", caption: modelCaption) {
                        if let preparation = model.preparation, preparation.totalBytes > 0 && preparation.model == "downloading" {
                            Text(preparation.fraction.formatted(.percent.precision(.fractionLength(0)).locale(model.copy.locale)))
                                .font(.system(size: 11, weight: .semibold, design: .monospaced)).foregroundStyle(palette.cyan)
                        } else { mark(model.preparation?.model ?? "waiting") }
                    }
                    if let progress = model.preparation, !progress.modelComplete, progress.totalBytes > 0 {
                        VStack(alignment: .leading, spacing: 4) {
                            ProgressView(value: progress.fraction).tint(palette.cyan).controlSize(.small)
                            Text(model.preparationBytes).font(.system(size: 11)).foregroundStyle(palette.secondary)
                        }.padding(.leading, 41).padding(.trailing, 10).padding(.bottom, 10)
                    }
                }
                rowDivider
                preparationRow("gearshape.2", title: "first-service", state: model.preparation?.service ?? "waiting")
            }
        case .login:
            VStack(alignment: .leading, spacing: 10) {
                group {
                    row("person.crop.circle", title: "first-login-toggle", caption: loginCaption) {
                        Toggle(model.text("first-login-toggle"), isOn: Binding(get: { model.setupLoginChoice },
                            set: { enabled in Task { await model.chooseSetupLogin(enabled) } }))
                            .labelsHidden().toggleStyle(.switch).tint(.primary)
                            .disabled(model.loginBusy)
                    }
                    if model.loginState == .approval {
                        Button(model.text("login-settings")) { model.openLoginSettings() }
                            .buttonStyle(.link).font(.system(size: 12)).padding(.leading, 41).padding(.bottom, 10)
                    }
                    if model.loginError { Text(model.text("login-error")).font(.system(size: 11)).padding(10) }
                    rowDivider
                    row("arrow.triangle.2.circlepath", title: "update-automatic", caption: "first-updates-caption") {
                        Toggle(model.text("update-automatic"), isOn: Binding(get: { model.updates.automatic },
                            set: { model.updates.setAutomaticChecks($0, requestNotifications: false) }))
                            .labelsHidden().toggleStyle(.switch).tint(.primary)
                    }
                }
                Text(model.text("first-settings-note")).font(.system(size: 11)).foregroundStyle(palette.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        case .done:
            VStack(alignment: .leading, spacing: 12) {
                group {
                    HStack(spacing: 14) {
                        Image(nsImage: BrandGlyph.menuBar).renderingMode(.template).foregroundStyle(palette.graphic)
                            .frame(width: 36, height: 30).accessibilityHidden(true)
                        Text(model.text("first-menu-hint")).font(.system(size: 13)).fixedSize(horizontal: false, vertical: true)
                        Spacer(minLength: 0)
                    }.padding(10)
                }
                if model.setupOpenFailed {
                    Label(model.text("setup-browser-error"), systemImage: "exclamationmark.triangle.fill")
                        .font(.system(size: 13)).foregroundStyle(palette.warning).fixedSize(horizontal: false, vertical: true)
                }
            }
        }
    }

    private var modelCaption: String {
        switch model.preparation?.model {
        case "ready": "first-model-ready"
        case "unused": "first-model-unused"
        case "verifying": "first-model-verifying"
        case "downloading": "first-model-downloading"
        case "failed": "first-model-failed"
        default: model.preparation?.reason == "offline" ? "first-model-offline" : "first-waiting"
        }
    }
    private var loginCaption: String {
        switch model.loginState {
        case .approval: "first-login-approval"
        default: "first-login-caption"
        }
    }
    private func preparationRow(_ symbol: String, title: String, state: String) -> some View {
        row(symbol, title: title, caption: state == "ready" ? "first-part-ready" : state == "failed" ? "first-part-failed" :
            state == "waiting" ? "first-waiting" : title == "first-database" ? "first-database-creating" : "first-service-starting") {
            mark(state)
        }
    }
    @ViewBuilder private func mark(_ state: String) -> some View {
        if state == "ready" || state == "unused" {
            Image(systemName: "checkmark.circle.fill").foregroundStyle(palette.cyan)
        } else if state == "failed" {
            Image(systemName: "exclamationmark.circle.fill").foregroundStyle(palette.warning)
        } else if state == "waiting" {
            Image(systemName: model.preparation?.reason == "offline" ? "wifi.slash" : "circle.dashed").foregroundStyle(palette.graphic)
        } else { ProgressView().controlSize(.small).frame(width: 14) }
    }
    private func group<Content: View>(@ViewBuilder _ content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 0, content: content)
            .frame(maxWidth: .infinity).background(palette.card, in: RoundedRectangle(cornerRadius: 10))
            .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(palette.line, lineWidth: 0.7))
    }
    private var rowDivider: some View { Divider().padding(.leading, 41).padding(.trailing, 10) }
    private func row<Trailing: View>(_ symbol: String, title: String, caption: String,
                                    @ViewBuilder trailing: () -> Trailing) -> some View {
        HStack(spacing: 9) {
            Image(systemName: symbol).font(.system(size: 14)).foregroundStyle(palette.secondary).frame(width: 22).accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 2) {
                Text(model.text(title)).font(.system(size: 13, weight: .medium)).fixedSize(horizontal: false, vertical: true)
                Text(model.text(caption)).font(.system(size: 11)).foregroundStyle(palette.secondary).fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 0)
            trailing().font(.system(size: 14))
        }.padding(.horizontal, 10).padding(.vertical, 8)
    }
    private var footer: some View {
        HStack(spacing: 8) {
            if model.step != .welcome && model.step != .done && model.step != .installation {
                Button(model.text("back")) { model.goBack() }.buttonStyle(LaunchButtonStyle(palette: palette)).disabled(model.loginBusy)
            }
            if model.step != .done {
                Button(model.text("later"), action: close).buttonStyle(.plain).font(.system(size: 12))
                    .help(model.text("first-later-help"))
            }
            Spacer(minLength: 0)
            if model.step == .connection && model.preparationFailed {
                if let directory = model.engineLogDirectory {
                    Button(model.text("engine-logs")) { NSWorkspace.shared.activateFileViewerSelecting([directory]) }
                        .buttonStyle(LaunchButtonStyle(palette: palette))
                }
                Button(model.text("retry")) { model.startEngine() }
                    .buttonStyle(LaunchButtonStyle(palette: palette, primary: true)).disabled(model.controlBusy)
            } else if model.step == .done {
                Button(model.text("skip")) { if model.finish() { close() } }
                    .buttonStyle(LaunchButtonStyle(palette: palette)).disabled(model.completingSetup)
                Button(model.text("first-open")) { Task { if await model.completeAndOpen() { close() } } }
                    .buttonStyle(LaunchButtonStyle(palette: palette, primary: true)).keyboardShortcut(.defaultAction)
                    .disabled(model.completingSetup || model.checking || model.controlBusy)
            } else {
                Button { Task { await model.advanceSetup() } } label: {
                    HStack(spacing: 7) {
                        if model.step == .connection && !model.preparationReady { ProgressView().controlSize(.small) }
                        Text(model.text(model.step == .connection && !model.preparationReady ? "first-busy" : "continue"))
                    }
                }.buttonStyle(LaunchButtonStyle(palette: palette, primary: true)).keyboardShortcut(.defaultAction)
                    .disabled(model.loginBusy || (model.step == .connection && !model.preparationReady))
            }
        }
    }
}
