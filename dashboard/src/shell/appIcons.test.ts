import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { inflateSync } from "node:zlib";
import { describe, expect, it } from "vitest";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const PUBLIC = join(ROOT, "public");

/** Width and height from a PNG's IHDR chunk. */
function pngSize(path: string): [number, number] {
  const bytes = readFileSync(path);
  expect(bytes.subarray(1, 4).toString("latin1")).toBe("PNG");
  return [bytes.readUInt32BE(16), bytes.readUInt32BE(20)];
}

/** RGBA pixels of an 8-bit, non-interlaced RGBA PNG, unfiltered row by row. */
function pngPixels(path: string): Uint8Array {
  const bytes = readFileSync(path);
  const [width, height] = pngSize(path);
  expect([bytes[24], bytes[25], bytes[28]], `${path} is 8-bit RGBA, not interlaced`).toEqual([8, 6, 0]);
  const chunks: Buffer[] = [];
  for (let at = 8; at < bytes.length; ) {
    const length = bytes.readUInt32BE(at);
    if (bytes.subarray(at + 4, at + 8).toString("latin1") === "IDAT") chunks.push(bytes.subarray(at + 8, at + 8 + length));
    at += length + 12;
  }
  const raw = inflateSync(Buffer.concat(chunks));
  const stride = width * 4;
  const out = new Uint8Array(stride * height);
  for (let y = 0; y < height; y++) {
    const filter = raw[y * (stride + 1)];
    for (let x = 0; x < stride; x++) {
      const value = raw[y * (stride + 1) + 1 + x];
      const left = x >= 4 ? out[y * stride + x - 4] : 0;
      const up = y > 0 ? out[(y - 1) * stride + x] : 0;
      const corner = x >= 4 && y > 0 ? out[(y - 1) * stride + x - 4] : 0;
      const guess = left + up - corner;
      const paeth = [left, up, corner].reduce((best, c) => (Math.abs(guess - c) < Math.abs(guess - best) ? c : best));
      const predictor = [0, left, up, (left + up) >> 1, paeth][filter];
      out[y * stride + x] = (value + predictor) & 0xff;
    }
  }
  return out;
}

const html = readFileSync(join(ROOT, "index.html"), "utf8");
const links = [...html.matchAll(/<link\s+rel="(icon|apple-touch-icon|manifest)"([^>]*)>/g)].map(([, rel, rest]) => ({
  rel,
  href: /href="\/([^"]+)"/.exec(rest)?.[1] ?? "",
  sizes: /sizes="([^"]+)"/.exec(rest)?.[1],
}));

describe("app icons", () => {
  it("links favicons, a touch icon and a manifest, each a file the build ships", () => {
    expect(links.map((link) => link.rel).sort()).toEqual(["apple-touch-icon", "icon", "icon", "icon", "manifest"]);
    for (const link of links) expect(existsSync(join(PUBLIC, link.href)), link.href).toBe(true);
  });

  it("serves every favicon at the size its link declares, and a 180 px touch icon", () => {
    for (const link of links.filter((l) => l.rel === "icon")) {
      expect(pngSize(join(PUBLIC, link.href)).join("x"), link.href).toBe(link.sizes);
    }
    const touch = links.find((l) => l.rel === "apple-touch-icon")!;
    expect(pngSize(join(PUBLIC, touch.href))).toEqual([180, 180]);
  });

  it("draws every favicon in white ink so the mark stands out on a dark tab strip", () => {
    for (const link of links.filter((l) => l.rel === "icon")) {
      const pixels = pngPixels(join(PUBLIC, link.href));
      let inked = 0;
      for (let at = 0; at < pixels.length; at += 4) {
        if (pixels[at + 3] < 128) continue;
        inked += 1;
        expect(Math.min(pixels[at], pixels[at + 1], pixels[at + 2]), `${link.href} ink at pixel ${at / 4}`).toBeGreaterThanOrEqual(240);
      }
      expect(inked, `${link.href} has a visible mark`).toBeGreaterThan(pixels.length / 4 / 10);
    }
  });

  it("gives the manifest a name and an installable icon of every declared size, one of them maskable", () => {
    const manifest = JSON.parse(readFileSync(join(PUBLIC, "manifest.webmanifest"), "utf8"));
    expect(manifest.name).toBeTruthy();
    expect(manifest.start_url).toBe("/");
    for (const icon of manifest.icons as { src: string; sizes: string }[]) {
      expect(pngSize(join(PUBLIC, icon.src.replace(/^\//, ""))).join("x"), icon.src).toBe(icon.sizes);
    }
    const sizes = manifest.icons.map((icon: { sizes: string }) => icon.sizes);
    expect(sizes).toContain("192x192");
    expect(sizes).toContain("512x512");
    expect(manifest.icons.some((icon: { purpose?: string }) => icon.purpose === "maskable")).toBe(true);
  });
});
