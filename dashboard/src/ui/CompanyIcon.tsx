// Company brand mark, with a monogram fallback.
//
// Most of the catalog has a Simple Icons mark; the rest (consultancies,
// quant firms, defence startups, plus brands removed upstream on request) get a
// brand-tinted monogram. Both render at the same size in the same frame, so a
// list of companies reads as one system rather than "logos, and then the others".
//
// Colour is emitted as BOTH theme variants up front (`--brand-l` / `--brand-d`)
// and CSS picks. A primitive cannot read the theme — it lives in App state and
// F1 must not import F2 — and this avoids a MutationObserver per icon besides.
import { useEffect, useRef, useState, type RefObject } from "react";
import { brandInk, hslToHex } from "./brandColor";
import { hasBrandIcon, loadBrandIcon, resolveBrandIcon, type BrandIcon } from "./brandIcons";
import "./CompanyIcon.css";

// One observer for every mark waiting on a shard. A company page can list
// thousands of companies, and a shard is hundreds of kilobytes: a mark no one
// can see yet must not fetch one. The observer goes once nothing waits.
let watcher: IntersectionObserver | null = null;
const waiting = new Map<Element, () => void>();

function stopWaiting(element: Element): void {
  if (!waiting.delete(element)) return;
  watcher?.unobserve(element);
  if (waiting.size === 0) {
    watcher?.disconnect();
    watcher = null;
  }
}

/** Calls `near` once `element` is within a screen of the viewport. With no
 *  IntersectionObserver (jsdom) it calls it at once. Returns the cancel. */
function whenNearScreen(element: Element, near: () => void): () => void {
  if (typeof IntersectionObserver === "undefined") {
    near();
    return () => {};
  }
  watcher ??= new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      const call = waiting.get(entry.target);
      stopWaiting(entry.target);
      call?.();
    }
  }, { rootMargin: "100% 0px" });
  waiting.set(element, near);
  watcher.observe(element);
  return () => stopWaiting(element);
}

/**
 * Resolves a company's mark, reaching past the bundled set when needed.
 *
 * Seeds synchronously from the eager set so a catalog company never flashes a
 * monogram first. Only a company the build did not know about takes the async
 * path, and only when the manifest says a mark exists and the mark comes near
 * the screen, so an uncovered company never schedules an update at all.
 */
function useBrandIcon(slug: string, display: string, frame: RefObject<HTMLElement | null>): BrandIcon | null {
  const [icon, setIcon] = useState<BrandIcon | null>(() => resolveBrandIcon(slug, display));

  useEffect(() => {
    const eager = resolveBrandIcon(slug, display);
    if (eager) {
      setIcon(eager);
      return;
    }
    setIcon(null);
    const element = frame.current;
    if (!element || !hasBrandIcon(slug, display)) return;
    // Guard against a late resolution landing after the props moved on.
    let alive = true;
    const cancel = whenNearScreen(element, () => {
      void loadBrandIcon(slug, display).then((found) => {
        if (alive && found) setIcon(found);
      });
    });
    return () => {
      alive = false;
      cancel();
    };
  }, [slug, display, frame]);

  return icon;
}

export interface CompanyIconProps {
  slug: string;
  display: string;
  size?: number;
  /** Paint the mark in its brand colour instead of inheriting text colour. Use
   *  for hero/selected states; the design system reserves saturated colour for
   *  meaning, so a dense grid should leave this off and let :hover do it. */
  brand?: boolean;
  /** Brand colour for companies with no mark, e.g. `profile.brand_color`.
   *  Ignored when Simple Icons supplies one. */
  fallbackColor?: string | null;
  className?: string;
}

/** Stable hue per slug so an uncovered company keeps the same monogram colour
 *  everywhere, instead of a grey box or a colour that moves between screens.
 *  Must return HEX: brandInk parses nothing else and would fall through to
 *  currentColor, and the monogram would lose its tint. */
function hueFor(slug: string): string {
  let h = 0;
  for (let i = 0; i < slug.length; i += 1) h = (h * 31 + slug.charCodeAt(i)) % 360;
  return hslToHex(h, 0.45, 0.45);
}

export function CompanyIcon({
  slug,
  display,
  size = 20,
  brand = false,
  fallbackColor = null,
  className = "",
}: CompanyIconProps) {
  const frame = useRef<HTMLSpanElement>(null);
  const icon = useBrandIcon(slug, display, frame);
  const raw = icon?.hex ?? fallbackColor ?? hueFor(slug);
  const style = {
    "--brand-l": brandInk(raw, "light"),
    "--brand-d": brandInk(raw, "dark"),
    width: size,
    height: size,
  } as React.CSSProperties;
  const cls = `ui-company-icon${brand ? " is-brand" : ""}${className ? ` ${className}` : ""}`;

  if (!icon) {
    return (
      <span ref={frame} className={`${cls} is-monogram`} style={style} aria-hidden="true">
        {/* Drawn from the attribute, not written as text: the letter stands in
            for a logo, and as text it would join the visible label of whatever
            control holds the icon ("OOpenAI"). */}
        <span style={{ fontSize: Math.round(size * 0.5) }} data-letter={display.slice(0, 1).toUpperCase()} />
      </span>
    );
  }
  return (
    <span ref={frame} className={cls} style={style} aria-hidden="true">
      <svg viewBox="0 0 24 24" width={size} height={size} role="presentation">
        {/* Simple Icons marks are single-path solids — no stroke, unlike the
            Lucide UI set. Do not add strokeWidth here. */}
        <path d={icon.path} fill="currentColor" />
      </svg>
    </span>
  );
}
