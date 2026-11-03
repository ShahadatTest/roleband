import { JobLinkRow } from "../../patterns/jobs/JobLinkRow";
import { companyName } from "../../format";
import { Badge } from "../../ui";
import type { BadgeTone } from "../../ui";
import "./digest-panel.css";
import {
  notificationsDigestPanelMoreRolesOpenedToday,
  notificationsDigestPanelUnrankedSetAnIntentStatement,
} from "../../copy/gen/notifications";
import { Msg } from "../../ui/Msg";

/* The digest's expanded body: the day's best-fit roles, each one a way in.
 *
 * Without this the digest is a dead end. It stands for a day of per-role
 * matches, each of which would be clickable as a row of its own; a count that
 * goes nowhere would trade noise for uselessness. The row stays one line until
 * opened; the roles are there when the user wants them.
 *
 * Entries are `JobLinkRow`, not buttons: a role HAS a URL, so the anchor buys
 * Enter, the status-bar destination and cmd/middle-click for free, and a plain
 * click still opens the detail as an overlay over the feed.
 */

export interface DigestEntry {
  job_id: number;
  company: string;
  title: string;
  fit: number | null;
  fit_band: string | null;
}

export interface Digest {
  day: string;
  count: number;
  companies: string[];
  ranked: boolean;
  top: DigestEntry[];
}

/** Parse `meta` into a digest, or null. Defensive: `meta` is untyped JSONB and
 *  a row may carry none of these keys. */
export function parseDigest(meta: Record<string, unknown> | null | undefined): Digest | null {
  if (!meta || typeof meta !== "object") return null;
  const { top, count } = meta as { top?: unknown; count?: unknown };
  if (!Array.isArray(top) || typeof count !== "number") return null;
  const entries: DigestEntry[] = [];
  for (const raw of top) {
    if (!raw || typeof raw !== "object") continue;
    const e = raw as Record<string, unknown>;
    if (typeof e.job_id !== "number" || typeof e.title !== "string") continue;
    entries.push({
      job_id: e.job_id,
      company: typeof e.company === "string" ? e.company : "",
      title: e.title,
      fit: typeof e.fit === "number" ? e.fit : null,
      fit_band: typeof e.fit_band === "string" ? e.fit_band : null,
    });
  }
  return {
    day: typeof meta.day === "string" ? meta.day : "",
    count,
    companies: Array.isArray(meta.companies) ? (meta.companies as string[]) : [],
    ranked: meta.ranked === true,
    top: entries,
  };
}

/** Tone by fit band, so the ladder reads at a glance rather than as five
 *  identical rows the reader has to compare by number. */
function bandTone(band: string | null): BadgeTone {
  switch (band) {
    case "Strong":
      return "success";
    case "Good":
      return "accent";
    case "Fair":
      return "info";
    default:
      return "neutral";
  }
}

export function DigestPanel({
  digest,
  onOpenJob,
}: {
  digest: Digest;
  onOpenJob: (jobId: number, company?: string | null) => void;
}) {
  const hidden = digest.count - digest.top.length;
  return (
    <div className="digest-panel">
      <p className="digest-panel-lead">
        {notificationsDigestPanelUnrankedSetAnIntentStatement({ choice: (digest.ranked) ? "yes" : "no" })}
      </p>
      <ul className="digest-list">
        {digest.top.map((entry) => (
          <li key={entry.job_id}>
            <JobLinkRow
              className="digest-entry"
              jobId={entry.job_id}
              company={entry.company || null}
              onOpen={onOpenJob}
            >
              <span className="digest-entry-copy">
                <span className="digest-entry-title">{entry.title}</span>
                <span className="digest-entry-company">{companyName(entry.company)}</span>
              </span>
              {entry.fit_band && (
                <Badge tone={bandTone(entry.fit_band)} size="sm">
                  {entry.fit_band}
                </Badge>
              )}
            </JobLinkRow>
          </li>
        ))}
      </ul>
      {hidden > 0 && (
        <p className="digest-panel-more">
          <Msg of={notificationsDigestPanelMoreRolesOpenedToday} args={{ count: hidden }} elems={{ hidden: hidden }} />
        </p>
      )}
    </div>
  );
}
