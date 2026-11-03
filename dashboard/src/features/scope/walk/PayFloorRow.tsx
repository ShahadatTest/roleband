import { useEffect, useRef, useState, type FormEvent } from "react";
import type { PayFloor } from "../../../api";
import { api } from "../../../api";
import { fmtMoney } from "../../../money";
import { useWriteQueue } from "../../../hooks/useWriteQueue";
import { Button, Icon, useEscapeLayer } from "../../../ui";
import { Select } from "../../../ui/Select";
import {
  profilePayFloorRowAYearBase,
  profilePayFloorRowAddAPayFloor,
  profilePayFloorRowCancel,
  profilePayFloorRowChecking,
  profilePayFloorRowComparedWherePayIsStated,
  profilePayFloorRowCouldNotRemoveThePay,
  profilePayFloorRowCouldNotSaveThePay,
  profilePayFloorRowCouldnTReadYourPay,
  profilePayFloorRowCurrency,
  profilePayFloorRowEnterAYearlyAmountLike,
  profilePayFloorRowLowestYearlyBasePay,
  profilePayFloorRowMinimumYearlyBasePay,
  profilePayFloorRowNoRolesAreHidden,
  profilePayFloorRowPayFloor,
  profilePayFloorRowPayFloor2,
  profilePayFloorRowRetry,
  profilePayFloorRowRetryReadingThePayFloor,
  profilePayFloorRowSaveFloor,
  profilePayFloorRowSetFloor,
  profilePayFloorRowSetYourPayFloor,
  profileScopeSectionRemove,
} from "../../../copy/gen/profile";

/* The pay floor, the Summary's one OPTIONAL answer. Not a Walk
   question: disclosed pay exists only in some postings and some countries, so
   for many people it does nothing. It narrows nothing
   either: the funnel and the Board never read it. Saved on its own, apart
   from the Walk's save, because it is not part of the scope. In first-run
   setup (`held`) it saves nothing: Save and Remove change only what the row
   shows, and setup's Start writes it after the scope, so Start stays the one
   save and "Set up later" leaves nothing behind.

   Save and Remove are two writers of one setting, so both go through one
   write queue: the setting ends as the last thing the person asked for, not
   whichever request the server answered last. */

const CURRENCIES = ["USD", "CAD", "GBP", "EUR", "CHF", "AUD", "SGD", "INR", "JPY"];

/** The country of each currency above, by the scope catalog's country slug. */
const COUNTRY_CURRENCY: Record<string, string> = {
  united_states: "USD", canada: "CAD", uk: "GBP", switzerland: "CHF", australia: "AUD",
  singapore: "SGD", india: "INR", japan: "JPY",
  ...Object.fromEntries([
    "austria", "belgium", "croatia", "cyprus", "estonia", "finland", "france", "germany", "greece",
    "ireland", "italy", "latvia", "lithuania", "luxembourg", "malta", "netherlands", "portugal",
    "slovakia", "slovenia", "spain",
  ].map((country) => [country, "EUR"])),
};

/** The currency a new floor starts in: that of the first chosen place inside a
    country the menu has a currency for, walking up from a metro or city to its
    country. USD when none is. */
export function currencyForPlaces(
  places: Iterable<string>,
  locations: readonly { slug: string; parent: string | null }[],
): string {
  const parentOf = new Map(locations.map((location) => [location.slug, location.parent]));
  for (const place of places) {
    for (let at: string | null | undefined = place, hops = 0; at && hops < 6; at = parentOf.get(at), hops += 1) {
      const currency = COUNTRY_CURRENCY[at];
      if (currency) return currency;
    }
  }
  return "USD";
}

/** The backend's `PAY_FLOOR_MAX` (settings_store.py): above it the API
    answers 422, so the form says so before sending. */
const PAY_FLOOR_MAX = 100_000_000;

/** A yearly amount as people write one: "250000", "250,000", "250,000.00",
    "250k" or "1.5m" (the app itself prints "$250K"). Whole units. At most two
    decimals, so "250.000", a thousands separator in much of Europe, is never
    read as 250. */
export function parseAmount(raw: string): number | null {
  const match = /^(\d+(?:\.\d{1,2})?)([km])?$/i.exec(raw.replace(/[\s,]/g, ""));
  if (!match) return null;
  const unit = { k: 1_000, m: 1_000_000 }[(match[2] ?? "").toLowerCase()] ?? 1;
  const amount = Math.round(Number(match[1]) * unit);
  return amount > 0 && amount <= PAY_FLOOR_MAX ? amount : null;
}

export function PayFloorRow({
  floor, status, onRetry, onChange, held = false, startCurrency = "USD",
}: {
  floor: PayFloor | null;
  /** The stored floor's read: nothing is offered until it is known, or "Add"
      over a floor that failed to load would overwrite it. */
  status: "loading" | "error" | "ready";
  onRetry: () => void;
  onChange: (floor: PayFloor | null) => void;
  held?: boolean;
  /** The currency the editor opens in when there is no floor yet. */
  startCurrency?: string;
}) {
  const [editing, setEditing] = useState(false);
  const [amount, setAmount] = useState("");
  const [currency, setCurrency] = useState("USD");
  const [error, setError] = useState<string | null>(null);
  const { exclusive, writing } = useWriteQueue("pay-floor");
  const inputRef = useRef<HTMLInputElement>(null);
  const openRef = useRef<HTMLButtonElement>(null);
  const returnFocus = useRef(false);

  // Focus follows the editor: into the amount on open, back to the opener on
  // close, as the aim line does (AimLine.tsx).
  useEffect(() => {
    if (editing) inputRef.current?.focus();
    else if (returnFocus.current) {
      returnFocus.current = false;
      openRef.current?.focus();
    }
  }, [editing]);

  const open = () => {
    setAmount(floor ? String(floor.amount) : "");
    setCurrency(floor?.currency ?? startCurrency);
    setError(null);
    setEditing(true);
  };
  const close = () => {
    returnFocus.current = true;
    setEditing(false);
  };
  useEscapeLayer(editing, writing ? undefined : close, "page");

  /* Held, an amount typed but not yet set still counts when the person moves
     on without pressing Set: leaving the Summary unmounts the row, and a valid
     amount left in the box is what they meant. Cancel and Escape close the
     editor first, so they keep nothing. */
  const pending = useRef<PayFloor | null>(null);
  const parsedNow = editing ? parseAmount(amount) : null;
  pending.current = held && parsedNow != null ? { amount: parsedNow, currency } : null;
  const keep = useRef(onChange);
  keep.current = onChange;
  useEffect(() => () => {
    if (pending.current) keep.current(pending.current);
  }, []);

  const run = (write: () => Promise<{ pay_floor: PayFloor | null }>, failed: string) => {
    setError(null);
    exclusive(["pay-floor"], write)
      .then((result) => {
        onChange(result.pay_floor);
        close();
      })
      .catch(() => setError(failed));
  };

  const save = (event: FormEvent) => {
    event.preventDefault();
    const parsed = parseAmount(amount);
    if (parsed == null) {
      setError(profilePayFloorRowEnterAYearlyAmountLike());
      return;
    }
    const next = { amount: parsed, currency };
    run(held ? async () => ({ pay_floor: next }) : () => api.savePayFloor(next), profilePayFloorRowCouldNotSaveThePay());
  };

  // A stored currency outside the list is offered as it is, never quietly
  // swapped for USD by an Adjust that changed only the amount.
  const options = (CURRENCIES.includes(currency) ? CURRENCIES : [currency, ...CURRENCIES])
    .map((value) => ({ value, label: value }));

  return (
    <section className="walk-summary-block walk-summary-pay" aria-labelledby="walk-pay-floor-title">
      <h3 className="walk-summary-section-title" id="walk-pay-floor-title">{profilePayFloorRowPayFloor()}</h3>
      {editing ? (
        <form className="walk-floor-form" onSubmit={save} aria-label={profilePayFloorRowPayFloor2()}>
          <input
            ref={inputRef}
            className="walk-floor-amount"
            aria-label={profilePayFloorRowLowestYearlyBasePay()}
            inputMode="numeric"
            placeholder="250000"
            value={amount}
            disabled={writing}
            onChange={(event) => {
              setAmount(event.target.value);
              setError(null);
            }}
          />
          <Select label={profilePayFloorRowCurrency()} value={currency} onChange={setCurrency} options={options} disabled={writing} />
          <span className="walk-floor-unit">{profilePayFloorRowAYearBase()}</span>
          <Button type="submit" variant="ghost" disabled={writing}>
            {held ? profilePayFloorRowSetFloor() : profilePayFloorRowSaveFloor({ choice: (writing) ? "yes" : "no" })}
          </Button>
          <Button variant="link" className="ui-btn-quiet" onClick={close} disabled={writing}>
            {profilePayFloorRowCancel()}
          </Button>
          {floor && (
            <Button
              variant="link"
              className="ui-btn-quiet"
              disabled={writing}
              onClick={() => run(held ? async () => ({ pay_floor: null }) : api.clearPayFloor, profilePayFloorRowCouldNotRemoveThePay())}
            >
              {profileScopeSectionRemove()}
            </Button>
          )}
          {error && <span className="walk-floor-error" role="alert">{error}</span>}
        </form>
      ) : status === "loading" ? (
        <span className="walk-fact-text walk-floor-pending">{profilePayFloorRowChecking()}</span>
      ) : status === "error" ? (
        <>
          <span className="walk-fact-text">{profilePayFloorRowCouldnTReadYourPay()}</span>
          <Button variant="link" className="ui-btn-quiet walk-summary-adjust" aria-label={profilePayFloorRowRetryReadingThePayFloor()} onClick={onRetry}>
            {profilePayFloorRowRetry()}
          </Button>
        </>
      ) : (
        <>
          <Button
            ref={openRef}
            size="lg"
            className="ui-btn-strong ui-btn-tile"
            aria-label={profilePayFloorRowAddAPayFloor({ choice: (floor) ? "yes" : "no" })}
            aria-expanded={false}
            onClick={open}
          >
            <Icon name="sliders" size={20} />
            <span className="ui-btn-tile-copy">
              <span className="ui-btn-tile-title" data-selection={floor ? "content" : undefined}>{profilePayFloorRowSetYourPayFloor({ choice: (floor) ? "yes" : "no", amount: (floor) ? String(fmtMoney(floor.amount, floor.currency)) : "" })}</span>
              <span className="ui-btn-tile-description">{profilePayFloorRowMinimumYearlyBasePay({ choice: (floor) ? "yes" : "no" })}</span>
            </span>
            <Icon name="chevronDown" />
          </Button>
        </>
      )}
      <p className="walk-note">{profilePayFloorRowComparedWherePayIsStated()}</p>
      <p className="walk-note">{profilePayFloorRowNoRolesAreHidden()}</p>
    </section>
  );
}
