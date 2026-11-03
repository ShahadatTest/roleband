import AppKit

// The RoleBand mark on its tile, on Apple's macOS icon grid: an 824 shape in a
// 1024 canvas, corner radius 185. Geometry is in a 100 box with y pointing up.
// Below 64 px the master weights fall under a pixel, so each small size has its
// own drawing: 32 px keeps three heavier rings, 16 px drops the innermost ring,
// which would otherwise close the three into a bullseye. The places never move.
struct Ring { let radius: CGFloat; let width: CGFloat; let alpha: CGFloat }
struct Drawing { let rings: [Ring]; let sweep: CGFloat; let role: CGFloat; let share: CGFloat }

let master = Drawing(rings: [Ring(radius: 43.9, width: 3.0, alpha: 0.45), Ring(radius: 28.6, width: 3.0, alpha: 0.45),
                             Ring(radius: 13.2, width: 3.0, alpha: 0.45)], sweep: 3.4, role: 5.0, share: 0.78)
let mid = Drawing(rings: [Ring(radius: 43.9, width: 6.0, alpha: 1), Ring(radius: 28.6, width: 6.0, alpha: 1),
                          Ring(radius: 13.2, width: 6.0, alpha: 1)], sweep: 7.0, role: 6.5, share: 0.84)
let small = Drawing(rings: [Ring(radius: 43.9, width: 7.0, alpha: 1), Ring(radius: 28.6, width: 7.0, alpha: 1)],
                    sweep: 7.0, role: 7.0, share: 0.84)

func drawing(forPixels size: Int) -> Drawing { size <= 16 ? small : size <= 32 ? mid : master }

let directory = URL(fileURLWithPath: CommandLine.arguments[1])
try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
for base in [16, 32, 128, 256, 512] {
    for scale in [1, 2] {
        let size = base * scale
        let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: size, pixelsHigh: size,
                                     bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true,
                                     isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: bitmap)
        let canvas = NSAffineTransform()
        canvas.scale(by: CGFloat(size) / 1024)
        canvas.concat()
        NSColor(srgbRed: 0x1d / 255, green: 0x21 / 255, blue: 0x1d / 255, alpha: 1).setFill()
        NSBezierPath(roundedRect: NSRect(x: 100, y: 100, width: 824, height: 824), xRadius: 185, yRadius: 185).fill()
        let art = drawing(forPixels: size)
        let mark = 824 * art.share
        let box = NSAffineTransform()
        box.translateX(by: 512 - mark / 2, yBy: 512 - mark / 2)
        box.scale(by: mark / 100)
        box.concat()
        let gold = NSColor(srgbRed: 0xdb / 255, green: 0xcb / 255, blue: 0x90 / 255, alpha: 1)
        for ring in art.rings {
            gold.withAlphaComponent(ring.alpha).setStroke()
            let circle = NSBezierPath(ovalIn: NSRect(x: 50 - ring.radius, y: 50 - ring.radius, width: ring.radius * 2, height: ring.radius * 2))
            circle.lineWidth = ring.width
            circle.stroke()
        }
        gold.setStroke()
        let sweep = NSBezierPath()
        sweep.move(to: NSPoint(x: 50, y: 50)); sweep.line(to: NSPoint(x: 81.18, y: 81.18))
        sweep.lineWidth = art.sweep; sweep.lineCapStyle = .round; sweep.stroke()
        gold.setFill()
        NSBezierPath(ovalIn: NSRect(x: 69.37 - art.role, y: 69.37 - art.role, width: art.role * 2, height: art.role * 2)).fill()
        NSGraphicsContext.restoreGraphicsState()
        let suffix = scale == 2 ? "@2x" : ""
        try bitmap.representation(using: .png, properties: [:])!.write(to: directory.appendingPathComponent("icon_\(base)x\(base)\(suffix).png"))
    }
}
