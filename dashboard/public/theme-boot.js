// Set the saved theme before first paint to avoid a flash. A file, not an
// inline script: the Content-Security-Policy allows scripts from this origin only.
// Storage can throw on access (blocked site data): the default theme then.
var theme = "dark";
try {
  if (localStorage.getItem("theme") === "light") theme = "light";
} catch (e) {
  // Blocked site data: keep the default.
}
// First-run setup is always dark (shownTheme in src/shell/theme.ts): the
// welcome page and the setup walk paint dark from the first frame.
if (location.pathname === "/welcome" || /[?&]setup=/.test(location.search)) theme = "dark";
document.documentElement.setAttribute("data-theme", theme);
// The welcome's planet stands on the plain ground, without the ambient wash
// whose warm corner reads as a stray light beside it. A launch at "/" may be a
// fresh install on its way there, so it starts plain too; the app hands the
// wash back once it shows anything else (App.tsx).
if (location.pathname === "/" || location.pathname === "/welcome") {
  document.documentElement.setAttribute("data-ground", "plain");
}
