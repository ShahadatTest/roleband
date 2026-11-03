import {
  jobsLevelNotMappedTitle,
  jobsLevelNotStatedTitle,
  jobsLevelUnconfirmed,
  jobsLevelUnconfirmedTitle,
  jobsMatchedVia,
  jobsSignDateMoved,
  jobsSignDateMovedInline,
  jobsSignLongOpen,
  jobsSignLongOpenInline,
  jobsSignRelisted,
  jobsSignRelistedInline,
  jobsStandingHedge,
  jobsStandingTitle,
  jobsViaFuzzy,
  jobsViaFuzzyInline,
  jobsViaKeyword,
  jobsViaKeywordInline,
} from "../../copy/gen/jobs";
import type { JobDetail } from "../../api";
import { BAND_LABEL, LOC_LABEL } from "../../format";
import { list } from "../../copy/format";
import { LEVEL_NOT_MAPPED, LEVEL_NOT_STATED } from "../../copy/vocabulary";
import { Badge, type BadgeTone } from "../../ui/Badge";

const MATCH_VIA_LABEL: Record<string, { label: () => string; inline: () => string }> = {
  keyword: { label: jobsViaKeyword, inline: jobsViaKeywordInline },
  fuzzy: { label: jobsViaFuzzy, inline: jobsViaFuzzyInline },
};

/** The bands that wear a hue of their own; every other band is neutral. */
const BAND_TONE: Partial<Record<string, BadgeTone>> = {
  staff: "accent",
  principal: "principal",
  director_plus: "director",
};

// The job row's read-only label vocabulary: what a posting IS (band, location)
// and why it surfaced (retrieval source). Controls that ACT on a job live in
// ./JobControls; these render nothing interactive, which is why the split is
// by that and not by screen.

export function BandBadge(
  { band, confidence, basis }: { band: string; confidence?: string; basis?: string | null },
) {
  // A posting that names no level is stored at Mid for sorting only:
  // showing "Mid-level" would claim a level it never stated. One
  // whose title names a level we cannot place keeps a guessed band
  // for sorting: showing it would claim a placement we have not made.
  const notStated = basis === "none";
  const notMapped = basis === "unmapped";
  const mark = notStated ? LEVEL_NOT_STATED() : notMapped ? LEVEL_NOT_MAPPED()
    : confidence === "unconfirmed" ? jobsLevelUnconfirmed() : null;
  return (
    <span style={{ display: "inline-flex", gap: 5 }}>
      {!notStated && !notMapped && (
        <Badge shape="tag" variant="tint" tone={BAND_TONE[band] ?? "neutral"}>{BAND_LABEL[band] ?? band}</Badge>
      )}
      {mark && (
        <Badge
          shape="tag"
          variant="tint"
          tone="warning"
          dashed
          title={notStated ? jobsLevelNotStatedTitle()
            : notMapped ? jobsLevelNotMappedTitle()
              : jobsLevelUnconfirmedTitle()}
        >
          {mark}
        </Badge>
      )}
    </span>
  );
}

export function LocBadge({ slug }: { slug: string }) {
  return <Badge shape="tag" variant="outline">{LOC_LABEL[slug] ?? slug}</Badge>;
}

// Subtle indicator of *why* a row matched on the Best-match path. Shows which
// retrieval sources hit (keyword / fuzzy) rather than the raw fusion score,
// which is tiny and unintuitive (and never a cosine: the vector reorders, it
// does not admit, so it earns no badge). "exact" is
// filtered here because identity is the CLASS chip's claim (`MatchClassBadge`),
// not a retrieval source. Renders nothing without a textual match.
export function MatchBadge({ matchedVia }: { matchedVia?: string[] | null }) {
  const sources = (matchedVia ?? []).filter((v) => v !== "exact");
  if (sources.length === 0) return null;
  const label = sources.map((v) => MATCH_VIA_LABEL[v]?.label() ?? v).join(" · ");
  const inline = list(sources.map((v) => MATCH_VIA_LABEL[v]?.inline() ?? v));
  return (
    <Badge shape="tag" variant="tint" tone="accent" title={jobsMatchedVia({ sources: inline })}>
      {label}
    </Badge>
  );
}

/** The standing-posting verdict, as Job detail and the Board both receive it.
 * One wording for both surfaces: a second copy is how
 *  two screens come to describe one posting differently. */
export type Reality = NonNullable<JobDetail["posting_reality"]>;

export const STANDING_TITLE = jobsStandingTitle;

export const STANDING_HEDGE = jobsStandingHedge;

/** Why a posting may be a standing one, one line per sign. Worded as what was
 *  observed, never as a judgement of the employer. The age figure lives in
 *  Details; a second copy here would show two. */
export function standingSigns(reality: Reality, { inline = false } = {}): string[] {
  return reality.met.map((code) => {
    if (code === "long_open") return inline ? jobsSignLongOpenInline() : jobsSignLongOpen();
    if (code === "relisted") {
      return inline ? jobsSignRelistedInline({ count: reality.listings }) : jobsSignRelisted({ count: reality.listings });
    }
    return inline ? jobsSignDateMovedInline() : jobsSignDateMoved();
  });
}

/** Shown only at `possible` (two of three signs). Fewer signs, a closed
 *  posting, or a row whose verdict was not sent say nothing. */
export function isStanding(reality: Reality | null | undefined): reality is Reality {
  return !!reality && reality.level === "possible";
}
