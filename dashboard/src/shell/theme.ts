/* The theme a person chose, kept on this device.
 *
 * Storage can throw on access (blocked site data, a private window, a full
 * quota), and the shell reads the theme during its first render, where a throw
 * leaves a blank page. So a failed read is the default theme and a failed write
 * is dropped: the switch still works for this visit. `public/theme-boot.js`
 * reads the same key the same way before first paint. */

export type Theme = "light" | "dark";

const KEY = "theme";
export const DEFAULT_THEME: Theme = "dark";

export function readTheme(): Theme {
  try {
    const saved = localStorage.getItem(KEY);
    return saved === "light" || saved === "dark" ? saved : DEFAULT_THEME;
  } catch {
    return DEFAULT_THEME;
  }
}

/** The theme on screen. First-run setup (the welcome page and the setup
    walk) is always dark, whatever the person chose: the person's choice is
    neither changed nor saved over, and comes back when setup ends.
    `public/theme-boot.js` paints the welcome page dark the same way. */
export function shownTheme(chosen: Theme, inSetup: boolean): Theme {
  return inSetup ? "dark" : chosen;
}

export function writeTheme(theme: Theme): void {
  try {
    localStorage.setItem(KEY, theme);
  } catch {
    // Not remembered: the next visit starts from the default.
  }
}
