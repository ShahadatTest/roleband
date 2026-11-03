import { ReactNode } from "react";
import { Job } from "../../api";
import { WORKPLACE_LABEL, relDays } from "../../format";
import { BandBadge, LocBadge } from "../../patterns/jobs/JobBadges";
import { postingPlaces } from "../../patterns/jobs/location";
import { placeGroups } from "../../patterns/jobs/placeGroups";
import type { PayCover } from "../../payCoverage";
import { payShown } from "../../payShown";
import { type LedgerRow, rowDiffers } from "../../patterns/ledger";
import {
  compareAttributesEstComp,
  compareAttributesLevel,
  compareAttributesListedFor,
  compareAttributesLocations,
  compareAttributesRegions,
  compareAttributesReposts,
  compareAttributesStatus,
  compareAttributesWorkplace,
} from "../../copy/gen/compare";
import { statusName } from "../../copy/vocab";
import { Content } from "../../ui/Content";
import { sharedEstTcFull } from "../../copy/gen/shared";

/** What a cell reads beside its job: the plugin answering pay, so a company it
 *  has not read says "not covered". */
export interface AttrView {
  cover: PayCover | null;
}

/** A ledger row (patterns/ledger) that draws its own cell. Two roles
 *  "disagree" on a row when their diff keys differ, which is what tints it. */
export interface Attr extends LedgerRow<Job> {
  /** `view`: what the screen read beside the jobs (the controller's). */
  render: (j: Job, view?: AttrView) => ReactNode;
}

/* Comparison rows declared once and mapped across every job column, so values
 * line up by construction.
 *
 * The grid starts at Level, and Company and Title are NOT rows. The column
 * head above every cell carries the company chip and the title as a link, so
 * those rows would restate their own header and push the first real
 * difference down. A fact stated in the head is not a comparison row. */
export const ATTRIBUTES: Attr[] = [
  {
    key: "band",
    get label() { return compareAttributesLevel(); },
    render: (j) => <BandBadge band={j.level_band} confidence={j.level_confidence} basis={j.level_basis} />,
    diff: (j) => j.level_band,
  },
  {
    key: "comp",
    get label() { return compareAttributesEstComp(); },
    get fullLabel() { return sharedEstTcFull(); },
    render: (j, view) => payShown(j, view?.cover).text,
    // The figures, not their rounded text: two totals that both read "$400K"
    // still differ; a base never equals a total of the same amount.
    diff: (j) => `${j.comp_median ?? ""}|${j.comp_base_median ?? ""}`,
  },
  {
    key: "locations",
    get label() { return compareAttributesLocations(); },
    render: (j) => postingPlaces(j.locations).slice(0, 3).join(", ") || "—",
    diff: (j) => postingPlaces(j.locations).join("|"),
  },
  {
    key: "regions",
    get label() { return compareAttributesRegions(); },
    render: (j) => (placeGroups(j.location_groups).length ? placeGroups(j.location_groups).map((g) => <LocBadge key={g} slug={g} />) : "—"),
    diff: (j) => j.location_groups.join("|"),
  },
  {
    key: "workplace",
    get label() { return compareAttributesWorkplace(); },
    render: (j) => WORKPLACE_LABEL[j.workplace_type] ?? j.workplace_type,
    diff: (j) => j.workplace_type,
  },
  { key: "listed", get label() { return compareAttributesListedFor(); }, render: (j) => relDays(j.listed_days), diff: (j) => String(j.listed_days ?? "") },
  {
    key: "status",
    get label() { return compareAttributesStatus(); },
    render: (j) => <span className="cmp-status">{statusName(j.status) ?? <Content text={j.status} />}</span>,
    diff: (j) => j.status,
  },
  { key: "reposts", get label() { return compareAttributesReposts(); }, render: (j) => j.repost_count, diff: (j) => String(j.repost_count) },
];

/** True when the compared roles do not all agree on this attribute. */
export function attributeDiffers(attr: Attr, jobs: Job[]): boolean {
  return rowDiffers(attr, jobs);
}
