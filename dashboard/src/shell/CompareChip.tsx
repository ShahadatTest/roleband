import { shellCompareChip, shellCompareChipAria, shellCompareChipTitle } from "../copy/gen/shell";
import { useLocation } from "react-router-dom";
import { useJobWorkspace } from "../context/JobWorkspace";
import { COMPARE_ROUTE, coverBackground } from "../routing/paths";
import { StatChip } from "./StatChip";

/* The standing comparison, stated on every screen. Compare is not in the
 * rail, so this chip is the one place the selection is visible from Insights
 * or Settings, beside the other counts the top bar carries. From two,
 * because that is when a comparison exists — the beacon raises at two for the
 * same reason. A link with a real href: the comparison IS a URL, and a
 * modifier-click opens it standalone. Its own component so a compare toggle
 * re-renders this chip and nothing else in the shell. */
export function CompareChip() {
  const { compareIds } = useJobWorkspace();
  const location = useLocation();
  const n = compareIds.size;
  if (n < 2) return null;
  const here = location.pathname === COMPARE_ROUTE;
  return (
    <StatChip
      kind="link"
      to={COMPARE_ROUTE}
      state={here ? location.state : { backgroundLocation: coverBackground(location) }}
      n={n}
      label={shellCompareChip()}
      ariaLabel={shellCompareChipAria({ count: n })}
      title={shellCompareChipTitle()}
    />
  );
}
