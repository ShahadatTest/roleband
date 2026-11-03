import "../../patterns/companies/company-chip.css";
import { ResourceLoadState } from "../../ui/ResourceLoadState";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { EmptyState, ExternalLink, Segmented } from "../../ui";
import { CompanyPrices, PRICE_FEED_KEY_URL, api } from "../../api";
import { calendarDay, number } from "../../copy/format";
import { companyName } from "../../format";
import { EChart } from "../../ui/EChart";
import {
  profilesStockPricePanelAddKey,
  profilesStockPricePanelClose,
  profilesStockPricePanelDailyClosesOverLatestUnknown,
  profilesStockPricePanelDayMove,
  profilesStockPricePanelEmptyTitle,
  profilesStockPricePanelLoading,
  profilesStockPricePanelNeedsKey,
  profilesStockPricePanelPriceHistoryUnavailableRightNow,
  profilesStockPricePanelPriceRange,
  profilesStockPricePanelRange,
  profilesStockPricePanelRangeMove,
  profilesStockPricePanelStockPrice,
  profilesStockPricePanelStockPrice2,
  profilesStockPricePanelWaiting,
} from "../../copy/gen/profiles";
import { sharedPriceFeedGetKey } from "../../copy/gen/shared";
import { Msg } from "../../ui/Msg";
import { usePricesVersion } from "../../context/SyncState";

const RANGES = ["1m", "3m", "6m", "1y"] as const;
type Range = (typeof RANGES)[number];
type Direction = "up" | "down" | "flat";
/** The catalog's key for a range (a Fluent variant key cannot lead with a digit). */
const RANGE_KEY = { "1m": "m1", "3m": "m3", "6m": "m6", "1y": "y1" } as const;

const direction = (move: number | null): Direction => (move == null || move === 0 ? "flat" : move > 0 ? "up" : "down");
/** A price in its own currency, to the cent (the shell's `money` rounds to whole units). */
const price = (value: number, currency: string, digits = 2) =>
  number(value, { style: "currency", currency, minimumFractionDigits: digits, maximumFractionDigits: digits });
const signed = (value: number, options: Intl.NumberFormatOptions) => number(value, { ...options, signDisplay: "exceptZero" });

// A listed company's daily closes. One
// instrument: the ticker beside the title, the range on the right; the last
// close at the stat size with the day's move in money and percent and the day
// it closed; the move across the chosen range on the right, which is what the
// line's colour says, so the number and the line never disagree. The chart is
// straight segments (closes are points, a curve between them invents prices).
// With no prices, a ghost of the chart holds its room, titled with why and
// what to do, and the range control is gone: it would choose between nothings.
export function StockPricePanel({ slug, ticker }: { slug: string; ticker?: string | null }) {
  const [range, setRange] = useState<Range>("3m");
  const [data, setData] = useState<CompanyPrices | null>(null);
  const [failed, setFailed] = useState(false);
  // The prices job's run ended: what it stored is shown without a reload.
  const pricesVersion = usePricesVersion();

  useEffect(() => {
    let alive = true;
    setFailed(false);
    api
      .companyPrices(slug, range)
      .then((d) => alive && setData(d))
      .catch(() => alive && setFailed(true));
    return () => {
      alive = false;
    };
  }, [slug, range, pricesVersion]);

  const bars = useMemo(() => data?.bars ?? [], [data]);
  const currency = data?.latest?.currency || data?.currency || "USD";
  // The move across the visible window (first vs last close): the line's colour and its label.
  const rangeMove = bars.length >= 2 ? (bars[bars.length - 1].close - bars[0].close) / bars[0].close : null;
  const rangeDir = direction(rangeMove);

  const option = useMemo(() => {
    const down = rangeDir === "down";
    const hue = down ? "var(--app-danger)" : "var(--app-positive)";
    // The fill fades from the hue's soft tint at the line to the panel's own
    // surface at the axis: tokens only, so both themes hold.
    const tint = down ? "var(--app-danger-soft)" : "var(--app-positive-soft)";
    return {
      grid: { left: 52, right: 8, top: 12, bottom: 24 },
      xAxis: {
        type: "category",
        data: bars.map((b) => b.date),
        boundaryGap: false,
        axisLabel: { formatter: (iso: string) => calendarDay(iso), showMinLabel: true, showMaxLabel: true, hideOverlap: true, color: "var(--app-text-muted)" },
        axisLine: { lineStyle: { color: "var(--app-border-strong)" } },
        axisTick: { show: false },
      },
      yAxis: {
        type: "value",
        scale: true,
        splitNumber: 4,
        axisLabel: { formatter: (v: number) => price(v, currency, 0), color: "var(--app-text-muted)" },
        splitLine: { lineStyle: { color: "var(--app-border)" } },
      },
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "line", lineStyle: { color: "var(--app-border-strong)" } },
        formatter: (points: { axisValue: string; value: number }[]) =>
          `${calendarDay(points[0].axisValue)} · ${price(points[0].value, currency)}`,
      },
      series: [
        {
          type: "line",
          data: bars.map((b) => b.close),
          showSymbol: false,
          smooth: false,
          lineStyle: { color: hue, width: 1.5 },
          areaStyle: {
            color: {
              type: "linear", x: 0, y: 0, x2: 0, y2: 1,
              colorStops: [
                { offset: 0, color: tint },
                { offset: 1, color: "var(--app-surface-raised)" },
              ],
            },
          },
        },
      ],
    };
  }, [bars, currency, rangeDir]);

  const latest = data?.latest ?? null;
  const hasPrices = latest !== null || bars.length > 0;
  const dayDir = direction(latest?.change_pct ?? null);
  const shownTicker = latest?.ticker ?? ticker ?? null;

  return (
    <div className="panel" data-testid="stock-panel">
      <div className="prof-card-head">
        <span className="prof-price-title">
          <h3>{profilesStockPricePanelStockPrice()}</h3>
          {shownTicker && <span className="prof-card-stat" data-testid="stock-ticker">{shownTicker}</span>}
        </span>
        {hasPrices && (
          <Segmented
            label={profilesStockPricePanelPriceRange()}
            value={range}
            onChange={(next) => setRange(next as Range)}
            options={RANGES.map((r) => ({ value: r, label: profilesStockPricePanelRange({ range: RANGE_KEY[r] }) }))}
          />
        )}
      </div>

      {latest && (
        <div className="prof-price-now" data-testid="stock-quote">
          <span className="prof-price-quote">{price(latest.price, currency)}</span>
          {latest.change_abs != null && latest.change_pct != null && (
            <span className={`co-card-change co-change-${dayDir}`} data-testid="stock-day-move">
              {profilesStockPricePanelDayMove({
                money: String(signed(latest.change_abs, { style: "currency", currency, minimumFractionDigits: 2, maximumFractionDigits: 2 })),
                percent: String(signed(latest.change_pct / 100, { style: "percent", minimumFractionDigits: 2, maximumFractionDigits: 2 })),
              })}
            </span>
          )}
          <span className="prof-price-asof">{profilesStockPricePanelClose({ date: String(calendarDay(latest.as_of)) })}</span>
          {rangeMove != null && (
            <span className={`prof-price-range co-change-${rangeDir}`} data-testid="stock-range-move">
              {profilesStockPricePanelRangeMove({
                move: String(signed(rangeMove, { style: "percent", minimumFractionDigits: 1, maximumFractionDigits: 1 })),
                range: RANGE_KEY[range],
              })}
            </span>
          )}
        </div>
      )}

      {failed ? (
        <EmptyState variant="preview" art="chart" title={profilesStockPricePanelPriceHistoryUnavailableRightNow()} />
      ) : !data ? (
        <ResourceLoadState error={null} loading={profilesStockPricePanelLoading()} />
      ) : bars.length === 0 ? (
        <div data-testid="price-empty">
          <EmptyState
            variant="preview"
            art="chart"
            title={profilesStockPricePanelEmptyTitle()}
            actions={data.feed_configured ? undefined : (
              <Link className="ui-btn ui-btn-ghost ui-btn-sm" to="/settings/plugins">{profilesStockPricePanelAddKey()}</Link>
            )}
          >
            {data.feed_configured ? (
              profilesStockPricePanelWaiting()
            ) : (
              <Msg
                of={profilesStockPricePanelNeedsKey}
                elems={{
                  key: <ExternalLink href={PRICE_FEED_KEY_URL}>{sharedPriceFeedGetKey()}</ExternalLink>,
                }}
              />
            )}
          </EmptyState>
        </div>
      ) : (
        <EChart
          ariaLabel={profilesStockPricePanelStockPrice2({ slug: String(companyName(slug)), range: String(range) })}
          summary={profilesStockPricePanelDailyClosesOverLatestUnknown({ choice: (latest) ? "yes" : "no", length: bars.length, range: String(range), toFixed: (latest) ? String(latest.price.toFixed(2)) : "" })}
          height={220}
          option={option}
        />
      )}
      {data?.attribution && bars.length > 0 && <div className="prof-attribution">{data.attribution}</div>}
    </div>
  );
}
