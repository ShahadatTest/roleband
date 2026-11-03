import { useCallback } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { CompareScreen } from "../features/compare/CompareScreen";

/* The comparison as a routed cover. Opened from the list the roles
   were picked on it covers that list, which stays mounted with its scroll and
   filters; Back pops history. Reached by URL or refresh there is nothing
   underneath, so Back goes to the Radar. Which SHELL it wears is the slot's
   call (App renders the overlay routes separately), because a comparison with
   a role stacked on it carries a background and must still be the page. */
export function CompareRoute({ asOverlay = false }: { asOverlay?: boolean }) {
  const navigate = useNavigate();
  const location = useLocation();
  const hasBackground = Boolean((location.state as { backgroundLocation?: unknown } | null)?.backgroundLocation);
  const onBack = useCallback(() => {
    if (hasBackground) navigate(-1);
    else navigate("/");
  }, [hasBackground, navigate]);
  return <CompareScreen asOverlay={asOverlay} onBack={onBack} />;
}
