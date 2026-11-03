import Foundation

public struct LauncherCopy: Sendable {
    /// The resource bundle SwiftPM builds for this target; `build-app.sh` copies it into
    /// `Contents/Resources`.
    static let resourceBundleName = "RoleBandLauncher_LauncherCore"

    private let messages: [String: String]
    public let locale: Locale
    /// `regional` is the person's own locale: dates and numbers keep its region, clock and
    /// calendar, in the catalog's language.
    public init(language: String? = nil, regional: Locale = .current) {
        let preferred = language ?? Locale.preferredLanguages.first ?? "en"
        let code = preferred.hasPrefix("es") ? "es" : preferred.hasPrefix("zh") ? "zh-Hans" : "en"
        var components = Locale.Components(locale: regional)
        // The region lives in the language's components too; replacing them drops it unless it is carried over.
        let region = components.languageComponents.region ?? components.region
        components.languageComponents = Locale.Language.Components(identifier: code)
        components.languageComponents.region = region
        locale = Locale(components: components)
        messages = Self.load(code, from: Self.resources(in: .main)) ?? Self.load(code, from: .module) ?? [:]
    }
    /// The export fills each language's gaps with English, so a key missing here is missing from the
    /// English catalog too. It shows as itself rather than as another message.
    public func text(_ key: String) -> String { messages[key] ?? key }
    /// A message with named values, written `{name}` in the catalog.
    public func text(_ key: String, _ values: [String: String]) -> String {
        values.reduce(text(key)) { $0.replacingOccurrences(of: "{\($1.key)}", with: $1.value) }
    }

    /// The assembled app's copy of the resource bundle. SwiftPM's generated `Bundle.module` looks
    /// elsewhere depending on the build system (beside the app bundle, or the build machine's
    /// absolute `.build` path), so it is only the fallback for `swift test`.
    static func resources(in app: Bundle) -> Bundle? {
        app.url(forResource: resourceBundleName, withExtension: "bundle").flatMap(Bundle.init(url:))
    }

    /// True when the app bundle carries every language's catalog in its own resources.
    public static func appCarriesCatalogs(_ app: Bundle = .main) -> Bool {
        let resources = resources(in: app)
        return ["en", "es", "zh-Hans"].allSatisfy { load($0, from: resources)?["continue"] != nil }
    }

    static func load(_ code: String, from bundle: Bundle?) -> [String: String]? {
        guard let url = bundle?.url(forResource: "copy.\(code)", withExtension: "json"),
              let data = try? Data(contentsOf: url) else { return nil }
        return try? JSONDecoder().decode([String: String].self, from: data)
    }
}
