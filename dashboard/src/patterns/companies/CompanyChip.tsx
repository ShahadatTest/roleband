import {
  sharedCompanyChipAria,
  sharedCompanyChipSummary,
  sharedCompanyNoOpenRoles,
  sharedCompanyNotFollowed,
  sharedCompanyOpenRoles,
  sharedCompanyViewProfile,
} from "../../copy/gen/shared";
import "./company-chip.css";
import "./company-logo.css";
import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router-dom";
import { CompanyCard, api } from "../../api";
import { number } from "../../copy/format";
import { COMPANY, companyName, ownValue } from "../../format";
import { CompanyIcon, Content, Icon, hasBrandIcon } from "../../ui";

/** Said in place of a count for a company the user does not follow: the
 *  Board shows followed companies only. Here, beside the hover card
 *  that is in the shell, so the shell carries one sentence and not the row's. */
export function notOnBoardSentence(company: string): string {
  return sharedCompanyNotFollowed({ company });
}

// One shared request per company across every job row that mentions it, and no
// refetch on a second hover. Promises are cached too, so concurrent hovers of the
// same chip coalesce onto one fetch.
const cache = new Map<string, CompanyCard | Promise<CompanyCard>>();

function loadCard(slug: string): CompanyCard | Promise<CompanyCard> {
  const hit = cache.get(slug);
  if (hit) return hit;
  const p = api
    .companyCard(slug)
    .then((c) => {
      cache.set(slug, c);
      return c;
    })
    .catch((e) => {
      cache.delete(slug); // let a later hover retry rather than caching the failure
      throw e;
    });
  cache.set(slug, p);
  return p;
}

// Test seam: reset the cross-render cache between cases.
export function __clearCompanyCardCache() {
  cache.clear();
}

function profilePath(slug: string): string {
  return `/company/${encodeURIComponent(slug)}`;
}

const CENTS = { minimumFractionDigits: 2, maximumFractionDigits: 2 } as const;

/** A share price in the currency it trades in, written the region's way. */
function quote(price: number, currency: string): string {
  try {
    return number(price, { ...CENTS, style: "currency", currency });
  } catch {
    return `${number(price, CENTS)} ${currency}`;
  }
}

function ChangeTag({ pct }: { pct: number | null }) {
  if (pct == null) return null;
  const dir = pct > 0 ? "up" : pct < 0 ? "down" : "flat";
  return (
    <span className={`co-card-change co-change-${dir}`}>
      {number(pct / 100, { ...CENTS, style: "percent", signDisplay: "exceptZero" })}
    </span>
  );
}

function HoverCardBody({ card }: { card: CompanyCard }) {
  const brand = card.brand_color ?? ownValue(COMPANY, card.slug)?.color ?? null;
  // Same preference order as the profile hero: bundled mark, then the remote
  // logo, then a monogram. See CompanyLogo in CompanyProfiles.tsx.
  const mark = hasBrandIcon(card.slug, card.display_name);
  const showImage = !mark && Boolean(card.logo_url);
  return (
    <div className="co-card" role="dialog" aria-label={sharedCompanyChipSummary({ display_name: String(card.display_name) })}>
      <div className="co-card-head">
        {showImage ? (
          <span
            className="company-logo has-img co-card-logo"
            style={{
              background: brand ? `${brand}22` : "var(--app-surface-raised)",
              borderColor: brand ?? "var(--app-border)",
            }}
            aria-hidden="true"
          >
            <img src={card.logo_url!} alt="" loading="lazy" />
          </span>
        ) : (
          <span className="company-logo company-logo-mark co-card-logo">
            <CompanyIcon
              slug={card.slug}
              display={card.display_name}
              size={22}
              brand
              fallbackColor={brand}
            />
          </span>
        )}
        <div className="co-card-id">
          <span className="co-card-name">{card.display_name}</span>
          {card.ticker && <span className="traj-ticker">{card.ticker}</span>}
        </div>
      </div>

      {card.is_public && card.price != null && (
        <div className="co-card-price">
          <span className="co-card-quote">{quote(card.price, card.currency ?? "USD")}</span>
          <ChangeTag pct={card.change_pct} />
        </div>
      )}

      <div className="co-card-roles">
        {card.unfollowed
          ? notOnBoardSentence(card.display_name)
          : card.open_roles > 0
            ? sharedCompanyOpenRoles({ count: card.open_roles })
            : sharedCompanyNoOpenRoles()}
      </div>
      {(card.top_cities?.length ?? 0) > 0 && (
        <div className="co-card-cities">{card.top_cities.join(" · ")}</div>
      )}
      <div className="co-card-hint">
        {sharedCompanyViewProfile()} <Icon name="arrowRight" size={11} />
      </div>
    </div>
  );
}

// Company chip that (a) navigates to the company profile on click and (b) reveals
// a summary card (price, ticker, open-role count) on hover/focus. Used inside
// clickable job rows, so its click must not bubble up and open the job.
// Card dimensions used only for edge-clamping/flip math before it renders.
const CARD_W = 236;
const CARD_H = 190;
const GAP = 6;
const MARGIN = 8;

function placeCard(rect: DOMRect): { top: number; left: number } {
  const left = Math.max(
    MARGIN,
    Math.min(rect.left, window.innerWidth - CARD_W - MARGIN),
  );
  // Below the chip by default; flip above when it would fall off the bottom.
  let top = rect.bottom + GAP;
  if (top + CARD_H > window.innerHeight - MARGIN) top = rect.top - CARD_H - GAP;
  return { top: Math.max(MARGIN, top), left };
}

export function CompanyChip({ slug }: { slug: string }) {
  const navigate = useNavigate();
  const brand = ownValue(COMPANY, slug)?.color;
  const [card, setCard] = useState<CompanyCard | null>(null);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const btnRef = useRef<HTMLButtonElement>(null);
  const revealTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const hideTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const alive = useRef(true);

  useEffect(() => {
    // Must set true in setup, not just false in cleanup: StrictMode runs the
    // cleanup once on mount, which would otherwise pin `alive` false forever and
    // silently swallow every setState below.
    alive.current = true;
    return () => {
      alive.current = false;
      if (revealTimer.current) clearTimeout(revealTimer.current);
      if (hideTimer.current) clearTimeout(hideTimer.current);
    };
  }, []);

  const fetchCard = useCallback(() => {
    if (card) return;
    const r = loadCard(slug);
    if (r instanceof Promise) {
      r.then((c) => alive.current && setCard(c)).catch(() => {});
    } else {
      setCard(r);
    }
  }, [card, slug]);

  const reveal = useCallback(() => {
    if (hideTimer.current) clearTimeout(hideTimer.current);
    fetchCard();
    // Small delay so brushing past a chip doesn't flash the card. Position is
    // captured when it actually opens, off the chip's current viewport rect.
    revealTimer.current = setTimeout(() => {
      if (!alive.current || !btnRef.current) return;
      setPos(placeCard(btnRef.current.getBoundingClientRect()));
    }, 120);
  }, [fetchCard]);

  const hide = useCallback(() => {
    if (revealTimer.current) clearTimeout(revealTimer.current);
    hideTimer.current = setTimeout(() => alive.current && setPos(null), 80);
  }, []);

  const go = useCallback(
    (e: React.MouseEvent | React.KeyboardEvent) => {
      e.stopPropagation();
      navigate(profilePath(slug));
    },
    [navigate, slug],
  );

  const open = pos !== null && card !== null;
  // Identity is the MARK, not a fill: a brand-hex background puts twenty
  // full-chroma plates on a page that is desaturated everywhere else, the
  // loudest pixels on the row decorating its least important fact. The mark
  // carries the brand at 14px (a monogram in a tinted well when no bundled
  // mark exists) and rests MUTED; the chip's own
  // hover and the job row's hover light it in the brand colour.
  // The name sits in the ink of the line it is on.
  const name = companyName(slug);

  return (
    <span className="co-chip-wrap" onMouseEnter={reveal} onMouseLeave={hide}>
      <button
        ref={btnRef}
        type="button"
        className="chip chip-co"
        onClick={go}
        onFocus={reveal}
        onBlur={hide}
        aria-label={sharedCompanyChipAria({ company: name })}
      >
        <CompanyIcon slug={slug} display={name} size={14} fallbackColor={brand ?? card?.brand_color ?? null} />
        <Content text={name} />
      </button>
      {/* Portalled to <body> so it escapes the job row's stacking context — each
          row establishes one via its entrance transform, which would otherwise let
          later rows paint their chips/titles on top of the card. */}
      {open &&
        createPortal(
          <span
            className="co-card-portal"
            style={{ top: pos!.top, left: pos!.left }}
            onMouseEnter={reveal}
            onMouseLeave={hide}
            onClick={go}
          >
            <HoverCardBody card={card!} />
          </span>,
          document.body,
        )}
    </span>
  );
}
