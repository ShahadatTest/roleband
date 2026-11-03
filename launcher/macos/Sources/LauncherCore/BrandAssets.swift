import Foundation

public enum BrandAsset: String, CaseIterable, Sendable {
    case bar = "roleband-mark-bar-template"
    case mid = "roleband-mark-mid-template"
    case master = "roleband-mark-master-template"
    case menuBar = "roleband-menubar-18"
    case menuBarRetina = "roleband-menubar-18@2x"

    public var url: URL? {
        let bundle = LauncherCopy.resources(in: .main) ?? .module
        return bundle.url(forResource: rawValue, withExtension: self == .menuBar || self == .menuBarRetina ? "png" : "pdf")
    }
}
