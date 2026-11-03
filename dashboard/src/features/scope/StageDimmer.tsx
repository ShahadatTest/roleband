import { compare as copyCompare, number as copyNumber } from "../../copy/format";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useScopeDraft } from "./useScopeDraft";
import { countSelectedScope } from "./scopeDraftModel";
import { UNSTATED_LEVEL, countByOption } from "./scopeCells";
import { Icon, dragSurface } from "../../ui";
import { NewMark } from "./NewMark";
import { companyName } from "../../format";
import { NOUN, UNSTATED_LEVEL_CHOICE, count } from "../../copy/vocabulary";
import {
  profileStageDimmerAimingFor,
  profileStageDimmerClickYourLevelToday,
  profileStageDimmerCompanies,
  profileStageDimmerGated,
  profileStageDimmerLevelRange,
  profileStageDimmerLevelYouReAimingFor,
  profileStageDimmerRoles,
  profileStageDimmerSeeEveryCompany,
  profileStageDimmerThisKindOfRoleTops,
  profileStageDimmerWhatThisMeansAtEach,
  profileStageDimmerYouAreHere,
  profileStageDimmerYourLevelToday,
} from "../../copy/gen/profile";
import { Msg } from "../../ui/Msg";
import { levelName } from "../../copy/vocab";
import { rungWords } from "../../patterns/levels/levelGuide";

/* The career-stage "dimmer band".

   Interaction model — a calendar date-range pick (see docs/ui.md):
   - Fresh click (unplaced wizard, OR a committed pair): drops the "you are here"
     dot on the clicked stage, wiping any prior pair, and ARMS the aim (diamond)
     to follow the pointer. This is the range's anchor.
   - Armed: the aim follows the pointer across stages (live). That live movement
     is a PREVIEW and nothing more — it never touches the draft, so it can never
     be what `save` persists. The next click locks it wherever it lands — above,
     below, or on the anchor — and THAT is the commit. Leaving the rail without
     clicking abandons the preview and the committed rung stands.
   - Any later click starts a brand-new pair: the old markers disappear and the
     click becomes the next anchor. You never re-touch an existing marker.
   - Both handles stay keyboard sliders (arrow keys) as a parallel path.

   Handles live in one overlay layer positioned by percentage, so they glide
   between stages instead of teleporting. Under the rail, the decoder shows how
   each company grades the stage for the selected work — a company-wide number
   (Google "L5"), a technical-only code for technical roles (Apple "ICT4"), or
   the plain tier name when the company publishes no grade for that function.

   The decoder is a collapsed disclosure: it names every reference company, so
   open by default it is far taller than the rail it explains and pushes the
   step's Continue out of sight, in first-run setup as in Profile.

   Tiers a function never occupies (e.g. a new-grad manager) are disabled via the
   allowed-band gate from useScopeDraft; handles cannot land on them, and a
   line under the rail says why they are crossed out.

   `unstatedChoice` offers the choice for roles that state no level. First-run
   setup leaves it at its default and Profile offers it. `everyCompany` links
   the decoder to Insights' Levels tab, which names every reviewed ladder. */

type Handle = "current" | "aim";

/** Insights' Levels tab on the career track this draft reads: hands-on,
 *  the tab's own default, needs no key. */
function levelsLink(tracks: ReadonlySet<string>): string {
  const first = [...tracks][0];
  return tracks.size === 0 || tracks.has("technical") || !first ? "/statistics/levels" : `/statistics/levels?track=${first}`;
}

export function StageDimmer({ unstatedChoice = true, everyCompany = false }: {
  unstatedChoice?: boolean;
  everyCompany?: boolean;
} = {}) {
  const {
    catalog,
    experienceStage, targetStage,
    setExperienceStage, setTargetStage,
    selectedTracks, allowedBands, scopeIndex, scopeSelection,
    includeUnstatedLevel, setIncludeUnstatedLevel, countsShown,
  } = useScopeDraft();
  const lockTimer = useRef<number | null>(null);
  // The pulse outlives the click, never the dimmer: a timer left running fires
  // a state update into a component, or a page, that is already gone.
  useEffect(() => () => {
    if (lockTimer.current) window.clearTimeout(lockTimer.current);
  }, []);
  const [armed, setArmed] = useState<Handle | null>(null);
  // The rung under the pointer while aiming. A PREVIEW, deliberately not the
  // draft: pointer movement must never reach what `save` persists.
  const [aimPreview, setAimPreview] = useState<number | null>(null);
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);
  const [lockPulse, setLockPulse] = useState<Handle | null>(null);
  const [decoderOpen, setDecoderOpen] = useState(false);

  /* With the joint counted, a rung says how many roles the person's OTHER
     answers keep at that level (roles, places, interests, the veto), not the
     whole market's inventory for it. */
  const jointByBand = useMemo(
    () => (scopeIndex.ready ? countByOption(scopeIndex, scopeSelection, "bands") : null),
    [scopeIndex, scopeSelection],
  );
  if (!catalog) return null;

  const levels = [...catalog.levels].sort((a, b) => a.order - b.order);
  const unread = !countsShown;
  const order = levels.map((level) => level.slug);
  const savedExpIdx = experienceStage ? order.indexOf(experienceStage) : -1;
  const placed = savedExpIdx >= 0;

  const center = (index: number) => ((index + 0.5) / order.length) * 100;

  /* Roles whose posting states no level sit on no rung: their
     stored Mid is a placeholder, so they are counted apart and admitted by
     the person's choice below, never by the rail. */
  const unstatedCount = jointByBand
    ? jointByBand.get(UNSTATED_LEVEL) ?? 0
    : catalog.unstated_level_count ?? 0;

  const stageCount = (slug: string) => {
    if (jointByBand) return jointByBand.get(slug) ?? 0;
    if (!catalog.joint_counts_ready) {
      return levels.find((level) => level.slug === slug)?.count ?? 0;
    }
    return catalog.categories.reduce(
      (sum, category) => sum + category.groups.reduce(
        (groupSum, group) => groupSum + countSelectedScope(
          { [slug]: group.band_track_counts[slug] ?? {} }, new Set([slug]), selectedTracks,
        ),
        0,
      ),
      0,
    );
  };

  // Gating: which stages the selected function(s) can occupy. The range is
  // contiguous, so a clamp to [floor, ceiling] snaps to the nearest allowed cell.
  const isAllowed = (slug: string) => allowedBands.has(slug);
  const allowedIdxs = order.map((slug, index) => (isAllowed(slug) ? index : -1)).filter((i) => i >= 0);
  const loAllowed = allowedIdxs.length ? allowedIdxs[0] : 0;
  const hiAllowed = allowedIdxs.length ? allowedIdxs[allowedIdxs.length - 1] : order.length - 1;
  const clampAllowed = (index: number) => Math.max(loAllowed, Math.min(hiAllowed, index));
  /* The markers are DRAWN inside the range the chosen kinds of role allow,
     and never rewritten to it. Each kind's range is part of its
     answer in the gate, so a marker on a rung one kind cannot use
     costs nothing, while rewriting it would lose the person's level: Mid under
     "Leading a team" would become Senior and stay Senior after adding
     Hands-on. */
  const expIdx = placed ? clampAllowed(savedExpIdx) : -1;
  const committedTgtIdx = targetStage ? clampAllowed(order.indexOf(targetStage)) : expIdx;
  // While armed the diamond follows the pointer; the committed rung stands
  // behind it until a click (or the keyboard) locks the new one in.
  const tgtIdx = armed === "aim" && aimPreview !== null ? aimPreview : committedTgtIdx;
  const [lo, hi] = [Math.min(expIdx, tgtIdx), Math.max(expIdx, tgtIdx)];
  const disabledReason = (index: number) =>
    profileStageDimmerThisKindOfRoleTops({ choice: (index < loAllowed) ? "yes" : "no" });
  // The same reason on screen, where touch and keyboard reach it: a cell's
  // title shows only to a pointer resting on it.
  const gatedBelow = loAllowed > 0;
  const gatedAbove = hiAllowed < order.length - 1;
  const gatedNote = gatedBelow || gatedAbove
    ? profileStageDimmerGated({
      range: gatedBelow && gatedAbove ? "both" : gatedBelow ? "from" : "to",
      from: levelName(order[loAllowed]),
      to: levelName(order[hiAllowed]),
    })
    : null;

  // Resolve a decoder cell against the live track selection. Company-wide codes
  // apply to every function; a per-track code shows only when every selected
  // track agrees on it; otherwise the seniority word (tierWord) stands in.
  const resolveDecoder = (
    cell: { company_wide?: string; per_track?: Record<string, string> } | undefined,
    tierWord: string,
  ): { label: string; fallback: boolean } | null => {
    if (!cell) return null;
    if (cell.company_wide) return { label: cell.company_wide, fallback: false };
    const tracks = [...selectedTracks];
    const labels = tracks.map((track) => cell.per_track?.[track]).filter((label): label is string => Boolean(label));
    if (tracks.length > 0 && labels.length === tracks.length && new Set(labels).size === 1) {
      return { label: labels[0], fallback: false };
    }
    return { label: tierWord, fallback: true };
  };

  // The reference companies (the catalog sends only those),
  // by the name the company itself uses: "OpenAI", not a capitalised slug. A
  // company with no code of its own for the selected work (an engineering-only
  // ladder while you pick product roles) is left out: its row would only
  // repeat the seniority words the band already shows.
  const decoderCompanies = [...new Set(
    levels.flatMap((level) => Object.keys(level.decoder ?? {})),
  )]
    .filter((company) => levels.some((level) => {
      const resolved = resolveDecoder(level.decoder?.[company], levelName(level.slug));
      return resolved !== null && !resolved.fallback;
    }))
    .sort((a, b) => copyCompare(companyName(a), companyName(b)));

  const firePulse = (handle: Handle) => {
    setLockPulse(handle);
    if (lockTimer.current) window.clearTimeout(lockTimer.current);
    lockTimer.current = window.setTimeout(() => setLockPulse(null), 560);
  };

  // The rung under the pointer is the CELL under the pointer — never arithmetic
  // on the rail's box. The cells wrap into a grid wherever the rail is narrow
  // (every mobile viewport), so dividing the box into even columns would
  // resolve a tap on one rung to another and aim the walk there.
  const onCellPoint = (index: number) => {
    if (armed === "aim") { if (index !== aimPreview) setAimPreview(index); }
    else if (!placed) { if (index !== hoverIdx) setHoverIdx(index); }
  };

  const onCellClick = (index: number) => {
    if (!isAllowed(order[index])) return;  // gated tiers never take a handle
    // Second click of a pair: the aim is armed — lock it wherever the click lands
    // (above, below, or on the anchor; the band spans whichever two cells).
    if (armed) {
      setTargetStage(order[index]);
      setAimPreview(null);
      firePulse("aim");
      setArmed(null);
      return;
    }
    // Fresh click (unplaced wizard OR a committed pair): drop the "you are here"
    // dot here, wiping any existing pair, and arm the aim for the next click.
    setExperienceStage(order[index]);
    setTargetStage(order[index]);
    setAimPreview(null);
    setArmed("aim");
    setHoverIdx(null);
    firePulse("current");
  };

  const sliderKeys = (index: number, move: (slug: string) => void) => (event: React.KeyboardEvent) => {
    const delta = event.key === "ArrowRight" || event.key === "ArrowUp" ? 1
      : event.key === "ArrowLeft" || event.key === "ArrowDown" ? -1
        : 0;
    if (delta === 0) return;
    event.preventDefault();
    const next = clampAllowed(index + delta);
    move(order[next]);
  };

  const hint = profileStageDimmerClickYourLevelToday({ choice: (armed) ? "v1" : (placed) ? "v2" : "v3" });

  return (
    <div className="stage-dimmer">
      <div className="stage-legend" aria-hidden="true">
        <span className="stage-legend-item"><span className="stage-marker static" /> {profileStageDimmerYouAreHere()}</span>
        <span className="stage-legend-item"><span className="stage-edge static" /> {profileStageDimmerAimingFor()}</span>
        <span className="hint">{hint}</span>
      </div>
      <div
        className={`stage-rail${armed ? " armed" : ""}${placed ? "" : " placing"}`}
        role="group"
        aria-label={profileStageDimmerLevelRange()}
        {...dragSurface}
        onPointerLeave={() => { setHoverIdx(null); setAimPreview(null); }}
      >
        {placed && (
          <div
            className="stage-band"
            style={{ "--band-start": `${(lo / order.length) * 100}%`, "--band-size": `${((hi - lo + 1) / order.length) * 100}%` } as React.CSSProperties}
          />
        )}

        <div className="stage-cells">
          {levels.map((level, index) => {
            const isHandle = placed && (index === expIdx || index === tgtIdx);
            const gated = !isAllowed(level.slug);
            return (
              <button
                type="button"
                disabled={gated}
                aria-disabled={gated}
                title={gated ? disabledReason(index) : undefined}
                className={`stage-cell${gated ? " gated" : ""}${placed && index >= lo && index <= hi ? " lit" : ""}${isHandle ? " has-handle" : ""}`}
                key={level.slug}
                onPointerEnter={() => onCellPoint(index)}
                onPointerMove={() => onCellPoint(index)}
                onClick={() => onCellClick(index)}
              >
                <span className="stage-name">{levelName(level.slug)}</span>
                <NewMark on={level.new} />
                {/* A rung the answer rules out shows no count: it cannot be
                    picked. Nor does any rung before anything is read. */}
                {!gated && !unread && <span className="stage-count"><Msg of={profileStageDimmerRoles} elems={{ slug: copyNumber(stageCount(level.slug)) }} /></span>}
              </button>
            );
          })}
        </div>

        {/* Unplaced: a ghost dot previews where the first click lands. */}
        {!placed && hoverIdx !== null && (
          <span className="stage-marker ghost" style={{ "--pos": `${center(hoverIdx)}%` } as React.CSSProperties} />
        )}

        {/* Current level (dot) — keyboard slider + click-to-arm target. */}
        {placed && (
          <span
            className={`stage-marker${armed === "current" ? " armed" : ""}${lockPulse === "current" ? " lock" : ""}`}
            style={{ "--pos": `${center(expIdx)}%` } as React.CSSProperties}
            role="slider"
            tabIndex={0}
            aria-label={profileStageDimmerYourLevelToday()}
            aria-valuemin={0}
            aria-valuemax={order.length - 1}
            aria-valuenow={expIdx}
            aria-valuetext={levelName(levels[expIdx]?.slug)}
            aria-orientation="horizontal"
            onKeyDown={sliderKeys(expIdx, setExperienceStage)}
          />
        )}

        {/* Aim (diamond). */}
        {placed && (
          <span
            className={`stage-edge${armed === "aim" ? " armed" : ""}${lockPulse === "aim" ? " lock" : ""}`}
            style={{ "--pos": `${center(tgtIdx)}%` } as React.CSSProperties}
            role="slider"
            tabIndex={0}
            aria-label={profileStageDimmerLevelYouReAimingFor()}
            aria-valuemin={0}
            aria-valuemax={order.length - 1}
            aria-valuenow={tgtIdx}
            aria-valuetext={levelName(levels[tgtIdx]?.slug)}
            aria-orientation="horizontal"
            onKeyDown={sliderKeys(tgtIdx, (slug) => {
              setTargetStage(slug);
              setAimPreview(null);
              setArmed(null);
            })}
          />
        )}
      </div>

      {gatedNote && <p className="stage-gated-note">{gatedNote}</p>}

      {unstatedChoice && (
        <label className="select-card stage-unstated">
          <input
            type="checkbox"
            checked={includeUnstatedLevel}
            onChange={(event) => setIncludeUnstatedLevel(event.target.checked)}
          />
          <span className="select-card-label">{UNSTATED_LEVEL_CHOICE()}</span>
          <small>{count(NOUN.role, unstatedCount)}</small>
        </label>
      )}

      {decoderCompanies.length > 0 && (
        <>
          <button
            type="button"
            className="stage-decoder-toggle"
            aria-expanded={decoderOpen}
            aria-controls="stage-decoder-table"
            onClick={() => setDecoderOpen((open) => !open)}
          >
            <span>{profileStageDimmerWhatThisMeansAtEach()}</span>
            <span className="stage-decoder-toggle-meta">
              {decoderCompanies.length} {profileStageDimmerCompanies({ count: decoderCompanies.length })}
            </span>
            {/* The same chevron every other disclosure uses; CSS owns the
                rotate-on-expand. */}
            <span className="stage-decoder-toggle-chevron" aria-hidden="true">
              <Icon name="chevronDown" size={11} />
            </span>
          </button>
          {decoderOpen && (
            <div className="stage-decoder" id="stage-decoder-table">
              {decoderCompanies.map((company) => {
                const cells = levels.map((level) => resolveDecoder(level.decoder?.[company], levelName(level.slug)));
                // The row repeats its role ("Software Engineer") on every
                // rung; the cell is too narrow for it, so it shows the rung
                // word and keeps the full title on hover.
                const own = cells.flatMap((cell) => (cell && !cell.fallback ? [cell.label] : []));
                const short = new Map(own.map((label, i) => [label, rungWords(own)[i]]));
                return (
                  <div className="stage-decoder-row" key={company}>
                    <span className="stage-decoder-company">{companyName(company)}</span>
                    {levels.map((level, i) => {
                      const resolved = cells[i];
                      const gated = !isAllowed(level.slug);
                      const shown = resolved && !resolved.fallback ? short.get(resolved.label) ?? resolved.label : resolved?.label;
                      return (
                        <span
                          className={`stage-decoder-cell${resolved?.fallback ? " tier-word" : ""}${gated ? " gated" : ""}`}
                          key={level.slug}
                          title={shown !== resolved?.label ? resolved?.label : undefined}
                        >
                          {shown ?? "—"}
                        </span>
                      );
                    })}
                  </div>
                );
              })}
              {everyCompany && (
                <Link className="stage-decoder-more" to={levelsLink(selectedTracks)}>
                  {profileStageDimmerSeeEveryCompany()}
                </Link>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
