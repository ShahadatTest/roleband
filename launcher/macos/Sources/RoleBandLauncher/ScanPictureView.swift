import LauncherCore
import SwiftUI

/// The README's scan picture, redrawn for the panel: companies in flight on the left, their
/// channels, and the tank that holds what this scan has collected. At rest the left side holds the
/// last scan's facts instead.
struct ScanPictureCard: View {
    @ObservedObject var model: LauncherModel
    let picture: ScanPicture
    let phase: ScanPhase
    let now: Date

    private var live: Bool { phase == .scanning || phase == .stopping }

    var body: some View {
        PaletteReader { p in
            VStack(alignment: .leading, spacing: 8) {
                HStack(alignment: .firstTextBaseline) {
                    SectionLabel(text: model.text(phase.titleKey(picture)))
                    status(p)
                }
                VStack(alignment: .leading, spacing: 0) {
                    progressBar(p).padding(.top, 2).padding(.bottom, 10)
                    FlowInstrument(model: model, picture: picture, phase: phase).padding(.bottom, 10)
                    Divider().padding(.horizontal, -10)
                    schedule(p).padding(.top, 9)
                }
                .panelCard()
            }
        }
    }

    @ViewBuilder
    private func status(_ p: LaunchPalette) -> some View {
        Group {
            if model.requestedScan != nil {
                // As tall as the time it stands in for, so the panel does not jump by a point.
                ProgressView().controlSize(.mini).frame(height: 11)
            } else if live && picture.stage == .finishing, let start = Stamp.date(model.verified?.presentation.activitySince) {
                // The percent has said 100 since the last company; the clock shows the scan still moving.
                TimelineView(.periodic(from: .now, by: 1)) { timeline in
                    Text(ScanTime.running(since: start, now: timeline.date, locale: model.copy.locale))
                        .font(ScanType.figure(11)).foregroundStyle(p.cyan)
                }
            } else if live {
                if let percent = picture.percent {
                    Text("\(min(percent, 100))%").font(ScanType.figure(11)).foregroundStyle(p.cyan)
                }
            } else if let last = Stamp.date(model.verified?.presentation.lastScanAt) {
                Text(ScanTime.moment(last, now: now, model: model)).font(PanelType.fact).foregroundStyle(p.secondary)
            }
        }
        .fixedSize()
    }

    /// At rest the bar is an empty track: a full bar would only repeat "Scan complete".
    private func progressBar(_ p: LaunchPalette) -> some View {
        let fraction = live ? Double(min(picture.percent ?? 0, 100)) / 100 : 0
        return ProgressLine(fraction: fraction, color: p.cyan, track: p.track)
            .accessibilityElement()
            .accessibilityLabel(live ? model.text("scan-progress", ["percent": "\(min(picture.percent ?? 0, 100))"]) : model.text(phase.titleKey(picture)))
    }

    /// One line for the schedule: the next scan, a pause with its end, or scheduling off. While a
    /// stop is waiting for the engine, the line says what the stop keeps instead.
    @ViewBuilder
    private func schedule(_ p: LaunchPalette) -> some View {
        HStack(spacing: 6) {
            let state = ScheduleLine.of(phase: phase, schedule: model.scheduleState, picture: picture, now: now)
            switch state {
            case .stopping:
                Image(systemName: "checkmark.circle").font(.system(size: 11, weight: .medium)).foregroundStyle(p.cyan)
                    .accessibilityHidden(true)
                Text(model.text("scan-kept")).foregroundStyle(p.secondary)
                Spacer(minLength: 0)
            case .off:
                line("calendar.badge.minus", model.text("scan-schedule-off"), p)
                    .help(model.text("scan-schedule-off-help", ["setting": "ROLEBAND_SYNC_SCHEDULER_ENABLED"]))
                if let key = state.scheduleLink { link(key) }
            case .paused(let until):
                line("pause.circle", model.text("scan-paused-until", ["time": ScanTime.clock(until, now: now, locale: model.copy.locale)]), p)
                Button(model.text("scan-resume")) { model.pause(.resume) }
                    .buttonStyle(LinkButtonStyle(font: ScanType.line.weight(.medium)))
                    .help(model.text("scan-resume-help"))
                    .disabled(model.controlBusy)
            case .next(let next):
                line("clock", next.map { model.text("scan-next", ["time": ScanTime.clock($0, now: now, locale: model.copy.locale)]) } ?? model.text("scan-next-soon"), p)
                if let key = state.scheduleLink { link(key) }
            case .unknown:
                Text(model.text(model.scheduleFailed ? "pause-unavailable" : "pause-loading")).foregroundStyle(p.secondary)
                Spacer(minLength: 0)
            }
        }
        .font(ScanType.line)
    }

    private func line(_ symbol: String, _ text: String, _ p: LaunchPalette) -> some View {
        Group {
            Image(systemName: symbol).font(.system(size: 11, weight: .medium)).foregroundStyle(p.secondary)
                .accessibilityHidden(true)
            // A long language with a 12-hour clock wraps rather than cutting off the time.
            Text(text).foregroundStyle(p.secondary).lineLimit(2).minimumScaleFactor(0.85)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 4)
        }
    }

    private func link(_ key: String) -> some View {
        Button { model.open(.schedule) } label: {
            HStack(spacing: 3) {
                Text(model.text(key))
                Image(systemName: "arrow.up.right").font(.system(size: 9, weight: .bold)).accessibilityHidden(true)
            }
        }
        .buttonStyle(LinkButtonStyle(font: ScanType.line.weight(.medium)))
        .help(model.text("scan-opens-schedule"))
    }
}

/// Channels, travelling dots and the tank. Dots move only while companies are genuinely in
/// flight; with Reduce Motion the marks stay still and the clocks and counts still change.
private struct FlowInstrument: View {
    @ObservedObject var model: LauncherModel
    let picture: ScanPicture
    let phase: ScanPhase
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private let rowPitch: CGFloat = 27
    private let height: CGFloat = 140
    private let tankWidth: CGFloat = 90

    private var live: Bool { phase == .scanning || phase == .stopping }
    private var companies: [(name: String, since: Date?)] { picture.inFlight.map { ($0.name, Stamp.date($0.since)) } }
    /// Every company is read and none is in flight: the left side says how many were read.
    private var readTotal: Int? { live && companies.isEmpty && picture.everyCompanyRead ? picture.companiesTotal : nil }

    var body: some View {
        let flowing = live && !companies.isEmpty && !reduceMotion
        PaletteReader { p in
            TimelineView(.animation(minimumInterval: flowing ? 1.0 / 30 : 1, paused: !live)) { timeline in
                GeometryReader { proxy in
                    let tankX = proxy.size.width - tankWidth
                    ZStack(alignment: .topLeading) {
                        Canvas { context, _ in
                            draw(in: &context, tankX: tankX, now: timeline.date, flowing: flowing, p: p)
                        }
                        Tank(model: model, picture: picture, phase: phase, palette: p)
                            .frame(width: tankWidth, height: height)
                            .offset(x: tankX)
                    }
                }
                .frame(height: height)
                .accessibilityElement(children: .ignore)
                .accessibilityLabel(summary(now: timeline.date))
                .accessibilityAddTraits(.updatesFrequently)
                .overlay(alignment: .topLeading) {
                    if !live { LastScanFacts(model: model, picture: picture, palette: p, rowY: factY) }
                    if let readTotal { CompaniesRead(model: model, count: readTotal, palette: p, y: centerY) }
                }
            }
        }
    }

    private var centerY: CGFloat { height / 2 }
    /// Where the last scan's facts meet their channels: companies read above, new roles below.
    private func factY(_ index: Int) -> CGFloat { centerY + (index == 0 ? -22 : 22) - 6 }

    /// Flat where it leaves the source, then bending into the tank mouth.
    private func channel(from start: CGPoint, to end: CGPoint) -> (Path, (CGFloat) -> CGPoint) {
        let span = end.x - start.x
        let c1 = CGPoint(x: start.x + span * 0.34, y: start.y)
        let c2 = CGPoint(x: end.x - span * 0.40, y: end.y)
        var path = Path()
        path.move(to: start)
        path.addCurve(to: end, control1: c1, control2: c2)
        let point: (CGFloat) -> CGPoint = { t in
            let a = 1 - t
            let x = a * a * a * start.x + 3 * a * a * t * c1.x + 3 * a * t * t * c2.x + t * t * t * end.x
            let y = a * a * a * start.y + 3 * a * a * t * c1.y + 3 * a * t * t * c2.y + t * t * t * end.y
            return CGPoint(x: x, y: y)
        }
        return (path, point)
    }

    private func draw(in context: inout GraphicsContext, tankX: CGFloat, now: Date, flowing: Bool, p: LaunchPalette) {
        let mouth = CGPoint(x: tankX - 1, y: centerY)
        if readTotal != nil {
            let spout = CGPoint(x: LastScanFacts.labelRight + 8, y: centerY)
            context.stroke(channel(from: spout, to: mouth).0, with: .color(p.graphic), lineWidth: 1)
            dot(&context, at: spout, radius: 2.4, color: p.cyan)
        } else if live {
            let rows = companies
            let labelRight: CGFloat = 64
            let spoutX: CGFloat = 72
            let elapsed = now.timeIntervalSinceReferenceDate
            for (index, company) in rows.enumerated() {
                let nameY = centerY + (CGFloat(index) - CGFloat(rows.count - 1) / 2) * rowPitch - 5
                let (path, point) = channel(from: CGPoint(x: spoutX, y: nameY), to: mouth)
                context.stroke(path, with: .color(p.graphic), lineWidth: 1)
                context.draw(Text(company.name).font(.system(size: 12, weight: .medium)).foregroundStyle(p.cyan),
                             at: CGPoint(x: labelRight, y: nameY), anchor: .trailing)
                if let since = company.since {
                    context.draw(Text(ScanTime.running(since: since, now: now, locale: model.copy.locale)).font(ScanType.figure(10.5, weight: .regular)).foregroundStyle(p.secondary),
                                 at: CGPoint(x: labelRight, y: nameY + 13), anchor: .trailing)
                }
                dot(&context, at: CGPoint(x: spoutX, y: nameY), radius: 2.6, color: p.cyan)
                guard flowing else { continue }
                let period = 3.4
                for slot in 0..<3 {
                    let phase = (elapsed + Double(slot) * 1.13 + Double(index) * 0.41).truncatingRemainder(dividingBy: period) / period
                    let fade = min(1, phase / 0.08, (1 - phase) / 0.28)
                    dot(&context, at: point(phase), radius: 2.1, color: p.cyan.opacity(fade))
                }
            }
        } else {
            let spoutX = LastScanFacts.labelRight + 8
            for index in 0..<2 {
                let y = factY(index)
                let (path, _) = channel(from: CGPoint(x: spoutX, y: y), to: mouth)
                context.stroke(path, with: .color(p.graphic), lineWidth: 1)
                dot(&context, at: CGPoint(x: spoutX, y: y), radius: 2.4, color: p.graphic)
            }
        }
    }

    private func dot(_ context: inout GraphicsContext, at point: CGPoint, radius: CGFloat, color: Color) {
        context.fill(Path(ellipseIn: CGRect(x: point.x - radius, y: point.y - radius, width: radius * 2, height: radius * 2)),
                     with: .color(color))
    }

    private func summary(now: Date) -> String {
        if let readTotal {
            return model.text("scan-summary-read", ["companies": "\(readTotal)", "recorded": "\(picture.rolesRecorded ?? 0)",
                                                    "pending": "\(picture.rolesPending ?? 0)"])
        }
        if live {
            let names = companies.map { company in
                company.since.map { "\(company.name) \(ScanTime.running(since: $0, now: now, locale: model.copy.locale))" } ?? company.name
            }
            return model.text("scan-summary-live", ["companies": names.formatted(.list(type: .and).locale(model.copy.locale)),
                                                    "pending": "\(picture.rolesPending ?? 0)", "recorded": "\(picture.rolesRecorded ?? 0)"])
        }
        return model.text(phase == .stopped ? "scan-summary-stopped" : "scan-summary-last",
                          ["companies": "\(picture.lastCompanies ?? 0)", "roles": "\(picture.lastNewRoles ?? 0)",
                           "postings": "\(picture.lastPostings ?? 0)"])
    }
}

/// The last scan's two facts, each beside its channel's spout. The new-roles count opens the Radar
/// on New, as the dashboard's own New count does; with none, it stays a plain fact. Both are views
/// rather than canvas text so the count can be a button; the instrument's summary already reads
/// them aloud, so only the button is its own accessibility element.
private struct LastScanFacts: View {
    @ObservedObject var model: LauncherModel
    let picture: ScanPicture
    let palette: LaunchPalette
    let rowY: (Int) -> CGFloat
    @ViewState private var hovering = false

    static let labelRight: CGFloat = 92

    var body: some View {
        let p = palette
        let newRoles = picture.lastNewRoles ?? 0
        ZStack(alignment: .topLeading) {
            fact(picture.lastCompanies ?? 0, label: Text(model.text("scan-companies-read")).foregroundStyle(p.secondary))
                .accessibilityHidden(true)
                .modifier(Place(y: rowY(0)))
            if newRoles > 0 {
                Button { model.open(.newRoles) } label: {
                    fact(newRoles, label: HStack(spacing: 3) {
                        Text(model.text("scan-new-roles")).underline(hovering, color: p.goldText.opacity(0.6))
                        Image(systemName: "arrow.up.right").font(.system(size: 8, weight: .bold)).accessibilityHidden(true)
                    }
                    .foregroundStyle(p.goldText))
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .onHover { hovering = $0 }
                .disabled(model.verified == nil)
                .help(model.text("scan-new-roles-open"))
                .accessibilityLabel("\(newRoles) \(model.text("scan-new-roles"))")
                .accessibilityHint(model.text("scan-new-roles-open"))
                .modifier(Place(y: rowY(1)))
            } else {
                fact(0, label: Text(model.text("scan-new-roles")).foregroundStyle(p.secondary))
                    .accessibilityHidden(true)
                    .modifier(Place(y: rowY(1)))
            }
        }
    }

    /// The figure centred on its spout's line and the label under it, right-aligned to the spout.
    /// A label longer than the column grows to the left on one line.
    private func fact(_ count: Int, label: some View) -> some View {
        VStack(alignment: .trailing, spacing: 0) {
            Text(count.formatted(.number.locale(model.copy.locale))).font(ScanType.figure(17)).foregroundStyle(palette.ink)
            label.font(PanelType.fact)
        }
        .fixedSize()
    }

    /// Half the figure's line height up, so the figure's middle sits on the spout.
    private struct Place: ViewModifier {
        let y: CGFloat
        func body(content: Content) -> some View {
            content.frame(width: LastScanFacts.labelRight, alignment: .trailing).offset(y: y - 10)
        }
    }
}

/// How many companies a scan read, beside its one channel, once every company is read.
private struct CompaniesRead: View {
    @ObservedObject var model: LauncherModel
    let count: Int
    let palette: LaunchPalette
    let y: CGFloat

    var body: some View {
        VStack(alignment: .trailing, spacing: 0) {
            Text(count.formatted(.number.locale(model.copy.locale))).font(ScanType.figure(17)).foregroundStyle(palette.ink)
            Text(model.text("scan-companies-read")).font(PanelType.fact).foregroundStyle(palette.secondary)
        }
        .fixedSize()
        .frame(width: LastScanFacts.labelRight, alignment: .trailing)
        .offset(y: y - 10)
        .accessibilityHidden(true)
    }
}

/// Two volumes in one tank, with the dashboard's words: the figure counts roles from companies
/// still being read, and the band and floor count roles from companies whose scan has ended.
private struct Tank: View {
    @ObservedObject var model: LauncherModel
    let picture: ScanPicture
    let phase: ScanPhase
    let palette: LaunchPalette

    var body: some View {
        let p = palette
        let live = phase == .scanning || phase == .stopping
        // Past the reading no company is still scanning: the figure is what is recorded, and the
        // floor counts the roles still being added.
        let read = live && picture.everyCompanyRead
        let held = live ? picture.rolesPending ?? 0 : 0
        let written = live ? picture.rolesRecorded ?? 0 : picture.lastPostings ?? 0
        let fraction = CGFloat(written) / CGFloat(max(1, held + written))
        let shape = RoundedRectangle(cornerRadius: 8, style: .continuous)
        ZStack {
            shape.fill(p.sunken)
            GeometryReader { proxy in
                VStack(spacing: 0) {
                    Spacer(minLength: 0)
                    Rectangle().fill(p.cyan.opacity(p.dark ? 0.16 : 0.12))
                        .overlay(alignment: .top) { Rectangle().fill(p.cyan.opacity(0.55)).frame(height: fraction < 1 ? 1 : 0) }
                        .frame(height: proxy.size.height * fraction)
                }
            }
            .clipShape(shape)
            shape.strokeBorder(p.lineStrong, lineWidth: 0.8)
            VStack(spacing: 0) {
                Text(model.text(live ? "scan-roles-found" : (phase == .requesting ? "last-scan" : "scan-postings")).uppercased())
                    .font(PanelType.label).kerning(0.6).foregroundStyle(p.secondary)
                    .lineLimit(1).minimumScaleFactor(0.7).padding(.horizontal, 6).padding(.top, 9)
                Spacer(minLength: 0)
                Text((live && !read ? held : written).formatted(.number.locale(model.copy.locale))).font(ScanType.figure(20)).foregroundStyle(p.ink)
                    .lineLimit(1).minimumScaleFactor(0.6)
                Text(model.text(live && !read ? "scan-still-scanning" : "scan-recorded")).font(PanelType.fact).foregroundStyle(p.secondary)
                Spacer(minLength: 0)
                if read && held > 0 {
                    Rectangle().fill(p.line).frame(height: 0.7).padding(.horizontal, 8)
                    HStack(spacing: 3) {
                        Text(held.formatted(.number.locale(model.copy.locale))).font(ScanType.figure(11, weight: .medium))
                        Text(model.text("scan-to-add")).font(PanelType.fact)
                    }
                    .foregroundStyle(p.secondary).frame(height: 26)
                } else if live && !read {
                    Rectangle().fill(p.line).frame(height: 0.7).padding(.horizontal, 8)
                    HStack(spacing: 3) {
                        Text(written.formatted(.number.locale(model.copy.locale))).font(ScanType.figure(11, weight: .medium))
                        Text(model.text("scan-finished")).font(PanelType.fact)
                    }
                    .foregroundStyle(p.secondary).frame(height: 26)
                } else {
                    Color.clear.frame(height: 26)
                }
            }
        }
    }
}

/// Open Radar, then Scan now or Stop scan and the Pause menu, quiet: scans run on their own, and
/// the roles they find are what the person comes for. The scan button shows what the engine has
/// confirmed; a request in flight disables it and says so until the engine answers.
struct ScanPictureActions: View {
    @ObservedObject var model: LauncherModel
    let now: Date

    var body: some View {
        VStack(spacing: 8) {
            OpenRadarButton(model: model)
            HStack(spacing: 8) {
                scanButton
                if let plan = model.scheduleState, plan.pausable { pauseMenu(paused: plan.isPaused(at: now)) }
            }
        }
    }

    @ViewBuilder
    private var scanButton: some View {
        if let requested = model.requestedScan {
            Button {} label: {
                HStack(spacing: 7) {
                    ProgressView().controlSize(.mini)
                    Text(model.text(requested == .start ? "scan-sending" : "scan-stop-requested"))
                }
            }
            .buttonStyle(QuietButtonStyle())
            .disabled(true)
        } else if let action = model.scanAction {
            Button { model.scan(action) } label: {
                Label(model.text(action == .start ? "scan-now" : "scan-stop"), systemImage: action == .start ? "play.fill" : "stop.fill")
                    .labelStyle(GapLabelStyle(gap: 6, iconSize: 9))
            }
            .buttonStyle(QuietButtonStyle())
            .help(action == .stop ? model.text("scan-kept") : "")
            .disabled(model.controlBusy)
        }
    }

    private func pauseMenu(paused: Bool) -> some View {
        Menu {
            if paused {
                Button(model.text("pause-resume")) { model.pause(.resume) }
            } else {
                ForEach([PauseAction.hour, .threeHours, .tomorrow], id: \.rawValue) { action in
                    Button(model.text(action.key)) { model.pause(action) }
                }
            }
        } label: {
            HStack(spacing: 5) {
                Image(systemName: "pause").font(.system(size: 10, weight: .bold))
                Text(model.text(paused ? "scan-paused" : "scan-pause"))
                Image(systemName: "chevron.down").font(.system(size: 8, weight: .bold)).opacity(0.7)
            }
        }
        .menuStyle(.button).menuIndicator(.hidden).buttonStyle(QuietButtonStyle())
        .frame(maxWidth: .infinity)
        .help(model.text("pause-help"))
        .disabled(model.controlBusy)
    }
}

enum ScanType {
    static let line = Font.system(size: 12)
    static func figure(_ size: CGFloat, weight: Font.Weight = .semibold) -> Font {
        .system(size: size, weight: weight, design: .monospaced)
    }
}

enum ScanTime {
    /// "2m 28s" in the person's language.
    static func running(since: Date, now: Date, locale: Locale) -> String {
        Duration.seconds(max(0, Int(now.timeIntervalSince(since))))
            .formatted(.units(allowed: [.hours, .minutes, .seconds], width: .narrow, maximumUnitCount: 2).locale(locale))
    }

    /// The time alone today, the date and time otherwise.
    static func clock(_ date: Date, now: Date, locale: Locale) -> String {
        Calendar.current.isDate(date, inSameDayAs: now)
            ? date.formatted(.dateTime.hour().minute().locale(locale))
            : date.formatted(.dateTime.month(.abbreviated).day().hour().minute().locale(locale))
    }

    @MainActor
    static func moment(_ date: Date, now: Date, model: LauncherModel) -> String {
        Calendar.current.isDate(date, inSameDayAs: now)
            ? model.text("scan-today-at", ["time": clock(date, now: now, locale: model.copy.locale)])
            : clock(date, now: now, locale: model.copy.locale)
    }
}

/// What the schedule line shows. Scheduling switched off where the engine is configured has no
/// switch on the Schedule page, so that line links nowhere.
enum ScheduleLine: Equatable {
    case stopping, off, paused(until: Date), next(Date?), unknown

    static func of(phase: ScanPhase, schedule: ScheduleState?, picture: ScanPicture, now: Date) -> ScheduleLine {
        if phase == .stopping { return .stopping }
        if let schedule, !schedule.enabled { return .off }
        if let schedule, let until = schedule.pausedUntil, schedule.isPaused(at: now) { return .paused(until: until) }
        if schedule != nil || picture.nextScanAt != nil { return .next(picture.nextScan(after: now)) }
        return .unknown
    }

    /// The link beside the line, which opens the Schedule page.
    var scheduleLink: String? {
        if case .next = self { return "scan-change-times" }
        return nil
    }
}
