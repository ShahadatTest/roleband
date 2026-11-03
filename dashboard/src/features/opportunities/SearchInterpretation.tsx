import type { ReactNode } from "react";
import { Abbr } from "../../ui/Abbr";
import { Badge } from "../../ui/Badge";
import {
  radarFieldCompany,
  radarFieldDiscipline,
  radarFieldLevel,
  radarFieldLocation,
  radarFieldPay,
  radarFieldPayFull,
  radarFieldWorkplace,
  radarInterpAria,
  radarInterpLabel,
  radarInterpPayMax,
  radarInterpPayMin,
  radarInterpPayRange,
} from "../../copy/gen/radar";
import { ParsedQuery } from "../../api";
import { BAND_LABEL, LOC_LABEL, WORKPLACE_LABEL, companyName, fmtComp } from "../../format";
import { roleName } from "../../copy/vocab";

/* Renders "interpreted as ..." chips for the structured filters the backend
   parsed out of a natural-language query. Only shown on the Best-match path, and
   only when at least one structured filter was recognized — a plain keyword query
   parses to nothing and this stays hidden. */
export function SearchInterpretation({ parsed }: { parsed?: ParsedQuery | null }) {
  if (!parsed) return null;

  const chips: { key: string; kicker: ReactNode; value: string }[] = [];
  parsed.company.forEach((s) => chips.push({ key: `co-${s}`, kicker: radarFieldCompany(), value: companyName(s) }));
  parsed.level_band.forEach((s) => chips.push({ key: `lv-${s}`, kicker: radarFieldLevel(), value: BAND_LABEL[s] ?? s }));
  parsed.family.forEach((s) =>
    chips.push({ key: `fam-${s}`, kicker: radarFieldDiscipline(), value: roleName(s) })
  );
  parsed.workplace_type.forEach((s) =>
    chips.push({ key: `wp-${s}`, kicker: radarFieldWorkplace(), value: WORKPLACE_LABEL[s] ?? s })
  );
  parsed.location_group.forEach((s) =>
    chips.push({ key: `loc-${s}`, kicker: radarFieldLocation(), value: LOC_LABEL[s] ?? s })
  );
  if (parsed.comp_min != null || parsed.comp_max != null) {
    const value =
      parsed.comp_min != null && parsed.comp_max != null
        ? radarInterpPayRange({ min: fmtComp(parsed.comp_min), max: fmtComp(parsed.comp_max) })
        : parsed.comp_min != null
        ? radarInterpPayMin({ min: fmtComp(parsed.comp_min) })
        : radarInterpPayMax({ max: fmtComp(parsed.comp_max) });
    chips.push({ key: "comp", kicker: <Abbr short={radarFieldPay()} full={radarFieldPayFull()} />, value });
  }

  if (chips.length === 0) return null;

  return (
    <div className="search-interp" role="group" aria-label={radarInterpAria()}>
      <span className="si-label">{radarInterpLabel()}</span>
      {chips.map((c) => (
        <Badge key={c.key} shape="tag" variant="tint" className="si-chip">
          <span className="k">{c.kicker}</span> {c.value}
        </Badge>
      ))}
    </div>
  );
}
