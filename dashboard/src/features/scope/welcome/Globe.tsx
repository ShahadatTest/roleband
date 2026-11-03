import { geoGraticule10, geoPath, geoProjection, type GeoPermissibleObjects, type GeoProjection } from "d3-geo";
import { useEffect, useRef } from "react";
import { INTRO_CITIES } from "../../../introCities.gen";
import { RESTING, coast, grab, move, onPlanet, release, type DragState } from "./globeDrag";
import {
  STILL_AT, facingLon, facingShare, horizon, litness, perspective, place, projectionScale, scanEntry, scanLon,
  sinceScan, trailAt, viewDistance, visible, type Placement,
} from "./globeView";
import { loadWorld, type WorldShapes } from "./worldData";

/* The welcome planet: a slowly turning globe on a canvas, with a gold scan
   line crossing it and the cities RoleBand reads lighting as it passes. The
   reader can drag it. It is decoration (`aria-hidden`); the copy beside it
   says what it shows.

   Colours come from the theme's tokens at mount; first-run setup is always
   dark, so these are the dark values. With reduced motion the planet holds
   one frame (STILL_AT) and dragging still works, without a coast. */

const MAX_DENSITY = 2;
const GRATICULE = geoGraticule10();

type Rgb = [number, number, number];

/** A token's colour as rgb, normalised by the canvas itself. */
function tokenRgb(ctx: CanvasRenderingContext2D, from: Element, token: string): Rgb {
  ctx.fillStyle = "#000";
  ctx.fillStyle = getComputedStyle(from).getPropertyValue(token).trim() || "#000";
  const value = String(ctx.fillStyle);
  if (value.startsWith("#")) return [1, 3, 5].map((i) => parseInt(value.slice(i, i + 2), 16)) as Rgb;
  const parts = value.match(/[\d.]+/g)?.map(Number) ?? [0, 0, 0];
  return [parts[0], parts[1], parts[2]];
}

const rgba = ([r, g, b]: Rgb, a: number) => "rgba(" + [Math.round(r), Math.round(g), Math.round(b), a.toFixed(3)].join(",") + ")";
const mix = (a: Rgb, b: Rgb, t: number): Rgb => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];

/** The trail reaches 120 degrees back, where it has faded to nothing, in
    layers this many degrees apart. */
const TRAIL_STEP = 6;
const TRAIL_LAYERS = 120 / TRAIL_STEP;

/** The lune between two meridians, as a polygon d3 clips to the horizon. */
const lune = (west: number, east: number): GeoPermissibleObjects => ({
  type: "Polygon",
  coordinates: [[[west, -89.9], [west, 0], [west, 89.9], [east, 89.9], [east, 0], [east, -89.9], [west, -89.9]]],
});

export function Globe() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext?.("2d");
    if (!canvas || !ctx) return;
    const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
    const gold = tokenRgb(ctx, canvas, "--app-action");
    const ink = tokenRgb(ctx, canvas, "--app-text");
    const ground = tokenRgb(ctx, canvas, "--app-canvas");
    const raised = tokenRgb(ctx, canvas, "--app-surface-raised");

    let world: WorldShapes | null = null;
    let width = 0;
    let height = 0;
    let at: Placement = place(1, 1);
    let distance = 2;
    let projection: GeoProjection = geoProjection(perspective(distance));
    // A Path2D takes every call d3's path makes (it never begins a path).
    const shape = (object: GeoPermissibleObjects): Path2D => {
      const out = new Path2D();
      geoPath(projection, out as unknown as CanvasRenderingContext2D)(object);
      return out;
    };
    let drag: DragState = RESTING;
    let spun = reduced ? STILL_AT : 0;
    let previous: number | null = null;
    // The scan's own clock: it starts where the line has just come round the
    // western edge, on the first frame that draws the map, whenever the page
    // opened. Until then the line waits there.
    let scanFrom: number | null = null;
    let entry = 0;
    let frame = 0;

    const resize = () => {
      const density = Math.min(devicePixelRatio || 1, MAX_DENSITY);
      width = canvas.clientWidth;
      height = canvas.clientHeight;
      canvas.width = Math.round(width * density);
      canvas.height = Math.round(height * density);
      ctx.setTransform(density, 0, 0, density, 0, 0);
      at = place(width, height);
      entry = scanEntry(width, height);
      distance = viewDistance(at.r, height);
      projection = geoProjection(perspective(distance)).clipAngle((horizon(distance) * 180) / Math.PI);
    };

    const draw = (now: number) => {
      if (scanFrom === null && world) scanFrom = now;
      const seconds = reduced ? STILL_AT : entry + (scanFrom === null ? 0 : (now - scanFrom) / 1000);
      const step = previous === null ? 0 : Math.min(0.1, (now - previous) / 1000);
      previous = now;
      if (!reduced && !drag.grab) {
        spun += step;
        drag = coast(drag, step);
      }
      const { r, cx, cy } = at;
      const facing: [number, number] = [facingLon(spun, drag.turned), drag.tilt];
      projection.rotate([-facing[0], -facing[1]]).translate([cx, cy]).scale(projectionScale(r, distance));
      ctx.clearRect(0, 0, width, height);

      const halo = ctx.createRadialGradient(cx, cy, r * 0.97, cx, cy, r * 1.14);
      halo.addColorStop(0, rgba(gold, 0.11));
      halo.addColorStop(1, rgba(gold, 0));
      ctx.fillStyle = halo;
      ctx.beginPath(); ctx.arc(cx, cy, r * 1.14, 0, Math.PI * 2); ctx.fill();

      // The body, lit from the upper left.
      const body = ctx.createRadialGradient(cx - r * 0.4, cy - r * 0.45, r * 0.05, cx, cy, r);
      body.addColorStop(0, rgba(raised, 1));
      body.addColorStop(1, rgba(ground, 1));
      ctx.fillStyle = body;
      ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.fill();

      // Each shape is projected once a frame and drawn from that, filled and
      // clipped alike: projecting is most of a frame's work.
      const land = world ? shape(world.countries) : null;
      if (world && land) {
        ctx.strokeStyle = rgba(ink, 0.05); ctx.lineWidth = 0.6; ctx.stroke(shape(GRATICULE));
        ctx.fillStyle = rgba(ink, 0.11); ctx.fill(land);
        ctx.strokeStyle = rgba(ground, 0.85); ctx.lineWidth = 0.6; ctx.stroke(shape(world.borders));
      }

      // The scan's trail: layers that all start at the line and reach further
      // back each time, so their only shared edge is the line and the fade has
      // no seams. Land just passed gets it again, a little brighter. Every
      // layer is filled twice a frame, so their count is the frame's cost.
      const scan = scanLon(seconds);
      const layers = Array.from({ length: TRAIL_LAYERS }, (_, k) => shape(lune(scan - (k + 1) * TRAIL_STEP, scan)));
      const trail = (strength: number) => {
        layers.forEach((layer, k) => {
          ctx.fillStyle = rgba(gold, strength * (trailAt(k * TRAIL_STEP) - trailAt((k + 1) * TRAIL_STEP)));
          ctx.fill(layer);
        });
      };
      ctx.save();
      ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.clip();
      trail(0.06);
      if (land) { ctx.save(); ctx.clip(land); trail(0.1); ctx.restore(); }
      const limb = ctx.createRadialGradient(cx, cy, r * 0.55, cx, cy, r);
      limb.addColorStop(0, rgba(ground, 0));
      limb.addColorStop(1, rgba(ground, 0.5));
      ctx.fillStyle = limb;
      ctx.fillRect(cx - r, cy - r, 2 * r, 2 * r);
      const line = shape({ type: "LineString", coordinates: [[scan, -89.9], [scan, 0], [scan, 89.9]] });
      ctx.strokeStyle = rgba(gold, 0.18); ctx.lineWidth = 6; ctx.stroke(line);
      ctx.strokeStyle = rgba(gold, 0.9); ctx.lineWidth = 1.5; ctx.stroke(line);
      ctx.restore();

      // Cities: one size, gold; for a moment after the scan passes they turn
      // toward the ink and grow a little, so they still read on the trail.
      for (const [lon, lat] of INTRO_CITIES) {
        if (!visible([lon, lat], facing, distance, 0.04)) continue;
        const point = projection([lon, lat]);
        if (!point) continue;
        const lit = litness(sinceScan(scan, lon));
        const edge = 0.4 + 0.6 * facingShare([lon, lat], facing, distance);
        ctx.fillStyle = rgba(mix(gold, ink, lit * 0.75), (0.62 + 0.38 * lit) * edge);
        ctx.beginPath(); ctx.arc(point[0], point[1], 2.3 + 0.9 * lit, 0, Math.PI * 2); ctx.fill();
      }
    };

    const loop = (now: number) => {
      draw(now);
      if (!reduced) frame = requestAnimationFrame(loop);
    };
    const redraw = () => { if (reduced) draw(performance.now()); };

    const local = (event: PointerEvent): [number, number] => {
      const box = canvas.getBoundingClientRect();
      return [event.clientX - box.left, event.clientY - box.top];
    };
    const onDown = (event: PointerEvent) => {
      const [x, y] = local(event);
      if (!onPlanet(x, y, at)) return;
      drag = grab(drag, x, y, event.timeStamp);
      canvas.setPointerCapture?.(event.pointerId);
      canvas.style.cursor = "grabbing";
    };
    const onMove = (event: PointerEvent) => {
      const [x, y] = local(event);
      if (!drag.grab) { canvas.style.cursor = onPlanet(x, y, at) ? "grab" : ""; return; }
      drag = move(drag, x, y, event.timeStamp, at.r);
      redraw();
    };
    const onUp = (event: PointerEvent) => {
      drag = release(drag, reduced);
      const [x, y] = local(event);
      canvas.style.cursor = onPlanet(x, y, at) ? "grab" : "";
    };

    const observer = new ResizeObserver(() => { resize(); redraw(); });
    observer.observe(canvas);
    canvas.addEventListener("pointerdown", onDown);
    canvas.addEventListener("pointermove", onMove);
    canvas.addEventListener("pointerup", onUp);
    canvas.addEventListener("pointercancel", onUp);
    resize();
    let alive = true;
    loadWorld().then((shapes) => {
      if (!alive) return;
      world = shapes;
      redraw();
    });
    frame = requestAnimationFrame(loop);

    return () => {
      alive = false;
      cancelAnimationFrame(frame);
      observer.disconnect();
      canvas.removeEventListener("pointerdown", onDown);
      canvas.removeEventListener("pointermove", onMove);
      canvas.removeEventListener("pointerup", onUp);
      canvas.removeEventListener("pointercancel", onUp);
    };
  }, []);

  return <canvas ref={canvasRef} className="welcome-globe" aria-hidden="true" />;
}
