import { useId } from "react";
import "./EmptyState.css";

export type EmptyStateVariant = "page" | "inline" | "preview";
export type EmptyStateArt = "chart" | "rows";

/* A made-up series of daily closes, the same for every chart, in a
 * 240 x 100 box. It is never a company's prices: the ghost shows what kind of
 * content belongs here and says nothing about any stock. */
const GHOST_LINE =
  "M0.0,41.0L2.0,39.5L4.0,38.6L6.1,42.0L8.1,35.9L10.1,37.7L12.1,40.3L14.1,38.9L16.1,37.9L18.2,35.9L20.2,32.1L22.2,34.1L24.2,33.5L26.2,33.7L28.2,36.7L30.3,33.6L32.3,33.1L34.3,37.3L36.3,34.3L38.3,38.4L40.3,40.1L42.4,37.0L44.4,41.2L46.4,39.8L48.4,37.8L50.4,38.2L52.4,32.4L54.5,33.0L56.5,36.9L58.5,36.1L60.5,31.7L62.5,37.5L64.5,36.4L66.6,39.5L68.6,42.6L70.6,44.4L72.6,43.6L74.6,45.5L76.6,43.4L78.7,45.2L80.7,50.0L82.7,48.4L84.7,49.6L86.7,51.6L88.7,52.9L90.8,55.8L92.8,53.7L94.8,55.3L96.8,56.6L98.8,60.5L100.8,59.0L102.9,59.9L104.9,60.8L106.9,57.1L108.9,56.4L110.9,54.6L112.9,59.0L115.0,55.2L117.0,58.1L119.0,54.4L121.0,51.4L123.0,50.2L125.0,53.9L127.1,52.4L129.1,55.3L131.1,53.5L133.1,51.4L135.1,53.7L137.1,52.7L139.2,56.4L141.2,50.3L143.2,51.8L145.2,50.1L147.2,50.4L149.2,50.5L151.3,51.1L153.3,52.8L155.3,57.2L157.3,58.1L159.3,64.9L161.3,65.0L163.4,68.8L165.4,66.2L167.4,63.8L169.4,63.1L171.4,69.8L173.4,65.7L175.5,57.9L177.5,55.1L179.5,47.5L181.5,43.4L183.5,35.0L185.5,25.6L187.6,29.0L189.6,25.3L191.6,26.6L193.6,25.2L195.6,22.1L197.6,23.7L199.7,24.7L201.7,29.3L203.7,33.4L205.7,35.9L207.7,33.0L209.7,36.2L211.8,39.6L213.8,41.1L215.8,42.9L217.8,43.7L219.8,40.1L221.8,43.7L223.9,40.7L225.9,40.6L227.9,44.0L229.9,42.5L231.9,43.5L233.9,37.9L236.0,38.9L238.0,37.3L240.0,35.7";
const GHOST_GRID = [12, 31, 50, 69, 88];

/* The preview variant's picture of a chart, blurred: axis labels, gridlines,
 * the line and its fill, all out of focus, so it reads as a preview and no
 * value can be read off it. It takes the theme's neutral tone, never the
 * up or down hue a real chart's line carries. */
function GhostChart() {
  // Two ghosts can share a page, so each fill gradient needs its own id.
  const fill = useId();
  return (
    <div className="ui-empty-ghost ui-empty-ghost-chart" aria-hidden="true">
      <div className="ui-empty-ghost-snapshot">
        <div className="ui-empty-ghost-yaxis">
          {GHOST_GRID.map((y) => <span key={y} style={{ top: `${y}%` }} />)}
        </div>
        <svg viewBox="0 0 240 100" preserveAspectRatio="none">
          <defs>
            <linearGradient id={fill} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stopColor="currentColor" stopOpacity="0.28" />
              <stop offset="1" stopColor="currentColor" stopOpacity="0" />
            </linearGradient>
          </defs>
          {GHOST_GRID.map((y) => (
            <line key={y} className="ui-empty-ghost-grid" x1="0" x2="240" y1={y} y2={y} />
          ))}
          <path fill={`url(#${fill})`} d={`${GHOST_LINE}L240,100L0,100Z`} />
          <path className="ui-empty-ghost-line" d={GHOST_LINE} />
        </svg>
        <div className="ui-empty-ghost-xaxis">
          {[0, 1, 2, 3, 4, 5, 6].map((tick) => <span key={tick} />)}
        </div>
      </div>
    </div>
  );
}

/* Four table rows: a stronger row head, then cells of uneven width so they
 * read as absent data rather than as stripes. */
function GhostRows() {
  return (
    <div className="ui-empty-ghost ui-empty-ghost-rows" aria-hidden="true">
      {[0, 1, 2, 3].map((row) => (
        <div key={row} className="ui-empty-ghost-row">
          <span /><span /><span /><span /><span />
        </div>
      ))}
    </div>
  );
}

/* Quiet radar motif for empty states: three rings, a sweep, one blip. */
export function EmptyState({
  title,
  variant = "page",
  art = "chart",
  children,
  actions,
}: {
  title: React.ReactNode;
  /** `page` owns a screen's whole content column — the motif, centred, in its
   *  dashed frame. `inline` is for an empty INSIDE a container that is still
   *  furnished (a register body under its column head, the 260px company
   *  selector): same voice, no furniture. `preview` is for a container whose
   *  content has a strong silhouette (a chart, a table) that data has not
   *  filled yet: a ghost of that silhouette holds the content's room, so the
   *  reader sees what belongs there and the layout stands still when the data
   *  arrives. See EmptyState.css. */
  variant?: EmptyStateVariant;
  /** The preview variant's silhouette: a line chart, or table rows. */
  art?: EmptyStateArt;
  children?: React.ReactNode;
  /** The ways out, a row of their own under the body (page and preview): a
   *  button set in a sentence's line crowds it. The inline variant has none,
   *  its way out is a `link` inside the sentence. */
  actions?: React.ReactNode;
}) {
  if (variant === "inline") {
    return (
      <div className="ui-empty-inline">
        <p className="ui-empty-inline-title">{title}</p>
        {children && <p className="ui-empty-inline-body">{children}</p>}
      </div>
    );
  }
  if (variant === "preview") {
    return (
      <div className="ui-empty-preview" data-art={art}>
        {art === "rows" ? <GhostRows /> : <GhostChart />}
        <div className="ui-empty-preview-copy">
          <p className="ui-empty-inline-title">{title}</p>
          {children && <p className="ui-empty-inline-body">{children}</p>}
          {actions && <div className="ui-empty-preview-actions">{actions}</div>}
        </div>
      </div>
    );
  }
  return (
    <div className="empty">
      <div className="empty-art" aria-hidden="true">
        <span className="ring" />
        <span className="ring" />
        <span className="ring" />
        <span className="sweep" />
        <span className="blip" />
      </div>
      <div className="big">{title}</div>
      {children && <div className="empty-body">{children}</div>}
      {actions && <div className="empty-actions">{actions}</div>}
    </div>
  );
}
