import AppKit

let output = URL(fileURLWithPath: CommandLine.arguments[1])
let messages = try JSONDecoder().decode([String: String].self,
    from: Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[2])))
let width = 760
let height = 600
let ink = NSColor(calibratedRed: 0.12, green: 0.13, blue: 0.12, alpha: 1)
let gold = NSColor(calibratedRed: 0.49, green: 0.42, blue: 0.14, alpha: 1)

for scale in [1, 2] {
    let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: width * scale, pixelsHigh: height * scale,
                                 bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                                 colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    bitmap.size = NSSize(width: width, height: height)
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: bitmap)
    NSColor(calibratedRed: 0.96, green: 0.95, blue: 0.92, alpha: 1).setFill()
    NSRect(x: 0, y: 0, width: width, height: height).fill()

    func rect(_ x: CGFloat, _ y: CGFloat, _ w: CGFloat, _ h: CGFloat) -> NSRect {
        NSRect(x: x, y: CGFloat(height) - y - h, width: w, height: h)
    }
    func text(_ value: String, x: CGFloat, y: CGFloat, size: CGFloat,
              weight: NSFont.Weight = .regular, color: NSColor = ink, maxWidth: CGFloat = 664) {
        let style = NSMutableParagraphStyle()
        style.lineBreakMode = .byWordWrapping
        let string = NSAttributedString(string: value, attributes: [
            .font: NSFont.systemFont(ofSize: size, weight: weight), .foregroundColor: color, .paragraphStyle: style,
        ])
        let bounds = string.boundingRect(with: NSSize(width: maxWidth, height: 200), options: .usesLineFragmentOrigin)
        string.draw(in: rect(x, y, maxWidth, ceil(bounds.height)))
    }

    text(messages["installer-title"]!, x: 48, y: 24, size: 28, weight: .semibold)
    text(messages["guide-start"]!, x: 184, y: 98, size: 20, weight: .semibold, color: gold)
    text(messages["guide-start-body"]!, x: 184, y: 132, size: 15, maxWidth: 524)
    text(messages["guide-drag-caption"]!, x: 48, y: 216, size: 17)

    NSColor.white.withAlphaComponent(0.65).setFill()
    let zone = NSBezierPath(roundedRect: rect(32, 250, 696, 205), xRadius: 22, yRadius: 22)
    zone.fill()
    gold.withAlphaComponent(0.14).setStroke()
    zone.lineWidth = 1
    zone.stroke()
    gold.setStroke()
    let arrow = NSBezierPath()
    arrow.move(to: NSPoint(x: 320, y: height - 335))
    arrow.line(to: NSPoint(x: 440, y: height - 335))
    arrow.move(to: NSPoint(x: 430, y: height - 325))
    arrow.line(to: NSPoint(x: 440, y: height - 335))
    arrow.line(to: NSPoint(x: 430, y: height - 345))
    arrow.lineWidth = 2
    arrow.lineCapStyle = .round
    arrow.lineJoinStyle = .round
    arrow.stroke()

    text(messages["installer-open"]!, x: 48, y: 480, size: 17, weight: .medium)
    NSGraphicsContext.restoreGraphicsState()
    let name = scale == 1 ? "installer.png" : "installer@2x.png"
    try bitmap.representation(using: .png, properties: [:])!.write(to: output.appendingPathComponent(name))
}
