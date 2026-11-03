import { useCallback } from "react";
import { BoardScreen } from "../features/opportunities/BoardScreen";
import { MODE_PARAM, MODE_PARAMS, modeFromParam, type BoardMode } from "../features/opportunities/filters";
import { useSearchParam } from "../routing/useSearchParam";
import { useSearchParamList } from "../routing/useSearchParamList";

export function BoardRoute() {
  const [companyParam, onCompanyParamChange] = useSearchParamList("company");
  /* `?show=closed` / `?show=not-for-me`; absent is open, which is the board's
     default view and the one the top bar's "N open roles" links back to.
     Same shape as `?company=`: the route TRANSLATES, the screen
     owns the semantics. `useSearchParam` drops the key at the fallback, so an
     open board has a clean address and the link's plain `/` reaches it. */
  const [showParam, onShowParamChange] = useSearchParam("show", {
    options: MODE_PARAMS,
    fallback: MODE_PARAM.open,
  });
  /* Stable, because the screen mirrors the mode from an effect: a callback
     rebuilt every render makes that effect fire every render. */
  const mode = modeFromParam(showParam);
  const onModeChange = useCallback(
    (next: BoardMode) => onShowParamChange(MODE_PARAM[next]),
    [onShowParamChange],
  );
  return (
    <BoardScreen
      companyParam={companyParam}
      onCompanyParamChange={onCompanyParamChange}
      mode={mode}
      onModeChange={onModeChange}
    />
  );
}
