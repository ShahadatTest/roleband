import { ReactNode, createContext, createElement, useContext } from "react";
import { useLocation } from "react-router-dom";

/* WHICH SCREEN THE READER IS ON — the pathname, and nothing cleverer.
 *
 * Two things it deliberately does NOT do:
 *
 * A COVER IS ITS OWN SCREEN. A role detail and the comparison
 * open as a full-screen cover over the list they were reached from; that list
 * stays MOUNTED and keeps its scroll and filters, and history remembers it as
 * `backgroundLocation` (`paths.coverBackground`) so Back pops back to it. It is
 * mounted, but it is not what the reader is looking at — the cover is over it,
 * and the comparison's is a modal `dialog`. Reading through to the background
 * would put a toast raised INSIDE the comparison on the board underneath:
 * remove a role in the cover, click Radar, and the toast stays on the board it
 * was assigned to.
 *
 * A QUERY IS NOT A SCREEN. The board's filters, a search, a sort and a page all
 * rewrite the search string without the reader going anywhere, and a filter edit
 * must not cancel a confirmation it had nothing to do with.
 *
 * AND THE ANSWER DOES NOT DEPEND ON WHERE YOU ASK. Under a cover the
 * list is routed with `<Routes location={background}>` (App.tsx), and that
 * override is what `useLocation()` returns to everything inside it — so a
 * component ON the list asking which screen the reader is on would be told
 * "the list" while the reader looks at the comparison. The toast host asks
 * from the app root; the compare roster asks from the list, and would stay
 * open over the cover it had just opened. `ScreenProvider` reads the
 * location once, above both slots, and every `useScreenKey()` below it reads
 * that. With no provider — a test rendering one screen — it falls back to the
 * nearest location, which there is the same thing.
 */
const ReaderScreen = createContext<string | null>(null);

export function ScreenProvider({ children }: { children: ReactNode }) {
  return createElement(ReaderScreen.Provider, { value: useLocation().pathname }, children);
}

export function useScreenKey(): string {
  const reader = useContext(ReaderScreen);
  const nearest = useLocation().pathname;
  return reader ?? nearest;
}

/* Re-exported so a consumer below F2 asks routing about routing, and so a
   primitive that can work without a Router has one place to check for it. */
export { useInRouterContext } from "react-router-dom";
