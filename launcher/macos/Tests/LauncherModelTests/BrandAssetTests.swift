import AppKit
import Testing
@testable import LauncherCore
@testable import RoleBandLauncher

@MainActor
@Test func shippedNativeMarksLoadAsVectorAndRetinaTemplateRepresentations() throws {
    for profile in [BrandAsset.bar, .mid, .master] {
        let image = try #require(profile.url.flatMap(NSImage.init(contentsOf:)))
        #expect(image.representations.contains { $0 is NSPDFImageRep })
    }
    #expect(BrandGlyph.menuBar.isTemplate && BrandGlyph.master.isTemplate)
    #expect(BrandGlyph.menuBar.size == NSSize(width: 18, height: 18))
    #expect(Set(BrandGlyph.menuBar.representations.map { $0.pixelsWide }) == [18, 36])
    #expect(BrandGlyph.master.size == NSSize(width: 100, height: 100))
}

@MainActor
private func pixels(_ image: NSImage) throws -> NSBitmapImageRep {
    let bitmap = try #require(NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: 36, pixelsHigh: 36, bitsPerSample: 8,
        samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0))
    bitmap.size = image.size
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: bitmap)
    image.draw(in: NSRect(origin: .zero, size: image.size))
    NSGraphicsContext.restoreGraphicsState()
    return bitmap
}

@MainActor
@Test func everyMenuBarStateKeepsTheMarkAndBadgesOnlyItsCorner() throws {
    #expect(BrandGlyph.menuBar(badge: nil) === BrandGlyph.menuBar)
    let plain = try pixels(BrandGlyph.menuBar)
    for badge in ["arrow.triangle.2.circlepath.circle.fill", "pause.circle.fill", "exclamationmark.circle.fill",
                  "exclamationmark.triangle.fill", "xmark.circle.fill"] {
        #expect(NSImage(systemSymbolName: badge, accessibilityDescription: nil) != nil, "\(badge) is not a system symbol")
        let image = BrandGlyph.menuBar(badge: badge)
        #expect(image.isTemplate && image.size == NSSize(width: 18, height: 18))
        let badged = try pixels(image)
        var outside = 0, inside = 0
        for y in 0..<36 { for x in 0..<36 {
            let same = plain.colorAt(x: x, y: y)?.alphaComponent == badged.colorAt(x: x, y: y)?.alphaComponent
            // The bitmap's rows run top down; the badge disc is the lower right 20 by 20 pixels.
            if x >= 16 && y >= 16 { if !same { inside += 1 } } else if !same { outside += 1 }
        } }
        #expect(outside == 0, "\(badge) changed the mark outside its corner")
        #expect(inside > 20, "\(badge) drew no visible badge")
    }
}
