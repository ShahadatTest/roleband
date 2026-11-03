import { number as copyNumber } from "../../copy/format";
import { RefObject } from "react";
import { EmptyState, Icon, Switch } from "../../ui";
import { Button } from "../../ui/Button";
import { SearchField } from "../../ui/SearchField";
import type { RegisterFilterKey } from "./CompaniesData";
import { useCompanies, useCompaniesQuery, useCompaniesSync } from "./CompaniesData";
import {
  companiesRegisterChromeAScanIsAlreadyRunning,
  companiesRegisterChromeASearchShowsPlannedCompanies,
  companiesRegisterChromeClearTheSearch,
  companiesRegisterChromeCompaniesFailedTheLastScan,
  companiesRegisterChromeCompaniesNeedingAttention,
  companiesRegisterChromeCouldnTStartThatRescan,
  companiesRegisterChromeCuratedListOnly,
  companiesRegisterChromeFindACompanyAliasOr,
  companiesRegisterChromeFollowAll,
  companiesRegisterChromeFollowedCompaniesAreBlocked,
  companiesRegisterChromeFollowedCompaniesAreHiddenFrom,
  companiesRegisterChromeFollowedCompaniesAreNotScanned,
  companiesRegisterChromeFollowedCompaniesWaitForYour,
  companiesRegisterChromeFollowingOnly,
  companiesRegisterChromeMore,
  companiesRegisterChromeRolebandDoesnTScanThem,
  companiesRegisterChromeRegisterEmpty,
  companiesRegisterChromeToolbarStats,
  companiesRegisterChromeRescan,
  companiesRegisterChromeRescanningCompanies,
  companiesRegisterChromeReview,
  companiesRegisterChromeSearchCompanies,
  companiesRegisterChromeShowAllCompanies,
  companiesRegisterChromeShowPlanned,
  companiesRegisterChromeClearSearchToSee,
  companiesRegisterChromeShowAllToSee,
  companiesRegisterChromeShowPlannedButton,
  companiesRegisterChromeShowPlannedToSee,
} from "../../copy/gen/companies";
import { Msg } from "../../ui/Msg";

/* What frames the register: the warnings above it, the
 * toolbar that filters it, and what it says when the filters leave it empty. */

/** The roster's actionable warnings, above the register where they are read
 *  first. */
export function AttentionStrip() {
  const { alerts, failedSources, awaitingConsent, reviewConsent } = useCompanies();
  const { syncRunning, syncCompanies } = useCompaniesSync();
  if (alerts.length === 0 && failedSources.length === 0 && awaitingConsent.length === 0) return null;

  const names = (list: string[]) =>
    list.length > 4 ? companiesRegisterChromeMore({ names: list.slice(0, 4).join(", "), more: list.length - 4 }) : list.join(", ");

  const copy: Record<string, (n: number) => string> = {
    blocked: (count) => companiesRegisterChromeFollowedCompaniesAreBlocked({ count }),
    paused: (count) => companiesRegisterChromeFollowedCompaniesAreNotScanned({ count }),
    hidden: (count) => companiesRegisterChromeFollowedCompaniesAreHiddenFrom({ count }),
  };

  return (
    <section className="ledger-attention" aria-label={companiesRegisterChromeCompaniesNeedingAttention()}>
      {awaitingConsent.length > 0 && (
        <p className="ledger-attention-row">
          <Icon name="alert" size={16} />
          <b>
            {companiesRegisterChromeFollowedCompaniesWaitForYour({ count: awaitingConsent.length })}
          </b>
          <span>{companiesRegisterChromeRolebandDoesnTScanThem({ count: awaitingConsent.length })}</span>
          {awaitingConsent.map((company) => (
            <Button
              key={company.slug}
              size="sm"
              className="ui-btn-strong ledger-attention-act"
              onClick={() => reviewConsent(company)}
            >
              <Msg of={companiesRegisterChromeReview} elems={{ display: company.display }} />
            </Button>
          ))}
        </p>
      )}
      {failedSources.length > 0 && (
        <p className="ledger-attention-row">
          <Icon name="alert" size={16} />
          <b>
            {companiesRegisterChromeCompaniesFailedTheLastScan({ count: failedSources.length })}
          </b>
          <span>{names(failedSources.map((source) => source.display))}</span>
          <Button
            size="sm"
            className="ui-btn-strong ledger-attention-act"
            disabled={syncRunning}
            title={syncRunning ? companiesRegisterChromeAScanIsAlreadyRunning() : undefined}
            onClick={() =>
              syncCompanies(failedSources.map((source) => source.slug), {
                confirm: companiesRegisterChromeRescanningCompanies({ count: failedSources.length }),
                failure: companiesRegisterChromeCouldnTStartThatRescan(),
              })
            }
          >
            <Msg of={companiesRegisterChromeRescan} elems={{ count: failedSources.length }} />
          </Button>
        </p>
      )}
      {alerts.map((alert) => (
        <p className="ledger-attention-row" key={alert.kind}>
          <Icon name="alert" size={16} />
          <b>{copy[alert.kind](alert.companies.length)}</b>
          <span>{names(alert.companies)}</span>
        </p>
      ))}
    </section>
  );
}

export function LedgerToolbar({ toolbarRef }: { toolbarRef: RefObject<HTMLDivElement | null> }) {
  const { query, setQuery } = useCompaniesQuery();
  const {
    searching,
    trackedOnly,
    setTrackedOnly,
    showPlanned,
    setShowPlanned,
    trackedTotal,
    catalogTotal,
    trackedOpenRoles,
    trackedLive,
    trackedReady,
    listAction,
    requestListAction,
  } = useCompanies();

  return (
    <div className="ledger-toolbar" ref={toolbarRef}>
      <SearchField
        className="ledger-search"
        label={companiesRegisterChromeSearchCompanies()}
        placeholder={companiesRegisterChromeFindACompanyAliasOr()}
        value={query}
        onChange={setQuery}
      />

      <span className="ledger-stats tn" data-selection="chrome">
        <Msg
          of={companiesRegisterChromeToolbarStats}
          elems={{
            followed: <b>{trackedTotal}</b>,
            total: catalogTotal,
            sep: <i>·</i>,
            openRoles: <b>{trackedOpenRoles === null ? "—" : copyNumber(trackedOpenRoles)}</b>,
            live: <b>{trackedLive}</b>,
            ready: <b>{trackedReady}</b>,
          }}
        />
      </span>

      <span className="ledger-toolbar-end">
        <Switch checked={trackedOnly} onChange={setTrackedOnly}>
          <span>{companiesRegisterChromeFollowingOnly()}</span>
        </Switch>
        <Switch
          checked={showPlanned || searching}
          disabled={searching}
          onChange={setShowPlanned}
        >
          <span title={searching ? companiesRegisterChromeASearchShowsPlannedCompanies() : undefined}>
            {companiesRegisterChromeShowPlanned()}
          </span>
        </Switch>
        {/* Beside the count it acts on: every company listed here, never the
            set of other companies, which is offered at the end of the list. */}
        {listAction === "follow-all" && (
          <Button className="ui-btn-strong" onClick={requestListAction}>
            {companiesRegisterChromeFollowAll()}
          </Button>
        )}
        {listAction === "curated-only" && (
          <Button className="ui-btn-strong" onClick={requestListAction}>
            {companiesRegisterChromeCuratedListOnly()}
          </Button>
        )}
      </span>
    </div>
  );
}

/* The register's empty state names the filters that are actually holding rows
 * back, and offers each of them back.
 *
 * The list ANDs three filters together, so one sentence picked by
 * `query ? … : trackedOnly ? …` would answer "No companies match “stripe”."
 * about a catalog company hidden by Tracked only, and the reasonable next move
 * from that sentence, Add by link, duplicates it. `registerEmpty` measures the
 * blame by re-running the list's
 * own predicate with one filter released at a time, so the copy can state what
 * is behind each one rather than guess which is responsible.
 *
 * The actions are `link` buttons because they are verbs in a sentence, and they
 * release the filter that caused this rather than pointing somewhere else: Add
 * by URL is a real answer to "no such company", but it sits in the toolbar a
 * few pixels above and repeating it here would drown the one action that is
 * only available here.
 */
/** Which filters hold the rows back, as the empty title says it. */
function blamedKey(search: boolean, tracked: boolean, planned: boolean): string {
  if (search) return tracked ? "search-following" : "search";
  if (tracked) return planned ? "following-planned" : "following";
  return planned ? "planned" : "none";
}

export function RegisterEmpty() {
  const { registerEmpty, query, setQuery, setTrackedOnly, setShowPlanned, catalogTotal } =
    useCompanies();
  const reasons = registerEmpty ?? [];
  const blamed = (key: RegisterFilterKey) => reasons.find((reason) => reason.key === key);
  const search = blamed("query");
  const tracked = blamed("tracked");
  const planned = blamed("planned");
  const needle = query.trim();

  // Every branch below is reachable; the last is the one no filter explains,
  // where widening cannot help because the catalog came back empty.
  const title = companiesRegisterChromeRegisterEmpty({ blamed: blamedKey(!!search, !!tracked, !!planned), search: needle });

  return (
    <EmptyState variant="inline" title={title}>
      {tracked && (
        <>
          {/* Under a search every released row is by definition untracked — a
              tracked match would have kept the list from being empty. */}
          <Msg
            of={companiesRegisterChromeShowAllToSee}
            args={{ released: tracked.released, search: search ? "query" : "none" }}
            elems={{
              showAll: (
                <Button variant="link" onClick={() => setTrackedOnly(false)}>
                  {companiesRegisterChromeShowAllCompanies()}
                </Button>
              ),
            }}
          />{" "}
        </>
      )}
      {planned && (
        <>
          <Msg
            of={companiesRegisterChromeShowPlannedToSee}
            elems={{
              showPlanned: (
                <Button variant="link" onClick={() => setShowPlanned(true)}>
                  {companiesRegisterChromeShowPlannedButton()}
                </Button>
              ),
              released: planned.released,
            }}
          />{" "}
        </>
      )}
      {search && (
        <Msg
          of={companiesRegisterChromeClearSearchToSee}
          elems={{
            clearSearch: (
              <Button variant="link" onClick={() => setQuery("")}>
                {companiesRegisterChromeClearTheSearch()}
              </Button>
            ),
            catalogTotal: catalogTotal,
          }}
        />
      )}
    </EmptyState>
  );
}
