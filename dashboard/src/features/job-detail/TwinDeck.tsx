import { useEffect, useMemo, useState } from "react";
import { useReferenceVersion } from "../../context/SyncState";
import { TwinDetail, api } from "../../api";
import { postingPlaces } from "../../patterns/jobs/location";
import { Button } from "../../ui/Button";
import {
  roleTwinDeckCompareWithRelatedRoles,
  roleTwinDeckCouldNotLoadTwinPostings,
  roleTwinDeckHasRelatedRoles,
  roleTwinDeckLocationNotListed,
  roleTwinDeckRelatedRoles,
  roleTwinDeckReq,
  roleTwinDeckReq2,
  roleTwinDeckSeparateRolesWithCloselyRelated,
  roleTwinDeckViaARelatedGroupNot,
} from "../../copy/gen/role";
import { Msg } from "../../ui/Msg";
import { usePayCoverage } from "../../payCoverage";
import { payShown } from "../../payShown";

export function TwinDeck({
  jobId,
  onOpen,
  onCompare,
}: {
  jobId: number;
  onOpen: (id: number, companySlug?: string | null) => void;
  onCompare: (ids: number[]) => void;
}) {
  const [detail, setDetail] = useState<TwinDetail | null>(null);
  const cover = usePayCoverage();
  const [failed, setFailed] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [turning, setTurning] = useState(false);

  // A source switch re-reads the twins' pay in place; only a new
  // job starts the deck over.
  const version = useReferenceVersion();
  useEffect(() => {
    setDetail(null);
    setFailed(false);
    setExpanded(false);
  }, [jobId]);
  useEffect(() => {
    let active = true;
    api
      .twins(jobId)
      .then((value) => active && setDetail(value))
      // Silence here would be indistinguishable from "no twins"; the panel
      // says it could not look.
      .catch(() => active && setFailed(true));
    return () => {
      active = false;
    };
  }, [jobId, version]);

  const twins = useMemo(
    () => detail?.members.filter((member) => member.job.id !== jobId && member.direct) ?? [],
    [detail, jobId],
  );
  const group = useMemo(
    () => detail?.members.filter((member) => member.job.id !== jobId && !member.direct) ?? [],
    [detail, jobId],
  );
  if (failed) {
    return (
      <p className="twin-deck-error" role="status">
        {roleTwinDeckCouldNotLoadTwinPostings()}
      </p>
    );
  }
  if (twins.length === 0) return null;

  const open = (id: number, company: string) => {
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
      onOpen(id, company);
      return;
    }
    setTurning(true);
    window.setTimeout(() => onOpen(id, company), 140);
  };

  return (
    <section className={`twin-deck${turning ? " is-turning" : ""}`} aria-label={roleTwinDeckRelatedRoles()}>
      <button
        className="twin-deck-trigger"
        type="button"
        aria-expanded={expanded}
        onClick={() => setExpanded((value) => !value)}
      >
        <span className="twin-paper-mark" aria-hidden="true" />
        <span>
          <strong>{roleTwinDeckHasRelatedRoles({ count: twins.length, length: (twins.length === 1) ? "" : twins.length })}</strong>
          <small>{roleTwinDeckSeparateRolesWithCloselyRelated()}</small>
        </span>
        <span className="twin-deck-chevron" aria-hidden="true">{expanded ? "−" : "+"}</span>
      </button>

      {expanded && (
        <div className="twin-deck-sheet">
          <ol>
            {twins.map((member) => (
              <li key={member.job.id}>
                <button type="button" onClick={() => open(member.job.id, member.job.company)}>
                  <span className="twin-deck-title">{member.job.title}</span>
                  <span className="twin-deck-meta">
                    <Msg of={roleTwinDeckReq} elems={{ req_id: member.job.req_id, value: postingPlaces(member.job.locations).slice(0, 2).join(" · ") || roleTwinDeckLocationNotListed() }} />
                  </span>
                  <span className="twin-deck-meta">
                    {payShown(member.job, cover).text}
                  </span>
                </button>
              </li>
            ))}
          </ol>
          {group.length > 0 && (
            <div className="twin-group-members">
              <span>{roleTwinDeckViaARelatedGroupNot()}</span>
              {group.map((member) => (
                <Button
                  variant="link"
                  className="ui-btn-quiet"
                  key={member.job.id}
                  onClick={() => open(member.job.id, member.job.company)}
                >
                  <Msg of={roleTwinDeckReq2} elems={{ title: member.job.title, req_id: member.job.req_id }} />
                </Button>
              ))}
            </div>
          )}
          {/* Ghost, not primary: this renders INSIDE Job detail, whose primary
              is "View & apply", the one thing that page exists for. A second
              filled button on the same screen would make two primaries, and
              two primaries is none. */}
          <Button
            className="twin-compare-button"
            onClick={() => onCompare([jobId, ...twins.map((member) => member.job.id)])}
          >
            {roleTwinDeckCompareWithRelatedRoles()}
          </Button>
        </div>
      )}
    </section>
  );
}
