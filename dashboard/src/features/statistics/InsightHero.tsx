import { number as copyNumber } from "../../copy/format";
import type { ReactNode } from "react";
import { STATISTICS_TABS } from "../../navTabs";

/* Every Insights tab opens with this, so each leads with its answer under its
 * own name.
 *
 * The eyebrow is read from the tab list by slug, so it cannot drift from the
 * tab's own label. The figure is the answer, the line its scope (which roles,
 * which period), the tiles at most four supporting numbers. */

export interface HeroKpi {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  tone?: "good" | "bad";
  /** A range ("$423K–$768K") rather than one number: a smaller numeral. */
  wide?: boolean;
}

function tabLabel(slug: string): string {
  const tab = STATISTICS_TABS.find((t) => t.slug === slug);
  if (!tab) throw new Error(`no Insights tab "${slug}"`);
  return tab.label;
}

export function InsightHero({
  tab,
  figure,
  line,
  kpis,
  className,
  children,
}: {
  /** The tab's slug (`/statistics/:tab`); its label is the eyebrow. */
  tab: string;
  figure: ReactNode;
  line?: ReactNode;
  kpis: readonly HeroKpi[];
  className?: string;
  /** Below the line: a control the figure answers to (Stock's price slider). */
  children?: ReactNode;
}) {
  return (
    <div className={`panel cockpit insight-hero${className ? ` ${className}` : ""}`}>
      <div className="cockpit-lead">
        <span className="eyebrow">{tabLabel(tab)}</span>
        <h2 className="cockpit-figure">{figure}</h2>
        {line && <p>{line}</p>}
        {children}
      </div>
      {kpis.length > 0 && (
        <div className="cockpit-kpis">
          {kpis.slice(0, 4).map((k) => (
            <div className="kpi" key={k.label}>
              <span className="kpi-l">{k.label}</span>
              <span className={`kpi-n${k.tone ? ` ${k.tone}` : ""}${k.wide ? " wide" : ""}`}>{k.value}</span>
              {k.sub != null && <span className="kpi-s">{k.sub}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/** A count as tiles and sentences print it: `3,192`, never `3192`. */
export const n = (value: number) => copyNumber(value);
