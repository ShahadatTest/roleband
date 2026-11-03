import { act, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CompanyIcon } from "./CompanyIcon";
import { BRAND_ICONS } from "./brandIcons.gen";
import { BRAND_ICON_SLUGS } from "./brandIconManifest.gen";
import {
  __resetBrandIconCache,
  hasBrandIcon,
  loadBrandIcon,
  resolveBrandIcon,
} from "./brandIcons";

const markOf = (el: HTMLElement) => el.querySelector("svg path")?.getAttribute("d") ?? null;

describe("resolveBrandIcon", () => {
  it("matches on slug", () => {
    expect(resolveBrandIcon("netflix", "Netflix")?.title).toBe("Netflix");
  });

  it("matches on display name when the slug is careers-URL shaped", () => {
    // Our slug is "riot-games"; the icon set files it as "riotgames".
    expect(resolveBrandIcon("riot-games", "Riot Games")?.title).toBe("Riot Games");
  });

  it("uses the alias table where neither form normalises", () => {
    expect(resolveBrandIcon("google-deepmind", "Google DeepMind")?.title).toBe("DeepMind");
    expect(resolveBrandIcon("electronic-arts", "Electronic Arts")?.title).toBe("EA");
  });

  it("returns null for companies the icon set does not carry", () => {
    // Amazon and Microsoft are genuinely absent upstream (brand takedowns), and
    // quant firms were never there. A resolver that fuzzy-matched would wrongly
    // hand back some unrelated mark here.
    for (const [slug, display] of [
      ["amazon", "Amazon"],
      ["microsoft", "Microsoft"],
      ["jane-street", "Jane Street"],
      ["mckinsey-company", "McKinsey & Company"],
    ]) {
      expect(resolveBrandIcon(slug, display), slug).toBeNull();
    }
  });

  it("does not invent a mark for an unknown company", () => {
    expect(resolveBrandIcon("not-a-real-company", "Not A Real Company")).toBeNull();
  });
});

describe("CompanyIcon", () => {
  it("renders the brand path for a covered company", () => {
    const { container } = render(<CompanyIcon slug="netflix" display="Netflix" />);
    const el = container.firstChild as HTMLElement;
    expect(el.className).not.toContain("is-monogram");
    expect(markOf(el)).toBe(BRAND_ICONS.netflix.path);
  });

  it("falls back to an initial for an uncovered company", () => {
    const { container } = render(<CompanyIcon slug="jane-street" display="Jane Street" />);
    const el = container.firstChild as HTMLElement;
    expect(el.className).toContain("is-monogram");
    expect(el.querySelector("svg")).toBeNull();
    // Drawn by CSS from the attribute; no text node joins a parent's label.
    expect(el.querySelector("[data-letter]")).toHaveAttribute("data-letter", "J");
    expect(el.textContent).toBe("");
  });

  it("renders different companies with different marks", () => {
    // Guards against a resolver that returns the same (e.g. first) icon for
    // everything — which would still pass a single-company assertion.
    const a = render(<CompanyIcon slug="netflix" display="Netflix" />);
    const b = render(<CompanyIcon slug="spotify" display="Spotify" />);
    expect(markOf(a.container.firstChild as HTMLElement)).not.toBe(
      markOf(b.container.firstChild as HTMLElement),
    );
  });

  it("emits both theme variants so CSS can switch without JS", () => {
    const { container } = render(<CompanyIcon slug="apple" display="Apple" />);
    const style = (container.firstChild as HTMLElement).getAttribute("style") ?? "";
    expect(style).toContain("--brand-l");
    expect(style).toContain("--brand-d");
    // Apple is #000000: the dark variant must have been lifted off black, and
    // the two variants must differ.
    expect(style).not.toContain("--brand-d: #000000");
  });

  it("gives an uncovered company a real colour, not currentColor", () => {
    // hueFor() must return a hex: brandInk cannot parse an hsl() string, and an
    // unparsed tint silently falls back to currentColor. Assert a concrete hex.
    const { container } = render(<CompanyIcon slug="optiver" display="Optiver" />);
    const style = (container.firstChild as HTMLElement).getAttribute("style") ?? "";
    expect(style).not.toContain("currentColor");
    expect(style).toMatch(/--brand-l:\s*#[0-9a-f]{6}/i);
    expect(style).toMatch(/--brand-d:\s*#[0-9a-f]{6}/i);
  });

  it("keeps an uncovered company's monogram colour stable across renders", () => {
    const one = render(<CompanyIcon slug="optiver" display="Optiver" />);
    const two = render(<CompanyIcon slug="optiver" display="Optiver" />);
    expect((one.container.firstChild as HTMLElement).getAttribute("style")).toBe(
      (two.container.firstChild as HTMLElement).getAttribute("style"),
    );
  });

  it("gives different uncovered companies different monogram colours", () => {
    const a = render(<CompanyIcon slug="optiver" display="Optiver" />);
    const b = render(<CompanyIcon slug="citadel" display="Citadel" />);
    expect((a.container.firstChild as HTMLElement).getAttribute("style")).not.toBe(
      (b.container.firstChild as HTMLElement).getAttribute("style"),
    );
  });

  it("prefers an explicit fallbackColor over the derived hue when uncovered", () => {
    const { container } = render(
      <CompanyIcon slug="citadel" display="Citadel" fallbackColor="#E50914" />,
    );
    expect((container.firstChild as HTMLElement).getAttribute("style")).toContain("#e50914");
  });

  it("ignores fallbackColor when the icon set supplies the brand colour", () => {
    const { container } = render(
      <CompanyIcon slug="netflix" display="Netflix" fallbackColor="#00ff00" />,
    );
    expect((container.firstChild as HTMLElement).getAttribute("style")).not.toContain("#00ff00");
  });
});

// The reason tier 2 exists: a company added through "Add a company by link" is a
// database row, so no build-time generation can ever have seen it.
describe("lazy resolution for URL-added companies", () => {
  beforeEach(() => __resetBrandIconCache());

  it("does not bundle marks it can still resolve", () => {
    // Zoom is upstream but not a catalog company, so it must be absent from the
    // eager set and present in the manifest. If this ever inverts, the whole
    // lazy tier is either dead code or has silently swallowed the bundle.
    expect(BRAND_ICONS.zoom).toBeUndefined();
    expect(BRAND_ICON_SLUGS.has("zoom")).toBe(true);
    expect(resolveBrandIcon("zoom", "Zoom")).toBeNull();
  });

  it("loads a mark that was never in the bundled set", async () => {
    const icon = await loadBrandIcon("zoom", "Zoom");
    expect(icon?.title).toBe("Zoom");
    expect(icon?.path.length).toBeGreaterThan(10);
    expect(icon?.hex).toMatch(/^#[0-9a-fA-F]{6}$/);
  });

  it("resolves by display name when the slug is URL-derived", async () => {
    // "Add by link" slugifies the name, so both spellings must land.
    expect((await loadBrandIcon("hugging-face", "Hugging Face"))?.title).toBe("Hugging Face");
    expect((await loadBrandIcon("duolingo", "Duolingo"))?.title).toBe("Duolingo");
  });

  it("answers 'no mark' offline for a company absent upstream", async () => {
    // Amazon ships in the default catalog and is NOT upstream. It must resolve
    // to null without a shard: this is the case that made a whole-pack download
    // unacceptable.
    expect(hasBrandIcon("amazon", "Amazon")).toBe(false);
    expect(await loadBrandIcon("amazon", "Amazon")).toBeNull();
    expect(await loadBrandIcon("jane-street", "Jane Street")).toBeNull();
  });

  it("hasBrandIcon covers both tiers, so callers need not await to choose", () => {
    expect(hasBrandIcon("netflix", "Netflix")).toBe(true); // eager
    expect(hasBrandIcon("zoom", "Zoom")).toBe(true); // lazy
    expect(hasBrandIcon("citadel", "Citadel")).toBe(false); // never
  });

  it("renders a lazily-resolved mark into the DOM", async () => {
    const expected = (await loadBrandIcon("zoom", "Zoom"))!.path;
    __resetBrandIconCache();

    const { container } = render(<CompanyIcon slug="zoom" display="Zoom" />);
    // First paint has no mark; the monogram is the honest interim state.
    expect((container.firstChild as HTMLElement).className).toContain("is-monogram");

    await waitFor(() =>
      expect(container.querySelector("svg path")).toHaveAttribute("d", expected),
    );
    expect((container.firstChild as HTMLElement).className).not.toContain("is-monogram");
    // The mark also brings its brand colour, not the derived monogram hue.
    expect((container.firstChild as HTMLElement).getAttribute("style")).not.toContain(
      "currentColor",
    );
  });

  it("never schedules a load for a company with no mark anywhere", async () => {
    const { container } = render(<CompanyIcon slug="amazon" display="Amazon" />);
    const el = container.firstChild as HTMLElement;
    expect(el.className).toContain("is-monogram");
    // Give any stray async resolution a chance to land, then assert it did not.
    await new Promise((r) => setTimeout(r, 20));
    expect((container.firstChild as HTMLElement).className).toContain("is-monogram");
    expect(container.querySelector("svg")).toBeNull();
  });
});

// A company page can list thousands of companies, and a shard is hundreds of
// kilobytes, so a mark loads its shard only once it comes near the screen.
describe("a mark from a shard waits until it nears the screen", () => {
  const observed: Element[] = [];
  let report: IntersectionObserverCallback = () => {};
  class Watcher {
    constructor(callback: IntersectionObserverCallback) {
      report = callback;
    }
    observe(element: Element) {
      observed.push(element);
    }
    unobserve(element: Element) {
      const at = observed.indexOf(element);
      if (at >= 0) observed.splice(at, 1);
    }
    disconnect() {
      observed.length = 0;
    }
  }
  const nearScreen = (element: Element) =>
    act(() => report([{ target: element, isIntersecting: true } as IntersectionObserverEntry], {} as IntersectionObserver));

  beforeEach(() => {
    __resetBrandIconCache();
    observed.length = 0;
    vi.stubGlobal("IntersectionObserver", Watcher);
  });
  afterEach(() => vi.unstubAllGlobals());

  it("shows the monogram until the mark nears the screen, then the mark", async () => {
    const { container } = render(<CompanyIcon slug="zoom" display="Zoom" />);
    const el = container.firstChild as HTMLElement;
    await new Promise((r) => setTimeout(r, 50));
    expect(el.className).toContain("is-monogram");
    expect(observed).toEqual([el]);

    nearScreen(el);
    await waitFor(() => expect(container.querySelector("svg path")?.getAttribute("d")?.length).toBeGreaterThan(10));
    expect((container.firstChild as HTMLElement).className).not.toContain("is-monogram");
    expect(observed).toEqual([]);
  });

  it("never watches a bundled mark or a company with no mark anywhere", () => {
    render(<CompanyIcon slug="netflix" display="Netflix" />);
    render(<CompanyIcon slug="amazon" display="Amazon" />);
    expect(observed).toEqual([]);
  });

  it("stops watching a mark that goes before it nears the screen", () => {
    const { unmount } = render(<CompanyIcon slug="zoom" display="Zoom" />);
    expect(observed).toHaveLength(1);
    unmount();
    expect(observed).toEqual([]);
  });
});

describe("brand icon data", () => {
  it("covers the catalog's best-known employers", () => {
    // A regeneration that silently dropped most matches would still leave a
    // non-empty table; name specific companies so that failure is visible.
    for (const slug of ["google", "apple", "netflix", "meta", "nvidia", "stripe", "figma"]) {
      expect(BRAND_ICONS[slug], slug).toBeDefined();
    }
    expect(Object.keys(BRAND_ICONS).length).toBeGreaterThan(60);
  });

  it("every entry carries a usable hex and a non-empty path", () => {
    for (const [slug, icon] of Object.entries(BRAND_ICONS)) {
      expect(icon.hex, slug).toMatch(/^#[0-9a-fA-F]{6}$/);
      expect(icon.path.length, slug).toBeGreaterThan(10);
    }
  });
});
