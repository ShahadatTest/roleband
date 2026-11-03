import { number as copyNumber } from "../../../copy/format";
import { useId, useState, type CSSProperties, type KeyboardEvent } from "react";
import { isPending, share, type WalkProgress } from "./walkProgress";
import { STEPS, type StepId, type WalkView } from "./walkSteps";
import {
  profileRadarPyramidAfterTheFirstThreeAnswers,
  profileRadarPyramidAnsweredNoCountYet,
  profileRadarPyramidChoose,
  profileRadarPyramidCountedAfterYouSave,
  profileRadarPyramidCounting,
  profileRadarPyramidIllustrativeFunnelEachPercentageIs,
  profileRadarPyramidKeeps,
  profileRadarPyramidLocked,
  profileRadarPyramidNoCount,
  profileRadarPyramidNotAnsweredYet,
  profileRadarPyramidSaveFirst,
  profileRadarPyramidUrlFill,
  profileRadarPyramidWhatEachAnswerKeeps,
  profileScopeSectionRoles,
} from "../../../copy/gen/profile";

/* Five illustrative layers; real cumulative shares always visible beside
   them. Geometry never claims to measure volume. The full labelled row is
   the pointer/keyboard target, including the narrow tip. */

export type LayerState = "built" | "open" | "pending" | "locked" | "uncounted";

export interface PyramidLayer {
  id: StepId;
  label: string;
  gist: string;
  state: LayerState;
  /** What the layer keeps, in words: the share and the count once counted. */
  detail: string;
  metric: string;
}

/** The five layers for a draft, Role (the wide top) first. Pure: the figure only draws it. */
export function pyramidLayers(
  progress: WalkProgress,
  answered: Record<StepId, boolean>,
  used: { roles: boolean; subjects: boolean },
  stageOneComplete: boolean,
  /** The answers in words, when there is nothing to count yet. */
  named: Record<StepId, string> | null = null,
): PyramidLayer[] {
  const roles = (count: number) => profileScopeSectionRoles({ count: count, count2: String(copyNumber(count)) });
  return STEPS.map((step): PyramidLayer => {
    const base = { id: step.id, label: step.label, gist: step.gist };
    const narrows = step.optional ? used[step.id as "roles" | "subjects"] : answered[step.id];
    if (step.optional && !stageOneComplete) return { ...base, state: "locked", detail: profileRadarPyramidAfterTheFirstThreeAnswers(), metric: profileRadarPyramidLocked() };
    if (!narrows) return { ...base, state: "open", detail: profileRadarPyramidNotAnsweredYet({ choice: (step.optional) ? "yes" : "no" }), metric: profileRadarPyramidChoose({ choice: (step.optional) ? "yes" : "no" }) };
    if (named) return { ...base, state: "uncounted", detail: named[step.id], metric: named[step.id] };
    if (!progress.ready) return { ...base, state: "uncounted", detail: profileRadarPyramidAnsweredNoCountYet(), metric: profileRadarPyramidNoCount() };
    if (isPending(progress, step.id)) {
      return progress.counting
        ? { ...base, state: "pending", detail: profileRadarPyramidCounting(), metric: profileRadarPyramidCounting() }
        : { ...base, state: "pending", detail: profileRadarPyramidCountedAfterYouSave(), metric: profileRadarPyramidSaveFirst() };
    }
    const kept = progress.kept[step.id];
    return { ...base, state: "built", detail: profileRadarPyramidKeeps({ kept: String(share(kept, progress.total)), kept2: String(roles(kept)) }), metric: share(kept, progress.total) };
  });
}

// Point-down silhouette with room beside every band for a readable label.
const W = 360;
const TOP = 2;
const BOTTOM = 182;
const HALF = 90;
const CENTER = 96;
const GAP = 6;

/** Layer `index` (0 = the wide top) of `count` even layers of one
    point-down triangle, corners clockwise from the top left. */
export function layerPoints(index: number, count: number): string {
  const step = (BOTTOM - TOP) / count;
  const high = TOP + index * step;
  const low = high + step - (index === count - 1 ? 0 : GAP);
  const half = (y: number) => ((BOTTOM - y) / (BOTTOM - TOP)) * HALF;
  const cx = CENTER;
  return [
    [cx - half(high), high], [cx + half(high), high], [cx + half(low), low], [cx - half(low), low],
  ].map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
}

export function RadarPyramid({
  layers, view, onGo, named = false,
}: {
  layers: PyramidLayer[];
  view: WalkView;
  onGo: (view: WalkView) => void;
  /** Each layer says its answer under its name, where a share would sit beside it. */
  named?: boolean;
}) {
  const id = useId();
  const [hovered, setHovered] = useState<StepId | null>(null);
  const step = (BOTTOM - TOP) / layers.length;

  const go = (layer: PyramidLayer) => {
    if (layer.state !== "locked") onGo(layer.id);
  };
  const onKey = (event: KeyboardEvent, layer: PyramidLayer) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      go(layer);
    }
  };

  return (
    <div className={named ? "walk-pyramid walk-pyramid--named" : "walk-pyramid"}>
      <div className="walk-pyramid-drawing">
        <svg
          className="walk-pyramid-svg"
          viewBox={`0 0 ${W} ${BOTTOM + 2}`}
          role="group"
          aria-label={profileRadarPyramidWhatEachAnswerKeeps()}
          onMouseLeave={() => setHovered(null)}
        >
          <title>{profileRadarPyramidIllustrativeFunnelEachPercentageIs()}</title>
          <defs>
            <linearGradient id={`${id}-fill`} x1="0" x2="1" y1="0" y2="1">
              <stop offset="0" stopColor="var(--app-action)" stopOpacity="0.15" />
              <stop offset="1" stopColor="var(--app-action)" stopOpacity="0.55" />
            </linearGradient>
          </defs>
          {layers.map((layer, index) => {
            const high = TOP + index * step;
            const current = layer.id === view;
            return (
              <g
                key={layer.id}
                className={`walk-pyramid-layer is-${layer.state}${hovered === layer.id ? " is-hovered" : ""}`}
                style={{ "--depth": index / (layers.length - 1), "--pyramid-fill": profileRadarPyramidUrlFill({ id: String(id) }) } as CSSProperties}
                role="button"
                tabIndex={layer.state === "locked" ? -1 : 0}
                aria-label={layer.label}
                aria-describedby={`${id}-${layer.id}`}
                aria-current={current ? "step" : undefined}
                aria-disabled={layer.state === "locked" || undefined}
                onMouseEnter={() => setHovered(layer.id)}
                onFocus={() => setHovered(layer.id)}
                onBlur={() => setHovered(null)}
                onClick={() => go(layer)}
                onKeyDown={(event) => onKey(event, layer)}
              >
                <title>{layer.gist}.</title>
                <rect className="walk-pyramid-hit" x={0} y={high} width={W} height={step} />
                <polygon className="walk-pyramid-shape" points={layerPoints(index, layers.length)} />
                <line className="walk-pyramid-guide" x1={CENTER + HALF * (1 - (index + 0.5) / layers.length) + 8} x2="208" y1={high + step / 2 + 3} y2={high + step / 2 + 3} />
                <circle className="walk-pyramid-marker" cx="208" cy={high + step / 2 + 3} r="2.5" />
              </g>
            );
          })}
        </svg>
        {/* One label row per layer, so first-run setup's three layers line up
            with their guides as the walk's five do. */}
        <div className="walk-pyramid-labels" aria-hidden="true" style={{ "--pyramid-layers": layers.length } as CSSProperties}>
          {layers.map((layer) => (
            <span key={layer.id} className="walk-pyramid-caption" data-chosen={layer.id === view || undefined}>
              <strong>{layer.label}</strong>
              <span>{layer.metric}</span>
            </span>
          ))}
        </div>
      </div>
      {layers.map((layer) => (
        <span key={layer.id} id={`${id}-${layer.id}`} hidden>{layer.detail}</span>
      ))}
    </div>
  );
}
