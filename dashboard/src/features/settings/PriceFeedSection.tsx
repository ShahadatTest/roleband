// The key dialog wears the register's dialog form (`.ledger-form`), as the
// plugin dialogs on this tab do: import it rather than lean on another
// screen's chunk having loaded it.
import "../../design/materials/register-material.css";
import { useState, type FormEvent } from "react";
import { PRICE_FEED_KEY_URL, PriceFeedState, api } from "../../api";
import { errorText } from "../../api/errorText";
import { calendarDay, relative } from "../../copy/format";
import { useAsyncResource, useRefetchOn } from "../../hooks/useAsyncResource";
import { useJob, usePricesVersion } from "../../context/SyncState";
import { AsyncBoundary, Button, Dialog, ExternalLink } from "../../ui";
import { Card, CardMessage, CardRow } from "../../ui/Card";
import {
  settingsSaveFailed,
  settingsCancel,
  settingsPriceFeedAdd,
  settingsPriceFeedDialogField,
  settingsPriceFeedDialogNote,
  settingsPriceFeedDialogSave,
  settingsPriceFeedDialogTitle,
  settingsPriceFeedIntro,
  settingsPriceFeedKeyState,
  settingsPriceFeedLoadFailed,
  settingsPriceFeedPriced,
  settingsPriceFeedRateLimited,
  settingsPriceFeedRemove,
  settingsPriceFeedRemoved,
  settingsPriceFeedReplace,
  settingsPriceFeedSaved,
  settingsPriceFeedSource,
  settingsPriceFeedSourceTerms,
  settingsPriceFeedTitle,
  settingsPriceFeedUnauthorized,
  settingsPriceFeedUpdateNow,
  settingsPriceFeedUpdated,
  settingsPriceFeedUpdating,
  settingsPriceFeedWaiting,
  settingsLoading,
} from "../../copy/gen/settings";
import { sharedPriceFeedGetKey } from "../../copy/gen/shared";

// Settings > Plugins > Stock prices. One kit
// row, as the plugin rows above it: the service by name, the terms its key
// comes with and where to get one, then the facts (whether a key is set and
// where, how many companies have a price, the newest close, when prices last
// updated) and the actions. The key is write-only: the API never sends it
// back, so the card never shows a field holding nothing; it is typed in a
// dialog, as the AI tab's online-service key is. A key set in the environment
// works too; one saved here wins.

const ago = (iso: string) => relative((new Date(iso).getTime() - Date.now()) / 1000);

/** The row's facts, joined as the plugin rows join theirs. Counts and times
 *  only. While the prices job runs, that is the last fact; what it left for
 *  Tiingo's limits says how many and when the next batch can start. */
function facts(state: PriceFeedState, updating: boolean): string {
  const parts = [settingsPriceFeedKeyState({ origin: state.origin ?? "none" })];
  if (state.priced > 0 && state.as_of !== null) {
    parts.push(settingsPriceFeedPriced({ count: state.priced, date: String(calendarDay(state.as_of)) }));
  }
  if (updating) parts.push(settingsPriceFeedUpdating());
  else if (state.configured && state.last_run_at) parts.push(settingsPriceFeedUpdated({ ago: String(ago(state.last_run_at)) }));
  if (state.configured && !updating && state.waiting > 0 && state.next_at) {
    parts.push(settingsPriceFeedWaiting({ count: state.waiting, time: String(ago(state.next_at)) }));
  }
  return parts.join(" · ");
}

/** The dialog opens on its field: a child that focuses itself in a callback
 *  ref wins over the overlay's own focus capture (`ui/Overlay`). Module-level,
 *  so its identity never changes and a re-render never refocuses. */
const takeFocus = (el: HTMLInputElement | null) => el?.focus();

function KeyDialog({ onClose, onSaved }: { onClose: () => void; onSaved: (next: PriceFeedState) => void }) {
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const key = draft.trim();
    if (!key) return;
    setSaving(true);
    setError(null);
    try {
      onSaved(await api.savePriceFeedKey(key));
    } catch (caught) {
      setError(errorText(caught, settingsSaveFailed()));
      setSaving(false);
    }
  };

  return (
    <Dialog isOpen onClose={onClose} label={settingsPriceFeedDialogTitle()} width={480} className="app-overlay">
      <form className="ledger-form ledger-confirm" onSubmit={submit} data-testid="price-feed-dialog">
        <h3>{settingsPriceFeedDialogTitle()}</h3>
        <p>
          {settingsPriceFeedDialogNote()}{" "}
          <ExternalLink href={PRICE_FEED_KEY_URL}>{sharedPriceFeedGetKey()}</ExternalLink>
        </p>
        <div>
          <label htmlFor="price-feed-key">{settingsPriceFeedDialogField()}</label>
          <input
            id="price-feed-key"
            type="password"
            autoComplete="off"
            spellCheck={false}
            ref={takeFocus}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            disabled={saving}
          />
        </div>
        {error && <p className="ledger-form-error" role="alert">{error}</p>}
        <div className="ledger-form-actions">
          <Button onClick={onClose}>{settingsCancel()}</Button>
          <Button type="submit" variant="primary" disabled={saving || !draft.trim()}>
            {settingsPriceFeedDialogSave({ choice: saving ? "yes" : "no" })}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

export function PriceFeedSection() {
  const feed = useAsyncResource<PriceFeedState>(() => api.priceFeed(), []);
  const { mutate, refresh } = feed;
  // The shared status poll says when the prices job runs; its end re-reads the card.
  const job = useJob("prices");
  const updating = job?.state === "running" || job?.state === "starting";
  useRefetchOn(usePricesVersion(), refresh);
  const [editing, setEditing] = useState(false);
  const [removing, setRemoving] = useState(false);
  const [asking, setAsking] = useState(false);
  const [done, setDone] = useState<"saved" | "removed" | null>(null);
  const [check, setCheck] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const saved = (next: PriceFeedState) => {
    mutate(() => next);
    setEditing(false);
    setError(null);
    setCheck(next.key_check ?? null);
    setDone("saved");
  };

  const updateNow = async () => {
    setAsking(true);
    setError(null);
    try {
      const next = await api.refreshPriceFeed();
      mutate(() => next);
    } catch (caught) {
      setError(errorText(caught, settingsSaveFailed()));
    } finally {
      setAsking(false);
    }
  };

  const remove = async () => {
    setRemoving(true);
    setDone(null);
    setError(null);
    try {
      const next = await api.removePriceFeedKey();
      mutate(() => next);
      setDone("removed");
    } catch (caught) {
      setError(errorText(caught, settingsSaveFailed()));
    } finally {
      setRemoving(false);
    }
  };

  return (
    <Card title={settingsPriceFeedTitle()} intro={settingsPriceFeedIntro()}>
      <AsyncBoundary
        resource={feed}
        failed={settingsPriceFeedLoadFailed()}
        skeleton={<CardRow title={settingsPriceFeedSource()} facts={settingsLoading()} />}
      >
        {(state) => (
          <>
            <CardRow
              testId="price-feed-row"
              title={settingsPriceFeedSource()}
              description={
                <>
                  {settingsPriceFeedSourceTerms()}{" "}
                  <ExternalLink href={PRICE_FEED_KEY_URL}>{sharedPriceFeedGetKey()}</ExternalLink>
                </>
              }
              facts={<span data-testid="price-feed-facts">{facts(state, updating)}</span>}
              trailing={
                <>
                  {state.configured && (
                    <Button size="sm" disabled={asking || updating || removing} onClick={() => void updateNow()}>
                      {settingsPriceFeedUpdateNow()}
                    </Button>
                  )}
                  <Button size="sm" className="ui-btn-strong" disabled={removing} onClick={() => { setDone(null); setEditing(true); }}>
                    {state.origin === "settings" ? settingsPriceFeedReplace() : settingsPriceFeedAdd()}
                  </Button>
                  {state.origin === "settings" && (
                    <Button size="sm" disabled={removing} onClick={() => void remove()}>
                      {settingsPriceFeedRemove()}
                    </Button>
                  )}
                </>
              }
            />
            {state.configured && state.refused === "unauthorized" && (
              <CardMessage role="alert">{settingsPriceFeedUnauthorized()}</CardMessage>
            )}
            {state.configured && state.refused === "rate_limited" && (
              <CardMessage tone="info" role="status">{settingsPriceFeedRateLimited()}</CardMessage>
            )}
          </>
        )}
      </AsyncBoundary>
      {done === "saved" && (
        <CardMessage tone={check === "ok" ? "positive" : "info"} role="status">
          {settingsPriceFeedSaved({ check: check === "ok" ? "ok" : "other" })}
        </CardMessage>
      )}
      {done === "removed" && <CardMessage tone="positive" role="status">{settingsPriceFeedRemoved()}</CardMessage>}
      {error && <CardMessage role="alert">{error}</CardMessage>}
      {editing && <KeyDialog onClose={() => setEditing(false)} onSaved={saved} />}
    </Card>
  );
}
