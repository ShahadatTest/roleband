/* The board's MODE vocabulary and its name in the query string, alone.
 *
 * Its own module, with no imports, because the app shell reads it too: the top
 * bar lights "open roles" only when the board IS the open board, and
 * importing it from `filters.ts` would put the whole filter-ownership table in
 * the eager shell chunk, over the bundle gate, for one comparison. The
 * semantics (what each mode filters, how it counts) stay in `filters.ts`, which
 * re-exports everything here.
 */
export const BOARD_MODES = ["open", "closed", "dismissed"] as const;
export type BoardMode = (typeof BOARD_MODES)[number];

/* The product's words, not the system's (docs/copy.md): a role
 * you send away is "Not for me" on the button, in the beacon and here. The
 * API's own name for it is `dismissed_only`. */
/* The mode's name in the query string. It is URL-backed for one
 * concrete reason: the top bar's "N open roles" is a LINK to `/`, and a link
 * can only put the board back in its default view if the departure from that
 * view is in the URL to begin with. `open` is the fallback, so the default
 * board keeps a clean address. */
export const MODE_PARAM: Record<BoardMode, string> = {
  open: "open",
  closed: "closed",
  dismissed: "not-for-me",
};

export function modeFromParam(param: string): BoardMode {
  return (BOARD_MODES.find((mode) => MODE_PARAM[mode] === param) ?? "open");
}
