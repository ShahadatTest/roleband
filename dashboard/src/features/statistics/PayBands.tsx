import { useMemo, useState } from "react";
import type { DisclosedBand, DisclosedBands } from "../../api";
import { companyName, fmtComp } from "../../format";
import { FilterSelect } from "../../ui";
import { bandEmployers, bandScale, bandsByLevel, levelSummary } from "./charts/compBands";
import { levelLabel } from "./charts/levelLabel";
import {
  insightsPayBandsAnyEmployer,
  insightsPayBandsBandsFromEmployers,
  insightsPayBandsEachLineIsOnePublished,
  insightsPayBandsEmployerBands,
  insightsPayBandsPublishedBaseSalaryBandsBy,
} from "../../copy/gen/insights";

/* Published base-salary bands, a row per level. See `compBands.ts`
 * for why the unit is the band and never a role. Every band is a faint span;
 * the outlined span is the level's median band; an employer picked here is
 * the only colour on the chart. */

const range = (low: number | null, high: number | null) => `${fmtComp(low)}–${fmtComp(high)}`;

export function PayBands({ disclosed }: { disclosed: DisclosedBands }) {
  const [employer, setEmployer] = useState<string | null>(null);
  const levels = useMemo(() => bandsByLevel(disclosed.bands), [disclosed.bands]);
  const scale = useMemo(() => bandScale(disclosed.bands), [disclosed.bands]);
  const employers = useMemo(() => bandEmployers(disclosed.bands), [disclosed.bands]);

  const span = (low: number, high: number) => ({
    left: `${((low - scale.min) / (scale.max - scale.min)) * 100}%`,
    width: `${Math.max(0.6, ((high - low) / (scale.max - scale.min)) * 100)}%`,
  });

  return (
    <div className="pay-bands">
      <div className="pay-bands-pick">
        <FilterSelect
          label={employer ? companyName(employer) : insightsPayBandsAnyEmployer()}
          options={employers}
          selected={employer ? [employer] : []}
          onChange={(next) => setEmployer(next[0] ?? null)}
          multiple={false}
          searchable
        />
        <span className="hiring-note">
          {insightsPayBandsEachLineIsOnePublished()}
        </span>
      </div>
      <ol className="pay-bands-rows" aria-label={insightsPayBandsPublishedBaseSalaryBandsBy()}>
        {levels.map((row) => {
          const picked: DisclosedBand[] = employer ? row.bands.filter((b) => b.company === employer) : [];
          return (
            <li key={row.level} className="pay-bands-row">
              <span className="pay-bands-level">
                <strong>{levelLabel(row.level)}</strong>
                <span className="dim">
                  {insightsPayBandsBandsFromEmployers({ bands: row.bands.length, employers: row.employers })}
                </span>
              </span>
              <span className="pay-bands-track" role="img" aria-label={levelSummary(row, picked, employer)}>
                {row.bands.map((b) => (
                  <span key={`${b.company}-${b.low}-${b.high}`} className="pay-band" style={span(b.low, b.high)} />
                ))}
                {row.low != null && row.high != null && (
                  <span className="pay-band-median" style={span(row.low, row.high)} />
                )}
                {picked.map((b) => (
                  <span key={`picked-${b.low}-${b.high}`} className="pay-band" data-chosen style={span(b.low, b.high)} />
                ))}
              </span>
              <span className={`pay-bands-value${employer && !picked.length ? " dim" : ""}`}>
                {!employer
                  ? range(row.low, row.high)
                  : picked.length === 1
                    ? range(picked[0].low, picked[0].high)
                    : insightsPayBandsEmployerBands({
                        published: picked.length ? "some" : "none",
                        bands: picked.length,
                        range: picked.length ? range(Math.min(...picked.map((b) => b.low)), Math.max(...picked.map((b) => b.high))) : "",
                      })}
              </span>
            </li>
          );
        })}
      </ol>
      {/* The axis shares the rows' grid, so its ticks sit under the tracks. */}
      <div className="pay-bands-row" aria-hidden="true">
        <span />
        <span className="pay-bands-axis">
          {scale.ticks.map((t) => (
            <span key={t} style={{ left: `${((t - scale.min) / (scale.max - scale.min)) * 100}%` }}>
              {fmtComp(t)}
            </span>
          ))}
        </span>
        <span />
      </div>
    </div>
  );
}
