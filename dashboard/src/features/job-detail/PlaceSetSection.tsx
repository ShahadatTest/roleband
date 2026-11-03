import { errorText } from "../../api/errorText";
import { useCallback, useEffect, useState } from "react";
import { PlaceSetDecision, PlaceSetDetail, api } from "../../api";
import type { components } from "../../api.gen";
import { fmtCompIn } from "../../money";
import { postingPlaces } from "../../patterns/jobs/location";
import { JobLinkRow } from "../../patterns/jobs/JobLinkRow";
import { Button } from "../../ui/Button";
import { useToast } from "../../ui/Toast";
import { fmtDate } from "../../format";
import {
  rolePlaceSetSectionASecondPostingAtThe,
  rolePlaceSetSectionAlsoListedIn,
  rolePlaceSetSectionAlsoListedIn2,
  rolePlaceSetSectionAlsoListedInAnd,
  rolePlaceSetSectionCouldNotLoadThisRole,
  rolePlaceSetSectionCouldNotRecordTheVerdict,
  rolePlaceSetSectionDifferentRoles,
  rolePlaceSetSectionListed,
  rolePlaceSetSectionListed2,
  rolePlaceSetSectionMarkedAsADifferentRole,
  rolePlaceSetSectionOtherPlaces,
  rolePlaceSetSectionPlaceNotStated,
  rolePlaceSetSectionSamePlace,
  rolePlaceSetSectionSameTitleAndTheSame,
  rolePlaceSetSectionTheEmployerFilesThemAll,
  rolePlaceSetSectionTimesHere,
  rolePlaceSetSectionUndo,
  rolePlaceSetSectionUndo2,
  rolePlaceSetSectionYouMarkedThisPostingAs,
  roleJobCompPanelHr,
  roleJobCompPanelMo,
  roleJobCompPanelYr,
  rolePlaceSetSectionStatesNoPay,
  rolePlaceSetSectionStatesPay,
} from "../../copy/gen/role";

/* One role, listed once per place.
 *
 * The employer posted the same title and the same description at several
 * places. RoleBand decided that by rule, so the pair never reaches Duplicates;
 * this section is where the decision shows and where a person can overrule it.
 * An automatic merge with no way to see it is a failure, so the
 * section names every other place, says why they are one role, and carries
 * the one control that splits this posting out. Undo is the toast's, and a
 * split posting keeps a quiet line with the same way back after the toast is
 * gone. */
export function PlaceSetSection({
  jobId,
  onOpen,
}: {
  jobId: number;
  onOpen: (id: number, companySlug?: string | null) => void;
}) {
  const [detail, setDetail] = useState<PlaceSetDetail | null>(null);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const { toast } = useToast();

  useEffect(() => {
    let active = true;
    setDetail(null);
    setFailed(false);
    api
      .placeSet(jobId)
      .then((value) => active && setDetail(value))
      .catch(() => active && setFailed(true));
    return () => {
      active = false;
    };
  }, [jobId]);

  const decide = useCallback(
    async (decision: PlaceSetDecision) => {
      if (busy) return;
      setBusy(true);
      try {
        const next = await api.reviewPlaceSet(jobId, decision);
        setDetail(next);
        if (decision === "different") {
          toast({
            key: "place-set-verdict",
            text: rolePlaceSetSectionMarkedAsADifferentRole(),
            action: { label: rolePlaceSetSectionUndo2(), onClick: () => void decide("pending") },
          });
        }
      } catch (e) {
        toast({
          key: "place-set-verdict",
          text: rolePlaceSetSectionCouldNotRecordTheVerdict({ message: errorText(e) }),
          tone: "error",
        });
      } finally {
        setBusy(false);
      }
    },
    [busy, jobId, toast],
  );

  if (failed) {
    return (
      <p className="place-set-note" role="status">
        {rolePlaceSetSectionCouldNotLoadThisRole()}
      </p>
    );
  }
  if (detail?.rejected) {
    return (
      <p className="place-set-note">
        {rolePlaceSetSectionYouMarkedThisPostingAs()}{" "}
        <Button variant="link" onClick={() => void decide("pending")} disabled={busy}>
          {rolePlaceSetSectionUndo()}
        </Button>
      </p>
    );
  }
  const found = detail?.place_set;
  if (!found) return null;
  const others = found.members.filter((member) => !member.is_this);
  if (others.length === 0) return null;
  // The role may be listed again at a place, this one included. The
  // places are counted from the set's places (one each), the postings here
  // from the members at this posting's place; when any posting is a
  // relisting, every row states its date, the one thing that differs.
  const otherPlaces = Math.max(0, found.places.length - 1);
  const here = others.filter((member) => member.same_place).length;
  const dated = found.members.some((member) => member.relation === "relisted");
  const self = found.members.find((member) => member.is_this);

  return (
    <section className="place-set" aria-label={rolePlaceSetSectionAlsoListedIn()}>
      <div className="section-title">{placeSetTitle(otherPlaces, here)}</div>
      <ul className="place-set-list">
        {others.map((member) => (
          <li key={member.job.id}>
            <JobLinkRow
              className="place-set-row"
              jobId={member.job.id}
              company={member.job.company}
              onOpen={onOpen}
            >
              {member.same_place
                ? rolePlaceSetSectionSamePlace()
                : postingPlaces(member.job.locations).join(" · ") || rolePlaceSetSectionPlaceNotStated()}
              {siblingDifferences(member, self, dated).map((said) => " " + said).join("")}
            </JobLinkRow>
          </li>
        ))}
      </ul>
      <p className="place-set-why">
        {rolePlaceSetSectionSameTitleAndTheSame()}
        {dated && (" " + rolePlaceSetSectionASecondPostingAtThe())}
        {found.employer_label && (" " + rolePlaceSetSectionTheEmployerFilesThemAll({ employer_label: String(found.employer_label) }))}
      </p>
      <Button variant="link" onClick={() => void decide("different")} disabled={busy}>
        {rolePlaceSetSectionDifferentRoles()}
      </Button>
    </section>
  );
}

type StatedPay = components["schemas"]["PlaceSetStatedPay"];

const PERIOD: Record<string, () => string> = { year: roleJobCompPanelYr, month: roleJobCompPanelMo, hour: roleJobCompPanelHr };

/** A stated band as the posting states it: "$180K–$220K / yr". */
export function statedRange(pay: StatedPay): string {
  const cur = pay.currency ?? "USD";
  const ends = [pay.low, pay.high].filter((v): v is number => v != null).map((v) => fmtCompIn(v, cur));
  const unit = pay.period ? PERIOD[pay.period]?.() : undefined;
  return [ends.join("–"), unit].filter(Boolean).join(" ");
}

const samePay = (a: StatedPay | null, b: StatedPay | null): boolean =>
  (a == null && b == null) ||
  (a != null && b != null && a.low === b.low && a.high === b.high && a.currency === b.currency && a.period === b.period);

/** What a sibling posting states differently from the one being viewed: its
 *  listing date when the day differs, and its stated pay when that differs. */
export function siblingDifferences(
  member: { job: { listed_since: string | null }; stated_pay: StatedPay | null },
  self: { job: { listed_since: string | null }; stated_pay: StatedPay | null } | undefined,
  dated: boolean,
): string[] {
  const out: string[] = [];
  const day = (iso: string | null) => (iso ? iso.slice(0, 10) : null);
  if (dated || (self && day(member.job.listed_since) !== day(self.job.listed_since))) {
    out.push(rolePlaceSetSectionListed({ listed_since: String(fmtDate(member.job.listed_since)) }));
  }
  if (self && !samePay(member.stated_pay, self.stated_pay)) {
    out.push(member.stated_pay
      ? rolePlaceSetSectionStatesPay({ range: statedRange(member.stated_pay) })
      : rolePlaceSetSectionStatesNoPay());
  }
  return out;
}

/** "Also listed in 2 other places", "Listed 3 times here", or both: how many
 *  places besides this one, and how many postings at this one. */
export function placeSetTitle(otherPlaces: number, here: number): string {
  const places = rolePlaceSetSectionOtherPlaces({ count: otherPlaces, otherPlaces: (otherPlaces === 1) ? "" : otherPlaces });
  const times = rolePlaceSetSectionTimesHere({ value: here + 1 });
  if (otherPlaces > 0 && here > 0) return rolePlaceSetSectionAlsoListedInAnd({ places: String(places), times: String(times) });
  if (here > 0) return rolePlaceSetSectionListed2({ times: String(times) });
  return rolePlaceSetSectionAlsoListedIn2({ places: String(places) });
}
