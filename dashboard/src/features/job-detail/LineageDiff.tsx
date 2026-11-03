import { LineageDiff as LineageDiffData } from "../../api";
import { levelName, payBasisName } from "../../copy/vocab";
import { fmtCompIn } from "../../format";
import {
  roleJobCompPanelBasisNotStated,
  roleJobCompPanelTotalCompensation,
  roleLineageDiffAdded,
  roleLineageDiffChangesSinceThePreviousPosting,
  roleLineageDiffEstimateChanged,
  roleLineageDiffLevelChanged,
  roleLineageDiffLocationsChanged,
  roleLineageDiffNotDisclosed,
  roleLineageDiffPayBandNewlyDisclosed,
  roleLineageDiffPayBasisChanged,
  roleLineageDiffRemoved,
  roleLineageDiffTitleChanged,
} from "../../copy/gen/role";

/* What changed between this posting and the previous one in the stack. Renders
   nothing when nothing material changed. Amounts show in the currency the
   posting stated, never converted. */
function amount(v: number | null | undefined, currency: string | null | undefined): string {
  return v == null ? "—" : fmtCompIn(v, currency ?? "USD");
}

/** The basis a posting states its band on, said. A posting with no band has
 *  none; a code this build has no word for shows as itself. */
const BASIS: Record<string, () => string> = {
  base: () => payBasisName("base"),
  total: roleJobCompPanelTotalCompensation,
  unclear: roleJobCompPanelBasisNotStated,
};
const basis = (code: string | null): string => (code == null ? roleLineageDiffNotDisclosed() : BASIS[code]?.() ?? code);

function band(b: readonly (number | null)[] | null, currency: string | null): string {
  if (!b || (b[0] == null && b[1] == null)) return roleLineageDiffNotDisclosed();
  return `${amount(b[0], currency)}–${amount(b[1], currency)}`;
}

export function LineageDiff({ diff }: { diff: LineageDiffData | null | undefined }) {
  if (!diff) return null;
  const rows: { key: string; label: string; detail: string }[] = [];

  if (diff.title) rows.push({ key: "title", label: roleLineageDiffTitleChanged(), detail: `${diff.title.from} → ${diff.title.to}` });
  if (diff.level_band)
    rows.push({ key: "level", label: roleLineageDiffLevelChanged(), detail: `${levelName(diff.level_band.from)} → ${levelName(diff.level_band.to)}` });
  if (diff.disclosed_band) {
    const from = band(diff.disclosed_band.from, diff.disclosed_band.currency);
    const to = band(diff.disclosed_band.to, diff.disclosed_band.currency);
    const label = roleLineageDiffPayBandNewlyDisclosed({ choice: (diff.disclosed_band.from) ? "yes" : "no" });
    rows.push({ key: "band", label, detail: `${from} → ${to}` });
  }
  if (diff.pay_basis)
    rows.push({ key: "basis", label: roleLineageDiffPayBasisChanged(), detail: `${basis(diff.pay_basis.from)} → ${basis(diff.pay_basis.to)}` });
  if (diff.locations) {
    const parts: string[] = [];
    if (diff.locations.added.length) parts.push(roleLineageDiffAdded({ join: String(diff.locations.added.join(", ")) }));
    if (diff.locations.removed.length) parts.push(roleLineageDiffRemoved({ join: String(diff.locations.removed.join(", ")) }));
    if (parts.length) rows.push({ key: "loc", label: roleLineageDiffLocationsChanged(), detail: parts.join("; ") });
  }
  if (diff.comp_median)
    rows.push({
      key: "est",
      label: roleLineageDiffEstimateChanged(),
      detail: `${amount(diff.comp_median.from, diff.comp_median.currency)} → ${amount(diff.comp_median.to, diff.comp_median.currency)}`,
    });

  if (rows.length === 0) return null;

  return (
    <ul className="lineage-diff" aria-label={roleLineageDiffChangesSinceThePreviousPosting()}>
      {rows.map((r) => (
        <li key={r.key} className="lineage-diff-row">
          <span className="lineage-diff-label">{r.label}</span>
          <span className="lineage-diff-detail">{r.detail}</span>
        </li>
      ))}
    </ul>
  );
}
