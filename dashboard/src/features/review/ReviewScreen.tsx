import { reasonsText } from "./reasons";
import { errorText } from "../../api/errorText";
import { EmptyState } from "../../ui/EmptyState";
import { ResourceLoadState } from "../../ui/ResourceLoadState";
import { TabBar } from "../../ui/TabBar";
import { useStuck } from "../../hooks/useStuck";
import { useToast } from "../../ui/Toast";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, DuplicateLLMAssessment, LineageReviewItem } from "../../api";
import { CompanyChip } from "../../patterns/companies/CompanyChip";
import { Button, InfoTip } from "../../ui";
import { ComparisonLedger } from "./ComparisonLedger";
import { QueueDecisionConsole } from "./DecisionConsole";
import { DescriptionComparison } from "./DescriptionComparison";
import { ReviewHistory } from "./ReviewHistory";
import { useSearchParam } from "../../routing/useSearchParam";
import {
  DecidedList,
  RelationshipDecision,
  ReviewPair,
  mergeReviewLists,
  proposalKey,
  similarityText,
} from "./decision";
import "./review.css";
import {
  duplicatesProposedAs,
  duplicatesReviewHistoryDecided,
  duplicatesReviewScreenAboutSystemSimilarity,
  duplicatesReviewScreenCandidatePair,
  duplicatesReviewScreenCouldNotRecordTheVerdict,
  duplicatesReviewScreenCouldNotUndo,
  duplicatesReviewScreenDuplicateReviewViews,
  duplicatesReviewScreenEveryClosePairOnYour,
  duplicatesReviewScreenEveryPairMatchedAutomaticallyHas,
  duplicatesReviewScreenLoadFailed,
  duplicatesReviewScreenLoading,
  duplicatesReviewScreenMarkedAs,
  duplicatesReviewScreenMatchedAutomatically,
  duplicatesReviewScreenNoneFound,
  duplicatesReviewScreenNoneFoundWhy,
  duplicatesReviewScreenNoneFoundYet,
  duplicatesReviewScreenNothingToCheck,
  duplicatesReviewScreenOpenDecided,
  duplicatesReviewScreenPairsLeftInTheQueue,
  duplicatesReviewScreenQueue,
  duplicatesReviewScreenQueueClear,
  duplicatesReviewScreenSystemSimilarity,
  duplicatesReviewScreenSystemSimilarity2,
  duplicatesReviewScreenUndo,
  duplicatesReviewScreenUndoneYourLaterDecisionOn,
} from "../../copy/gen/duplicates";
import { Msg } from "../../ui/Msg";

/* `queue` is the possible matches waiting for a verdict; `auto` the pairs the
   detector matched on its own and nobody has checked, weakest
   first, decided with the same keys; `history` what was decided. */
type ReviewView = "queue" | "auto" | "history";
const REVIEW_VIEWS = ["queue", "auto", "history"] as const;

/* One labeling surface for all close pairs. The reviewer decides the product
   artifact directly: duplicate, twin, or unrelated. Shell of the review
   feature — state, loading, the decide/analyze/withdraw writes and the
   keyboard map; the surfaces it composes live beside it (ComparisonLedger,
   DecisionConsole, ReviewHistory, DescriptionComparison).

   A queue verdict takes the pair off the screen, so it confirms with a toast
   that carries Undo (the `pending` verdict). A history
   reclassification stays in place with its controls, so it does not. */
export function ReviewScreen() {
  // The tab is the address (`?view=`), so a reload or a shared link opens the
  // list it names; the queue, the default, keeps a bare URL.
  const [view, setView] = useSearchParam<ReviewView>("view", { options: REVIEW_VIEWS, fallback: "queue" });
  const [items, setItems] = useState<LineageReviewItem[] | null>(null);
  const [total, setTotal] = useState(0);
  const [autoTotal, setAutoTotal] = useState(0);
  // Which list `load` reads: the view's, read through a ref so a verdict's
  // reload always refreshes the list on screen.
  const source = useRef<"queue" | "auto">(view === "auto" ? "auto" : "queue");
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<DecidedList | null>(null);
  const [historyError, setHistoryError] = useState<string | null>(null);
  /* The Decided badge: the last read's total, moved by each verdict and Undo
     made while the list is closed. A write re-reads the list only while it
     is on screen (`view`, through a ref so a write that lands after a tab
     switch sees the tab now shown); otherwise the list is marked stale and
     read when it next opens. */
  const [decidedTotal, setDecidedTotal] = useState<number | null>(null);
  const shownView = useRef(view);
  const historyStale = useRef(false);
  const [busy, setBusy] = useState(false);
  const [aiBusy, setAiBusy] = useState(false);
  /* The model's advice is kept with the proposal it was asked about, and shown
     only while that proposal is the one on screen: Undo, or an answer that
     lands after a verdict, can put another pair there. `shownPair` is the
     proposal on screen, for an answer that lands later. */
  const [advice, setAdvice] = useState<PairAdvice | null>(null);
  const shownPair = useRef<string | null>(null);
  const { toast } = useToast();

  /* Only the newest read of each list may commit its response.
   *
   * Every verdict reloads the queue, and the Decided list while it is open, so
   * several reads are in flight whenever the user works quickly. A slow
   * earlier response landing after a fast later one would write the OLDER
   * queue back over the newer, which puts a pair that has just been decided
   * back on screen, asking to be decided again. `busy` does not cover this:
   * it is a UI guard, it is stale inside a handler that
   * fires twice before React re-renders, and `withdraw` does not check it.
   *
   * Same shape as the `writeRef` epoch in CompaniesData and the request key in
   * useAsyncResource: a counter, captured per call, compared before commit.
   *
   * A write also retires the queue reads in flight when it starts. They were
   * issued before it, so they can still list the pair a verdict decides, and
   * the next key would decide that pair again. */
  const queueRead = useRef(0);
  const historyRead = useRef(0);

  const load = useCallback(async () => {
    const read = ++queueRead.current;
    setError(null);
    try {
      if (source.current === "auto") {
        // Duplicates and twins the detectors matched on their own, one list,
        // weakest first: the likeliest mistakes lead.
        const [autoDuplicates, autoTwins, possible, possibleTwins] = await Promise.all([
          api.lineageReview({ status: "pending", confidence: "auto", order: "weakest", limit: 50 }),
          api.twinReview({ status: "pending", confidence: "auto", limit: 50 }),
          api.lineageReview({ status: "pending", confidence: "suspected", limit: 1 }),
          api.twinReview({ status: "pending", confidence: "suspected", limit: 1 }),
        ]);
        if (queueRead.current !== read) return;
        const auto = mergeReviewLists(autoDuplicates, autoTwins);
        setItems([...auto.items].sort((a, b) => (a.link.score ?? 0) - (b.link.score ?? 0)));
        setAutoTotal(auto.total);
        setTotal(possible.total + possibleTwins.total);
      } else {
        const [duplicates, twins, autoDuplicates, autoTwins] = await Promise.all([
          api.lineageReview({ status: "pending", confidence: "suspected", limit: 50 }),
          api.twinReview({ status: "pending", confidence: "suspected", limit: 50 }),
          api.lineageReview({ status: "pending", confidence: "auto", limit: 1 }),
          api.twinReview({ status: "pending", confidence: "auto", limit: 1 }),
        ]);
        if (queueRead.current !== read) return;
        const r = mergeReviewLists(duplicates, twins);
        setItems(r.items);
        setTotal(r.total);
        setAutoTotal(autoDuplicates.total + autoTwins.total);
      }
    } catch (e) {
      // A superseded read's failure is not the user's problem either: reporting
      // it would put an error on a screen that has since loaded fine.
      if (queueRead.current !== read) return;
      setError(String(e));
    }
  }, []);

  const loadHistory = useCallback(async () => {
    const read = ++historyRead.current;
    setHistoryError(null);
    try {
      const [duplicates, twins] = await Promise.all([
        api.lineageReviewHistory(200),
        api.twinReviewHistory(200),
      ]);
      if (historyRead.current !== read) return;
      const decided: DecidedList = mergeReviewLists(duplicates, twins);
      setHistory(decided);
      setDecidedTotal(decided.total);
    } catch (e) {
      if (historyRead.current !== read) return;
      setHistoryError(String(e));
    }
  }, []);

  useEffect(() => {
    load();
    loadHistory();
  }, [load, loadHistory]);

  useEffect(() => {
    shownView.current = view;
    if (view !== "history" || !historyStale.current) return;
    historyStale.current = false;
    setHistory(null);
    loadHistory();
  }, [view, loadHistory]);

  /* After a write: the Decided list on screen is read again; a closed one is
     read when it opens, and its badge moves by `decided` meanwhile. */
  const afterWrite = useCallback(
    (decided: number) => {
      if (shownView.current === "history") {
        void loadHistory();
        return;
      }
      historyStale.current = true;
      if (decided !== 0) setDecidedTotal((t) => (t === null ? t : Math.max(0, t + decided)));
    },
    [loadHistory],
  );

  useEffect(() => {
    document.querySelector("main.review-main")?.scrollTo({ top: 0 });
  }, [view]);

  // Switching between the two lists reads the one now on screen.
  useEffect(() => {
    if (view === "history" || source.current === view) return;
    source.current = view;
    setItems(null);
    setAdvice(null);
    load();
  }, [view, load]);

  /* The way back from a queue verdict: the pair returns to the queue and the
     verdict's side effects are put back on the server, except a related
     decision the person made since, which the server keeps and names
     (`kept`). Saying so is the only sign the Undo was partial. */
  const withdraw = useCallback(
    async (item: ReviewPair) => {
      setBusy(true);
      queueRead.current += 1;
      // A pair whose Undo keeps a later decision on the same postings stays decided.
      let leftDecided = 0;
      try {
        const result = await (item.link.proposal_kind === "twin"
          ? api.reviewTwinLink(item.link.id, "pending")
          : api.reviewLineageLink(item.link.id, "pending"));
        if (result.kept.length > 0) {
          toast({ key: "review-verdict", text: duplicatesReviewScreenUndoneYourLaterDecisionOn() });
        } else {
          leftDecided = -1;
        }
      } catch (e) {
        toast({ key: "review-verdict", text: duplicatesReviewScreenCouldNotUndo({ message: errorText(e) }), tone: "error" });
      } finally {
        setBusy(false);
      }
      void load();
      afterWrite(leftDecided);
    },
    [afterWrite, load, toast],
  );

  /* The next verdict waits only for this one to land: the reads after it
     run behind their own guards, and `busy` never waits on them. */
  const decide = useCallback(
    async (item: ReviewPair, decision: RelationshipDecision, fromHistory = false) => {
      if (busy) return;
      setBusy(true);
      queueRead.current += 1;
      setAdvice(null);
      let decided = 0;
      if (!fromHistory) {
        setItems((cur) =>
          cur
            ? cur.filter(
                (i) => i.link.id !== item.link.id || i.link.proposal_kind !== item.link.proposal_kind,
              )
            : cur,
        );
        (source.current === "auto" ? setAutoTotal : setTotal)((t) => Math.max(0, t - 1));
      }
      try {
        await (
          item.link.proposal_kind === "twin"
            ? await api.reviewTwinLink(
                item.link.id,
                decision === "twin" ? "confirmed" : decision === "duplicate" ? "duplicate" : "rejected",
              )
            : await api.reviewLineageLink(
                item.link.id,
                decision === "duplicate" ? "confirmed" : decision === "twin" ? "twin" : "rejected",
              )
        );
        if (!fromHistory) {
          decided = 1;
          toast({
            key: "review-verdict",
            text: duplicatesReviewScreenMarkedAs({ decision }),
            action: { label: duplicatesReviewScreenUndo(), onClick: () => void withdraw(item) },
          });
        }
      } catch (e) {
        /* A write error is not a load error: the reload that restores truth
           would wipe a load-state error at once. It stays as an error toast,
           keyed so the next verdict on the subject replaces it. */
        toast({
          key: "review-verdict",
          text: duplicatesReviewScreenCouldNotRecordTheVerdict({ message: errorText(e) }),
          tone: "error",
        });
      } finally {
        setBusy(false);
      }
      void load();
      afterWrite(decided);
    },
    [afterWrite, busy, load, toast, withdraw],
  );

  const current = items && items.length > 0 ? items[0] : null;
  const currentPair = current ? proposalKey(current) : null;
  const shownAdvice = advice !== null && advice.pair === currentPair ? advice : null;

  useEffect(() => {
    shownPair.current = currentPair;
  }, [currentPair]);

  const analyze = useCallback(async () => {
    if (!current || aiBusy) return;
    const pair = proposalKey(current);
    setAiBusy(true);
    setAdvice(null);
    try {
      const assessment =
        current.link.proposal_kind === "twin"
          ? await api.analyzeTwinLink(current.link.id)
          : await api.analyzeLineageLink(current.link.id);
      if (shownPair.current === pair) setAdvice({ pair, assessment, error: null });
    } catch (e) {
      if (shownPair.current === pair) setAdvice({ pair, assessment: null, error: errorText(e) });
    } finally {
      setAiBusy(false);
    }
  }, [current, aiBusy]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!current || busy || aiBusy || view === "history") return;
      // A verdict key is a bare letter: with a modifier it is the browser's
      // (Cmd+D bookmarks the page), and while a dialog is open over the queue
      // (the `?` sheet) the keyboard is the dialog's. Either would record a
      // verdict on a pair the user was not deciding.
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (document.querySelector('[aria-modal="true"]')) return;
      const target = e.target as HTMLElement | null;
      if (target?.isContentEditable || target?.closest("input, textarea, select, button, a")) return;
      const k = e.key.toLowerCase();
      if (k === "d") decide(current, "duplicate");
      else if (k === "t") decide(current, "twin");
      else if (k === "n") decide(current, "different");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [current, busy, aiBusy, decide, view]);

  // The tab row is at rest like every tab row, and gains a surface only
  // while pinned, to cover the queue scrolling beneath it.
  const toolbarMarker = useRef<HTMLSpanElement>(null);
  const toolbarStuck = useStuck(toolbarMarker);

  /* No scan has found a pair: nothing waits in either list and nothing was
     ever decided, which is every fresh install. The screen then says what it
     is for instead of calling an empty queue clear. Until Decided has been
     read that is not known, so the empty state waits for it; a Decided that
     fails to load leaves the plain empty states. */
  const decidedKnown = decidedTotal !== null || historyError !== null;
  const noneFound = total === 0 && autoTotal === 0 && decidedTotal === 0;

  return (
    <div className="review">
      <span ref={toolbarMarker} className="review-toolbar-marker" aria-hidden="true" />
      <header className="review-toolbar" data-stuck={toolbarStuck || undefined}>
        <TabBar
          label={duplicatesReviewScreenDuplicateReviewViews()}
          idPrefix="review"
          value={view}
          onChange={setView}
          tabs={[
            { id: "queue", label: duplicatesReviewScreenQueue(), badge: total },
            { id: "auto", label: duplicatesReviewScreenMatchedAutomatically(), badge: autoTotal },
            { id: "history", label: duplicatesReviewHistoryDecided(), badge: decidedTotal ?? 0 },
          ]}
        />
      </header>

      {view === "history" ? (
        <ReviewHistory
          history={history}
          error={historyError}
          onRetry={loadHistory}
          busy={busy}
          onChange={(item, decision) => decide(item, decision, true)}
        />
      ) : error ? (
        <ResourceLoadState error={new Error(error)} failed={duplicatesReviewScreenLoadFailed()} onRetry={load} />
      ) : !items || (items.length === 0 && !decidedKnown) ? (
        <ResourceLoadState error={null} loading={duplicatesReviewScreenLoading()} />
      ) : items.length === 0 && noneFound ? (
        <EmptyState title={duplicatesReviewScreenNoneFound()}>
          <p>{duplicatesReviewScreenNoneFoundWhy()}</p>
          <p>{duplicatesReviewScreenNoneFoundYet()}</p>
        </EmptyState>
      ) : items.length === 0 ? (
        <EmptyState
          title={view === "auto" ? duplicatesReviewScreenNothingToCheck() : duplicatesReviewScreenQueueClear()}
          actions={<Button onClick={() => setView("history")}>{duplicatesReviewScreenOpenDecided()}</Button>}
        >
          {view === "auto" ? duplicatesReviewScreenEveryPairMatchedAutomaticallyHas() : duplicatesReviewScreenEveryClosePairOnYour()}
        </EmptyState>
      ) : (
        <ReviewWorkspace
          item={items[0]}
          total={view === "auto" ? autoTotal : total}
          auto={view === "auto"}
          busy={busy}
          aiBusy={aiBusy}
          aiError={shownAdvice?.error ?? null}
          assessment={shownAdvice?.assessment ?? null}
          onAnalyze={analyze}
          onDecide={(decision) => decide(items[0], decision)}
        />
      )}
    </div>
  );
}

type PairAdvice = {
  /** The proposal asked about (`proposalKey`). */
  pair: string;
  assessment: DuplicateLLMAssessment | null;
  error: string | null;
};

function ReviewWorkspace({
  item,
  total,
  auto,
  busy,
  aiBusy,
  aiError,
  assessment,
  onAnalyze,
  onDecide,
}: {
  item: LineageReviewItem;
  total: number;
  auto: boolean;
  busy: boolean;
  aiBusy: boolean;
  aiError: string | null;
  assessment: DuplicateLLMAssessment | null;
  onAnalyze: () => void;
  onDecide: (decision: RelationshipDecision) => void;
}) {
  return (
    <section className="review-workspace" aria-label={duplicatesReviewScreenCandidatePair()}>
      <header className="review-casebar">
        <div className="review-pair-identity">
          <CompanyChip slug={item.prior.company} />
          <span>
            <Msg of={duplicatesReviewScreenPairsLeftInTheQueue} args={{ count: total, choice: (auto) ? "yes" : "no" }} elems={{ total: total }} />
          </span>
        </div>
        <SystemSimilarity item={item} />
      </header>

      <ComparisonLedger prior={item.prior} job={item.job} />

      <QueueDecisionConsole
        busy={busy}
        aiBusy={aiBusy}
        aiError={aiError}
        assessment={assessment}
        onAnalyze={onAnalyze}
        onDecide={onDecide}
      />
      <DescriptionComparison prior={item.prior} job={item.job} />
    </section>
  );
}

function SystemSimilarity({ item }: { item: LineageReviewItem }) {
  const link = item.link;
  const score = similarityText(link.score);
  return (
    <div
      className="review-system-indicator"
      role="group"
      aria-label={score === null ? duplicatesReviewScreenSystemSimilarity() : duplicatesReviewScreenSystemSimilarity2({ score })}
    >
      <span>{duplicatesReviewScreenSystemSimilarity()}</span>
      {score !== null && <strong>{score}</strong>}
      <InfoTip label={duplicatesReviewScreenAboutSystemSimilarity()}>
        <span className="review-system-detail">
          <strong>{duplicatesProposedAs({ kind: link.proposal_kind })}</strong>
          {reasonsText(link.said).length > 0 && <span>{reasonsText(link.said).join(" · ")}</span>}
        </span>
      </InfoTip>
    </div>
  );
}
