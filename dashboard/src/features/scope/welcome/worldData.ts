import { feature, mesh } from "topojson-client";
import type { FeatureCollection, Geometry, MultiLineString } from "geojson";

/* Lazy world geometry for the welcome planet. world-atlas (Natural Earth,
   110m) ships as TopoJSON, decoded once into country features and one
   interior-border mesh. The dynamic import keeps the atlas out of the main
   bundle: it loads only when the planet mounts. */

export interface WorldShapes {
  countries: FeatureCollection<Geometry>;
  borders: MultiLineString;
}

let loading: Promise<WorldShapes> | null = null;

export function loadWorld(): Promise<WorldShapes> {
  loading ??= import("world-atlas/countries-110m.json").then((mod) => {
    const topo = ((mod as any).default ?? mod) as any;
    return {
      countries: feature(topo, topo.objects.countries) as unknown as FeatureCollection<Geometry>,
      borders: mesh(topo, topo.objects.countries, (a: unknown, b: unknown) => a !== b),
    };
  });
  return loading;
}
