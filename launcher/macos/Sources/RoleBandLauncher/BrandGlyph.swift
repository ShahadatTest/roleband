import AppKit
import LauncherCore

@MainActor
enum BrandGlyph {
    static let menuBar: NSImage = {
        let image = NSImage(size: NSSize(width: 18, height: 18))
        for asset in [BrandAsset.menuBar, .menuBarRetina] {
            if let url = asset.url, let representation = NSImageRep(contentsOf: url) {
                representation.size = NSSize(width: 18, height: 18)
                image.addRepresentation(representation)
            }
        }
        image.isTemplate = true
        return image
    }()

    /// The menu-bar mark with a state's symbol as a badge in its lower right corner. The badge
    /// sits in a cleared disc so it stays legible over the rings once macOS tints the template.
    static func menuBar(badge: String?) -> NSImage {
        guard let badge else { return menuBar }
        if let cached = badged[badge] { return cached }
        let symbol = NSImage(systemSymbolName: badge, accessibilityDescription: nil)?
            .withSymbolConfiguration(NSImage.SymbolConfiguration(pointSize: 8, weight: .bold))
        let image = NSImage(size: menuBar.size, flipped: false) { rect in
            menuBar.draw(in: rect)
            let disc = NSRect(x: rect.maxX - 10, y: rect.minY, width: 10, height: 10)
            NSGraphicsContext.current?.compositingOperation = .clear
            NSBezierPath(ovalIn: disc).fill()
            NSGraphicsContext.current?.compositingOperation = .sourceOver
            if let symbol {
                let size = symbol.size
                symbol.draw(in: NSRect(x: disc.midX - size.width / 2, y: disc.midY - size.height / 2,
                                       width: size.width, height: size.height))
            }
            return true
        }
        image.isTemplate = true
        badged[badge] = image
        return image
    }
    private static var badged: [String: NSImage] = [:]

    static let master: NSImage = {
        let image = BrandAsset.master.url.flatMap(NSImage.init(contentsOf:)) ?? NSImage()
        image.isTemplate = true
        return image
    }()
}
