import LauncherCore
import SwiftUI

struct LauncherTheme: ViewModifier {
    @Environment(\.colorScheme) private var scheme
    func body(content: Content) -> some View {
        let accent = scheme == .dark
            ? Color(red: 219 / 255, green: 203 / 255, blue: 144 / 255)
            : Color(red: 124 / 255, green: 108 / 255, blue: 34 / 255)
        content.tint(accent).accentColor(accent)
    }
}
