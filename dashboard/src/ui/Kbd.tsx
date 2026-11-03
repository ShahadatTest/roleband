export function Kbd({ children }: { children: React.ReactNode }) {
  // A key is a thing you press, not a word you quote (docs/ui.md),
  // and its legend is the key's, not copy.
  return <span className="kbd" data-selection="chrome" data-copy="glyph">{children}</span>;
}
