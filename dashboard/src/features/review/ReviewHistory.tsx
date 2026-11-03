import { EmptyState } from "../../ui/EmptyState";
import { ResourceLoadState } from "../../ui/ResourceLoadState";
import { SearchField } from "../../ui/SearchField";
import { type ReactNode, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, type DecidedReviewItem } from "../../api";
import { companyName, fmtDate } from "../../format";
import { useAsyncResource } from "../../hooks/useAsyncResource";
import { Badge, Icon, Segmented } from "../../ui";
import { ComparisonLedger } from "./ComparisonLedger";
import { DecisionBar } from "./DecisionConsole";
import { DescriptionComparison } from "./DescriptionComparison";
import { DECISION_COPY, DecidedList, RelationshipDecision, decisionOf, proposalKey, similarityText } from "./decision";
import {
  duplicatesReviewHistoryAllDecisions,
  duplicatesReviewHistoryDecided,
  duplicatesReviewHistoryDecided2,
  duplicatesReviewHistoryEveryJudgmentReadyToRevisit,
  duplicatesReviewHistoryFilterDecisions,
  duplicatesReviewHistoryLoadFailed,
  duplicatesReviewHistoryLoading,
  duplicatesReviewHistoryNoMatchingDecisions,
  duplicatesProposedAs,
  duplicatesReviewHistoryOf,
  duplicatesReviewHistoryReviewed,
  duplicatesReviewHistoryRevised,
  duplicatesReviewHistorySearchDecisions,
  duplicatesReviewHistorySearchTitleOrRequisitionId,
  duplicatesReviewHistorySystemScore,
  duplicatesReviewHistoryTryAnotherTitleRequisitionId,
} from "../../copy/gen/duplicates";
import { Msg } from "../../ui/Msg";

/* The decision archive: every past judgment, searchable and filterable, each
 * expandable into the same ledger + decision surfaces the queue uses. The
 * decision label is a Badge (tone carries the verdict): accent = same opening,
 * info = twin, neutral = separate.
 *
 * The list is the routes' summary form: each posting a list row, without its
 * description or stated pay. An expanded row reads its two postings whole
 * (`api.job`, as Compare does) for the ledger and the description comparison. */

const DECISION_FILTERS = ["all", "duplicate", "twin", "different"] as const satisfies readonly ("all" | RelationshipDecision)[];
type DecisionFilter = (typeof DECISION_FILTERS)[number];

const DECISION_TONE = {
  duplicate: "accent",
  twin: "info",
  different: "neutral",
} as const;

export function ReviewHistory({
  history,
  error,
  busy,
  onChange,
  onRetry,
}: {
  history: DecidedList | null;
  error: string | null;
  onRetry: () => void;
  busy: boolean;
  onChange: (item: DecidedReviewItem, decision: RelationshipDecision) => void;
}) {
  // Filter and search are the address too (`?decision=`, `?q=`), so a reload
  // keeps the reader's place in the archive. The component's own
  // state is the source, seeded from the address, and EVERY change writes both
  // keys. The router hands a write the params of its last render, and its
  // navigation is a transition, so reading the address back would let a
  // filter click followed at once by typing write the search over an address
  // that does not have the filter yet, and lose the filter.
  const [params, setParams] = useSearchParams();
  const [filter, setFilterState] = useState<DecisionFilter>(() => {
    const read = params.get("decision");
    return DECISION_FILTERS.find((option) => option === read) ?? "all";
  });
  const [query, setQueryState] = useState(() => params.get("q") ?? "");
  // What the address must say, updated in the handler itself: two changes
  // before a re-render (a click, then a key) each see the other's value.
  const latest = useRef({ filter, query });
  const writeAddress = () =>
    setParams(
      (prev) => {
        const url = new URLSearchParams(prev);
        const { filter: nextFilter, query: nextQuery } = latest.current;
        if (nextFilter === "all") url.delete("decision");
        else url.set("decision", nextFilter);
        if (nextQuery.trim()) url.set("q", nextQuery);
        else url.delete("q");
        return url;
      },
      { replace: true },
    );
  const setFilter = (next: DecisionFilter) => {
    latest.current = { ...latest.current, filter: next };
    setFilterState(next);
    writeAddress();
  };
  const setQuery = (next: string) => {
    latest.current = { ...latest.current, query: next };
    setQueryState(next);
    writeAddress();
  };
  const [expanded, setExpanded] = useState<string | null>(null);

  const visible = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return (history?.items ?? []).filter((item) => {
      if (filter !== "all" && decisionOf(item) !== filter) return false;
      if (!normalized) return true;
      return `${item.prior.title} ${item.job.title} ${item.prior.req_id} ${item.job.req_id} ${item.prior.company} ${companyName(item.prior.company)}`
        .toLowerCase()
        .includes(normalized);
    });
  }, [history, filter, query]);

  if (error) return <ResourceLoadState error={new Error(error)} failed={duplicatesReviewHistoryLoadFailed()} onRetry={onRetry} />;

  return (
    <section className="review-history" aria-label={duplicatesReviewHistoryDecided2()}>
      <header className="review-history-head">
        <div><span className="review-case-index">{duplicatesReviewHistoryDecided()}</span><h2>{duplicatesReviewHistoryEveryJudgmentReadyToRevisit()}</h2></div>
        <SearchField
          className="review-history-search"
          label={duplicatesReviewHistorySearchDecisions()}
          placeholder={duplicatesReviewHistorySearchTitleOrRequisitionId()}
          value={query}
          onChange={setQuery}
        />
      </header>
      <div className="review-history-tools">
        <Segmented
          label={duplicatesReviewHistoryFilterDecisions()}
          value={filter}
          onChange={setFilter}
          options={DECISION_FILTERS.map((value) => ({
            value,
            label: value === "all" ? duplicatesReviewHistoryAllDecisions() : DECISION_COPY[value].label,
          }))}
        />
        <span><Msg of={duplicatesReviewHistoryOf} elems={{ length: visible.length, value: history?.total ?? 0 }} /></span>
      </div>
      {!history ? (
        <ResourceLoadState error={null} loading={duplicatesReviewHistoryLoading()} />
      ) : visible.length === 0 ? (
        <EmptyState title={duplicatesReviewHistoryNoMatchingDecisions()}>{duplicatesReviewHistoryTryAnotherTitleRequisitionId()}</EmptyState>
      ) : (
        <ol className="review-history-list">
          {visible.map((item) => {
            const key = proposalKey(item);
            const isOpen = expanded === key;
            const decision = decisionOf(item);
            const score = similarityText(item.link.score);
            const revisions = item.link.decision_changes ?? 0;
            return (
              <li key={key} className={isOpen ? "is-open" : ""}>
                <button className="review-history-summary" type="button" aria-expanded={isOpen} onClick={() => setExpanded(isOpen ? null : key)}>
                  <Badge tone={DECISION_TONE[decision]} className="review-history-decision">
                    {DECISION_COPY[decision].short}
                  </Badge>
                  <span className="review-history-titles"><strong>{item.prior.title}</strong><small>{item.prior.req_id} · {item.job.req_id}</small></span>
                  <span className="review-history-connector" aria-hidden="true">
                    <Icon name="arrowLeftRight" size={12} />
                  </span>
                  <span className="review-history-titles"><strong>{item.job.title}</strong><small>{companyName(item.prior.company)} · {fmtDate(item.link.reviewed_at)}</small></span>
                  <span className="review-history-score">
                    {score !== null && <>{score}<small>{duplicatesReviewHistorySystemScore()}</small></>}
                  </span>
                  <span className="review-history-chevron" aria-hidden="true">
                    <Icon name="chevronDown" size={12} />
                  </span>
                </button>
                {isOpen && (
                  <div className="review-history-detail">
                    <div className="review-history-evidence">
                      <span>{duplicatesProposedAs({ kind: item.link.proposal_kind })}</span>
                      <span>{duplicatesReviewHistoryReviewed()} <strong>{fmtDate(item.link.reviewed_at)}</strong></span>
                      {revisions > 0 && <span>{duplicatesReviewHistoryRevised({ count: revisions })}</span>}
                    </div>
                    <DecidedPair
                      item={item}
                      decisionBar={<DecisionBar busy={busy} current={decision} onDecide={(next) => onChange(item, next)} />}
                    />
                  </div>
                )}
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}

/* An expanded row: its two postings read whole, the ledger and the description
 * comparison over them, and the decision bar between, which needs only the
 * row and so is there while the postings load. */
function DecidedPair({ item, decisionBar }: { item: DecidedReviewItem; decisionBar: ReactNode }) {
  const pair = useAsyncResource(
    (signal) => Promise.all([api.job(item.prior.id, signal), api.job(item.job.id, signal)]),
    [item.prior.id, item.job.id],
  );
  if (!pair.data) {
    return (
      <>
        <ResourceLoadState error={pair.error} onRetry={pair.retry} />
        {decisionBar}
      </>
    );
  }
  const [prior, job] = pair.data;
  return (
    <>
      <ComparisonLedger prior={prior} job={job} />
      {decisionBar}
      <DescriptionComparison prior={prior} job={job} />
    </>
  );
}
