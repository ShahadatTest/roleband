import { useState } from "react";
import { ClusterDetail, ClusterSummary, InsightsScope, api } from "../../api";
import { companyName } from "../../format";
import { payPoint } from "../../payShown";
import { usePayCoverage } from "../../payCoverage";
import { listedFor } from "./ageCopy";
import { useAsyncResource } from "../../hooks/useAsyncResource";
import { Badge, FilterChip, InfoTip, ResourceLoadState } from "../../ui";
import { ClusterLandscapeChart } from "./charts/StatisticsCharts";
import { CompanyChip } from "../../patterns/companies/CompanyChip";
import { JobLinkRow } from "../../patterns/jobs/JobLinkRow";
import { InsightHero, n } from "./InsightHero";
import {
  insightsCommonCompanies,
  insightsCommonOpenRolesUnit,
  insightsClustersViewAboutRoleGroups,
  insightsClustersViewAndMoreCompanies,
  insightsClustersViewAreaEncodesActiveRoleVolume,
  insightsClustersViewClear,
  insightsClustersViewFromRoleDescriptions,
  insightsClustersViewGroupLandscape,
  insightsClustersViewGroupLoadFailed,
  insightsClustersViewGroupLoading,
  insightsClustersViewGroups,
  insightsClustersViewGroupsTile,
  insightsClustersViewGroupsAreBuiltFromRole,
  insightsClustersViewHowToReadTheCluster,
  insightsClustersViewLargest,
  insightsClustersViewLargestGroup,
  insightsClustersViewLoadFailed,
  insightsClustersViewLoading,
  insightsClustersViewMarketTerrain,
  insightsClustersViewRoleGroups,
  insightsClustersViewRoles,
  insightsClustersViewRolesGrouped,
  insightsClustersViewRolesInOneGroup,
  insightsClustersViewSemanticGroupsBuiltFromRole,
  insightsClustersViewWithAGroupedRole,
} from "../../copy/gen/insights";
import { Msg } from "../../ui/Msg";
import { roleName, skillName } from "../../copy/vocab";
import { clusterLabel } from "./names";

/** Companies named on a group card; the rest are one counted line. */
const CARD_COMPANIES = 8;

export function ClustersView({
  onOpen,
  scope,
}: {
  onOpen: (id: number, companySlug?: string | null) => void;
  scope?: InsightsScope;
}) {
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const clustersResource = useAsyncResource(() => api.clusters(scope), [scope], { keep: "stats/clusters" });
  const detailResource = useAsyncResource<ClusterDetail | null>(
    () => selectedId == null ? Promise.resolve(null) : api.cluster(selectedId),
    [selectedId],
    { keep: "stats/cluster" },
  );
  const clusters: ClusterSummary[] = clustersResource.data?.items ?? [];
  const detail = detailResource.data;
  const cover = usePayCoverage();

  if (clustersResource.loading || clustersResource.error) {
    return (
      <div className="stats-view">
        <ResourceLoadState
          error={clustersResource.error}
          loading={insightsClustersViewLoading()}
          failed={insightsClustersViewLoadFailed()}
          onRetry={clustersResource.retry}
        />
      </div>
    );
  }

  return (
    <div className="stats-view">
      <InsightHero
        tab="clusters"
        figure={insightsClustersViewRoleGroups({ count: clusters.length })}
        line={
          <>
            {clusters.length > 0
              ? insightsClustersViewLargestGroup({ label: clusterLabel(clusters[0]), size: n(clusters[0].size) })
              : insightsClustersViewGroupsAreBuiltFromRole()}
            <InfoTip label={insightsClustersViewAboutRoleGroups()}>
              {insightsClustersViewSemanticGroupsBuiltFromRole()}
            </InfoTip>
          </>
        }
        kpis={[
          { label: insightsClustersViewGroupsTile(), value: n(clusters.length), sub: insightsClustersViewFromRoleDescriptions() },
          { label: insightsClustersViewRolesGrouped(), value: n(clusters.reduce((t, c) => t + c.size, 0)), sub: insightsCommonOpenRolesUnit() },
          { label: insightsClustersViewLargest(), value: n(clusters[0]?.size ?? 0), sub: insightsClustersViewRolesInOneGroup() },
          {
            label: insightsCommonCompanies(),
            value: n(new Set(clusters.flatMap((c) => Object.keys(c.companies))).size),
            sub: insightsClustersViewWithAGroupedRole(),
          },
        ]}
      />

      {clusters.length > 0 && (
        <div className="panel chart-panel chart-panel-wide cluster-landscape">
          <div className="chart-panel-head">
            <div>
              <span className="eyebrow">{insightsClustersViewMarketTerrain()}</span>
              <h3>
                {insightsClustersViewGroupLandscape()}
                <InfoTip label={insightsClustersViewHowToReadTheCluster()}>
                  {insightsClustersViewAreaEncodesActiveRoleVolume()}
                </InfoTip>
              </h3>
            </div>
            <span className="chart-insight"><Msg of={insightsClustersViewGroups} elems={{ count: n(clusters.length) }} /></span>
          </div>
          <ClusterLandscapeChart
            clusters={clusters}
            selectedId={selectedId}
            onSelect={setSelectedId}
          />
        </div>
      )}

      {selectedId != null && (detailResource.loading || detailResource.error) && (
        <ResourceLoadState
          error={detailResource.error}
          loading={insightsClustersViewGroupLoading()}
          failed={insightsClustersViewGroupLoadFailed()}
          onRetry={detailResource.retry}
        />
      )}

      {detail && !detailResource.loading && !detailResource.error && (
        <div className="panel cluster-detail">
          <div className="cluster-detail-head">
            <div>
              <h3>{clusterLabel(detail)}</h3>
              <div className="sub">
                <Msg of={insightsClustersViewRoles} elems={{ family_display: roleName(detail.family_hint), size: detail.size }} />
              </div>
            </div>
            <FilterChip selected onClick={() => setSelectedId(null)}>
              {insightsClustersViewClear()}
            </FilterChip>
          </div>
          <div className="cluster-members">
            {detail.items.map((j) => (
              <JobLinkRow className="mini-job" key={j.id} jobId={j.id} company={j.company} onOpen={onOpen}>
                <div>
                  <div className="mj-title" data-selection="content">{j.title}</div>
                  <div className="mj-meta">
                    {[companyName(j.company), listedFor(j.listed_days)].filter(Boolean).join(" · ")}
                  </div>
                </div>
                <span className="n">{payPoint(j, cover).text}</span>
              </JobLinkRow>
            ))}
          </div>
        </div>
      )}

      <div className="demand-grid">
        {clusters.map((c) => (
          /* The CARD is a container, not a control. A <button> wrapping the
             whole card would also wrap the company chips, which are real
             buttons of their own (a chip's keyboard path to the profile is the
             accessible half of a hover card that is otherwise pointer-only).
             Nested buttons are invalid HTML: the browser reparents them, some
             engines make the inner one unreachable by keyboard, and assistive
             tech announces the pair inconsistently.

             So the card's control is ONE button on the title, stretched over
             the card by a pseudo-element, and the chips are its SIBLINGS, each
             already a positioned box (`.co-chip-wrap`), so it paints above that
             hit area and stays clickable. The whole card is the click target,
             with one keyboard stop for the card and one per chip. The selected
             state is `aria-pressed`, the app's single convention for
             "currently on" (docs/ui.md), so the open territory is announced,
             not only painted. */
          <div
            key={c.id}
            className="panel cluster-card"
          >
            <div className="cluster-card-head">
              <h3>
                <button
                  type="button"
                  className="cluster-card-select"
                  aria-pressed={selectedId === c.id}
                  onClick={() => setSelectedId(selectedId === c.id ? null : c.id)}
                >
                  {clusterLabel(c)}
                </button>
              </h3>
              <span className="cluster-size">{c.size}</span>
            </div>
            <div className="sub">{roleName(c.family_hint)}</div>
            <div className="cluster-terms">
              {c.top_terms.slice(0, 5).map((t) => (
                <Badge shape="tag" key={t.term}>
                  {skillName(t.term)}
                </Badge>
              ))}
            </div>
            {/* The leaders and one counted line: a card listing every
                company down to its single role runs to hundreds of chips. */}
            <div className="cluster-companies">
              {Object.entries(c.companies)
                .sort((a, b) => b[1] - a[1])
                .slice(0, CARD_COMPANIES)
                .map(([co, count]) => (
                  <span className="cluster-co" key={co}>
                    <CompanyChip slug={co} />
                    <span className="cluster-co-n">{count}</span>
                  </span>
                ))}
            </div>
            {Object.keys(c.companies).length > CARD_COMPANIES && (
              <p className="hiring-note">
                <Msg of={insightsClustersViewAndMoreCompanies} elems={{ n: n(Object.keys(c.companies).length - CARD_COMPANIES) }} />
              </p>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
