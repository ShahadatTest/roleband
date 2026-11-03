import { forwardRef, useEffect, useState, type Ref } from "react";
import { useReferenceVersion } from "../../context/SyncState";
import { Badge } from "../../ui/Badge";
import { Button } from "../../ui/Button";
import { Icon } from "../../ui/Icon";
import { api, LineageDetail, LineageMember } from "../../api";
import { fmtDate, relDays } from "../../format";
import { postingPlaces } from "../../patterns/jobs/location";
import { statusName } from "../../copy/vocab";
import { Content } from "../../ui/Content";
import { LineageDiff } from "./LineageDiff";
import {
  roleLineageStackBadge,
  roleLineageStackChangesFromThePreviousPosting,
  roleLineageStackCompEst,
  roleLineageStackCouldNotLoadPostingHistory,
  roleLineageStackFirstSeen,
  roleLineageStackFirstSeen2,
  roleLineageStackLastSeen,
  roleLineageStackLocations,
  roleLineageStackNextPosting,
  roleLineageStackPosting,
  roleLineageStackPostingHistory,
  roleLineageStackPostings,
  roleLineageStackPostingsOfThisRole,
  roleLineageStackPreviousPosting,
  roleLineageStackReq,
  roleLineageStackRole,
} from "../../copy/gen/role";
import { Msg } from "../../ui/Msg";
import { usePayCoverage } from "../../payCoverage";
import { payShown } from "../../payShown";
import { Abbr } from "../../ui/Abbr";
import { sharedEstTcFull } from "../../copy/gen/shared";

const ROLES = ["original", "repost", "duplicate"];

/** How one member reads: what it is, when the server names a part this build
 *  has words for (left out otherwise), and its place in the stack. A member
 *  with no place counts by its position, since the stack is sent in posting order. */
function memberReading(mem: LineageMember, index: number): { choice: "yes" | "no"; role: string; seq: number } {
  const role = mem.role !== null && ROLES.includes(mem.role) ? mem.role : null;
  return {
    choice: role ? "yes" : "no",
    role: role ? roleLineageStackRole({ role }) : "",
    seq: mem.seq ?? index + 1,
  };
}

/* The "stack deck": a role that was posted more than once, paged newest-first.
   Each step shows that posting as-of when it ran, plus what changed vs the prior
   one. Honest by construction — the user sees distinct req ids and date ranges,
   not a single merged row. Renders nothing for a standalone job. The ref is
   the stack's own element, so this cover's History can scroll to it. */
export const LineageStack = forwardRef<HTMLElement, { jobId: number }>(function LineageStack({ jobId }, ref) {
  const [detail, setDetail] = useState<LineageDetail | null>(null);
  const [idx, setIdx] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const cover = usePayCoverage();

  // A source switch re-reads the members' pay in place, keeping the
  // posting selected; only a new job starts over, on the newest.
  const version = useReferenceVersion();
  useEffect(() => {
    setDetail(null);
    setError(null);
    setIdx(-1);
  }, [jobId]);
  useEffect(() => {
    let live = true;
    api
      .lineage(jobId)
      .then((d) => {
        if (!live) return;
        setDetail(d);
        setIdx((i) => (i >= 0 && i < d.members.length ? i : Math.max(0, d.members.length - 1)));
      })
      .catch((e) => live && setError(String(e)));
    return () => {
      live = false;
    };
  }, [jobId, version]);

  if (error) return <div ref={ref as Ref<HTMLDivElement>} className="lineage-stack error">{roleLineageStackCouldNotLoadPostingHistory()}</div>;
  // A posting that stands alone answers `lineage_id: null` and no members.
  if (!detail || detail.lineage_id === null || detail.size <= 1 || detail.members.length === 0) return null;

  const members = detail.members;
  const at = Math.min(idx, members.length - 1);
  const m = members[at];
  const job = m.job;

  const go = (next: number) => setIdx(Math.max(0, Math.min(members.length - 1, next)));
  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowLeft") {
      e.preventDefault();
      go(at - 1);
    } else if (e.key === "ArrowRight") {
      e.preventDefault();
      go(at + 1);
    }
  };

  return (
    <section
      ref={ref}
      className="lineage-stack"
      aria-label={roleLineageStackPostingHistory()}
      tabIndex={0}
      onKeyDown={onKeyDown}
    >
      <header className="lineage-stack-head">
        <span className="lineage-stack-title">
          <Msg of={roleLineageStackPostingsOfThisRole} elems={{ size: detail.size }} />
        </span>
        <span className="lineage-stack-sub"><Msg of={roleLineageStackFirstSeen} elems={{ relDays: relDays(relDaysFromFirst(detail.first_seen)) }} /></span>
      </header>

      <div className="lineage-stack-pager">
        <Button variant="icon" size="sm" onClick={() => go(at - 1)} disabled={at === 0} aria-label={roleLineageStackPreviousPosting()}>
          <Icon name="arrowLeft" size={14} />
        </Button>
        <ol className="lineage-rail" aria-label={roleLineageStackPostings()}>
          {members.map((mem, i) => (
            <li key={mem.job.id}>
              <button
                className={`lineage-dot role-${mem.role}`}
                onClick={() => go(i)}
                aria-label={roleLineageStackPosting(memberReading(mem, i))}
                aria-current={i === at}
                title={roleLineageStackBadge(memberReading(mem, i))}
              />
            </li>
          ))}
        </ol>
        <Button variant="icon" size="sm" onClick={() => go(at + 1)} disabled={at === members.length - 1} aria-label={roleLineageStackNextPosting()}>
          <Icon name="arrowRight" size={14} />
        </Button>
      </div>

      <div className="lineage-member">
        <div className="lineage-member-head">
          <Badge shape="tag" variant="outline">{roleLineageStackBadge(memberReading(m, at))}</Badge>
          <Badge shape="tag" variant="outline">{statusName(job.status) ?? <Content text={job.status} />}</Badge>
          <span className="lineage-req"><Msg of={roleLineageStackReq} elems={{ req_id: job.req_id }} /></span>
        </div>
        <h4 className="lineage-member-title">{job.title}</h4>
        <dl className="lineage-member-facts">
          <div>
            <dt>{roleLineageStackLocations()}</dt>
            <dd>{postingPlaces(job.locations).join(" · ") || "—"}</dd>
          </div>
          <div>
            <dt><Abbr short={roleLineageStackCompEst()} full={sharedEstTcFull()} /></dt>
            <dd>{payShown(job, cover).text}</dd>
          </div>
          <div>
            <dt>{roleLineageStackFirstSeen2()}</dt>
            <dd>{fmtDate(job.first_seen)}</dd>
          </div>
          <div>
            <dt>{roleLineageStackLastSeen({ choice: (job.status === "closed") ? "yes" : "no" })}</dt>
            <dd>{fmtDate(job.status === "closed" ? job.closed_at : job.last_seen)}</dd>
          </div>
        </dl>
        {m.diff_vs_prev && (
          <div className="lineage-member-diff">
            <span className="lineage-diff-heading">{roleLineageStackChangesFromThePreviousPosting()}</span>
            <LineageDiff diff={m.diff_vs_prev} />
          </div>
        )}
      </div>
    </section>
  );
});

/* Days since the lineage's earliest posting. */
function relDaysFromFirst(firstSeen: string): number {
  const ms = Date.now() - new Date(firstSeen).getTime();
  return Math.floor(ms / 86_400_000);
}
