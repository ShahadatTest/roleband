/* The Settings shell: what is true on EVERY tab. Section index and tab
   navigation, and the cross-tab material facts (the ambient wash, one panel
   colour, one header height, one gutter) — each of which is only a fact
   because it holds across tabs, so none of them belongs to a tab's own file.
   The retired Pay data tab's address lives here too: it lands on Plugins. */

import { expect, test, type Page } from "./fixtures";
import { installSettingsRoutes } from "./settingsHarness";

test.beforeEach(async ({ page }) => {
  await installSettingsRoutes(page);
});

test("the section index redirects to the Companies tab", async ({ page }) => {
  // The scope surface lives under Profile; Settings opens on machinery.
  await page.goto("/settings");
  await expect(page).toHaveURL(/\/settings\/companies$/);
  await expect(page.getByRole("tab", { name: "Companies" })).toHaveAttribute("aria-selected", "true");
});

test("the tabs run from what RoleBand reads to the person's own data, Privacy last", async ({ page }) => {
  // Plugins is a data source, so it sits with what RoleBand reads, never
  // among the preferences.
  await page.goto("/settings/companies");
  await expect(page.getByRole("tab")).toHaveText([
    "Followed companies", "AI", "Schedule", "Plugins", "Recipes", "Language", "Data retention", "Privacy",
  ]);
});

test("every card on a kit tab and on AI is titled by a real h2 at one size", async ({ page }) => {
  // Measuring the `.intel-head-title` wrapper rather than the h2 inside it
  // reads AI's titles as a 15px/400 div. Pinned so the claim is checked rather
  // than re-audited. Companies is not here: its h2s are the register's sector
  // heads, a different rank.
  for (const [slug, first] of [
    ["intelligence", "Fit ranking"], ["schedule", "Scan clock"], ["plugins", "Plugins"],
    ["recipes", "Recipes"], ["language", "Language and region"], ["retention", "Data retention"],
    ["privacy", "Privacy"],
  ] as const) {
    await page.goto(`/settings/${slug}`);
    const titles = page.locator(".settings-content h2");
    await expect(titles.first(), slug).toHaveText(first);
    const type = await titles.evaluateAll((all) =>
      all.map((h) => `${getComputedStyle(h).fontSize}/${getComputedStyle(h).fontWeight}`));
    expect(type.length, slug).toBeGreaterThan(0);
    expect(new Set(type), `${slug}: ${type.join(", ")}`).toEqual(new Set(["18px/600"]));
  }
});

test("mounting while collapsed must not scroll the header away", async ({ page }) => {
  // A mount-time scrollIntoView on the active tab button runs against
  // whatever layout exists at mount. In a collapsed viewport (hidden
  // embedded pane, window mid-restore) the squeezed container clips the tab
  // button, "nearest" scrolls the PAGE container to reveal it, and the offset
  // survives the viewport growing back — the "Settings" header stays hidden.
  // Tab activation may only ever scroll the tabbar horizontally.
  await page.setViewportSize({ width: 500, height: 160 });
  await page.goto("/settings/schedule");
  await expect(page.getByRole("region", { name: "Schedule" })).toBeVisible();
  await page.setViewportSize({ width: 1280, height: 720 });
  await expect(page.getByRole("heading", { name: "Settings", exact: true })).toBeInViewport();
});

test("Pay data is gone: its old address lands on Plugins", async ({ page }) => {
  await page.goto("/settings/integrations");
  await expect(page).toHaveURL(/\/settings\/plugins$/);
  await expect(page.getByRole("tab", { name: "Plugins" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("tab", { name: "Pay data" })).toHaveCount(0);
});

test("switching tabs pushes, so Back returns to Companies", async ({ page }) => {
  await page.goto("/settings/companies");
  await page.getByRole("tab", { name: "AI" }).click();
  await expect(page).toHaveURL(/\/settings\/intelligence$/);
  await expect(page.getByRole("region", { name: "Fit ranking" })).toBeVisible();
  await page.goBack();
  await expect(page).toHaveURL(/\/settings\/companies$/);
});

test("the ambient wash covers every tab, and its imitators land on the same pixels", async ({ page }) => {
  // `body` paints two ambient washes for every route. The Settings scope
  // paints its own ground, which covers them, so it restates them in each
  // scope's own tokens, on every tab below.
  //
  // The hard part is not the wash, it is that this scope contains elements
  // whose whole job is to be indistinguishable from the page ground: Companies'
  // sticky column and sector headers (opaque, so rows vanish under them). A
  // gradient anchored with the default `scroll` resolves against each
  // ELEMENT's own box, so every one of those would land on different pixels
  // and read as a plate, and on the sticky headers the mismatch would SHIFT as
  // you scroll. `fixed` anchors every layer to the viewport instead, so the
  // ground and its imitators resolve identically by construction.
  //
  // Asserted on the COMPUTED value, because what matters is which rule wins
  // the cascade: a source read cannot tell a dead declaration from a live one.
  await page.setViewportSize({ width: 1280, height: 800 });

  const ground = async (path: string) => {
    await page.goto(path);
    await expect(page.locator(".settings-design-system")).toBeVisible();
    return page.evaluate(() => {
      const cs = getComputedStyle(document.querySelector(".settings-design-system") as HTMLElement);
      return { image: cs.backgroundImage, attachment: cs.backgroundAttachment };
    });
  };

  for (const path of [
    "/settings/companies",
    "/settings/intelligence",
    "/settings/plugins",
    "/settings/schedule",
  ]) {
    const g = await ground(path);
    expect(g.image, `${path} has no ambient wash`).toContain("radial-gradient");
    // Viewport-anchored, or the imitators below cannot possibly align.
    expect(g.attachment, `${path} is not viewport-anchored`).toBe("fixed, fixed");
  }

  // Companies: both sticky headers must be pixel-identical to the ground while
  // pinned, or a plate appears and slides.
  await page.goto("/settings/companies");
  await expect(page.getByRole("region", { name: "FAANG", exact: true })).toBeVisible();
  const register = await page.evaluate(() => {
    const scope = document.querySelector(".settings-design-system") as HTMLElement;
    scope.scrollTop = 400;
    const sig = (el: Element) => {
      const cs = getComputedStyle(el as HTMLElement);
      return `${cs.backgroundImage}|${cs.backgroundAttachment}|${cs.backgroundColor}`;
    };
    return {
      ground: sig(scope),
      colhead: sig(document.querySelector(".ledger-colhead")!),
      sectorHead: sig(document.querySelector(".ledger-sector-head")!),
    };
  });
  expect(register.colhead, "the sticky column header does not match the ground").toBe(register.ground);
  expect(register.sectorHead, "a sticky sector header does not match the ground").toBe(register.ground);

  // Intelligence's model-line button imitates nothing: it is a control resting
  // on its panel, and it must carry no ambient layer at all (canvas plus the
  // viewport-anchored wash would line it up with the ground and read as a hole
  // cut through the card). The panel comparison lives in the test below.
  //
  // Selected as `.ui-btn-ghost`, not by a screen-local name: asserting the
  // SHARED rank covers every screen that rests a ghost on a register panel.
  await page.goto("/settings/intelligence");
  await expect(page.locator(".ui-btn-ghost").first()).toBeVisible();
  const key = await page.evaluate(() => {
    const cs = getComputedStyle(document.querySelector(".ui-btn-ghost") as HTMLElement);
    return { image: cs.backgroundImage, color: cs.backgroundColor };
  });
  expect(key.image, "the button still paints the page's wash").toBe("none");
  expect(key.color, "the button is translucent, so the panel shows through it")
    .not.toMatch(/rgba?\([^)]*,\s*0?\.\d+\s*\)/);
});

/* What the EYE sees on a surface: the computed background colour with a flat
 * `linear-gradient(C, C)` layer composited over it.
 *
 * Settings reaches the same panel pixel by two different routes — the kit card
 * paints the canvas and lays the surface tint over it as a gradient (so the
 * page's light cannot shine through an opaque panel), while `.intel-card`
 * paints an already-opaque surface directly. Comparing `backgroundColor`
 * across them compares DECLARATIONS: it reports rgb(10,10,11) for a card that
 * renders rgb(17,17,18), which is how two panels could look identical to this
 * check while looking nothing alike on screen, and vice versa.
 *
 * Only a single-colour image layer is composited. A real gradient has no one
 * answer, so the base is returned rather than guessed at. */
async function renderedFills(page: Page, selector: string): Promise<string[]> {
  return page.evaluate((sel) => {
    const nums = (c: string) => (c.match(/[\d.]+/g) || []).map(Number);
    return [...document.querySelectorAll(sel)].map((el) => {
      const cs = getComputedStyle(el as HTMLElement);
      const base = nums(cs.backgroundColor);
      const stops = cs.backgroundImage.match(/rgba?\([^)]*\)/g) || [];
      if (!stops.length || new Set(stops).size !== 1) {
        return `rgb(${base.slice(0, 3).map(Math.round).join(", ")})`;
      }
      // The length guard above already proves this, but the union of a match
      // result with the `|| []` fallback does not carry that through — say it.
      const first = stops[0];
      if (first === undefined) return `rgb(${base.slice(0, 3).map(Math.round).join(", ")})`;
      const [r, g, b, a = 1] = nums(first);
      const over = [r, g, b].map((c, i) => Math.round(base[i] + a * (c - base[i])));
      return `rgb(${over.join(", ")})`;
    });
  }, selector);
}

test("a control nested in a panel is lighter than the panel, on every tab", async ({ page }) => {
  // A material that redefines `--app-surface` without moving the rest of the
  // surface ladder can leave `surface` sitting ABOVE `surface-subtle`: then no
  // step reads as raised over a panel, and the model-line button reaches past
  // the whole ladder to `--app-canvas` for its contrast, darker than the card
  // holding it while the same control one tab away is lighter than its card.
  //
  // Asserted as a STEP, not as pixels: the rule is "nested things come
  // forward", and it has to survive a repalette. The floor is 3 and not 0
  // because a sign alone is not the rule: a warm paper surface leaves
  // `surface-subtle` a luminance unit above it, which is lighter by
  // arithmetic and identical to the eye. The panel colours themselves are
  // pinned by the test below, which is where a colour change should fail.
  const RAISED_BY = 3;
  await page.addInitScript(() => localStorage.setItem("theme", "dark"));
  await page.setViewportSize({ width: 1280, height: 800 });
  const lum = (c: string) => {
    const [r, g, b] = (c.match(/\d+/g) || ["0", "0", "0"]).map(Number);
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };

  for (const [path, panelSel, controlSel] of [
    ["/settings/plugins", ".settings-card", ".ui-btn-ghost"],
    ["/settings/intelligence", ".intel-card", ".ui-btn-ghost"],
  ] as const) {
    await page.goto(path);
    await expect(page.locator(controlSel).first()).toBeVisible();
    const [panel] = await renderedFills(page, `.settings-content ${panelSel}`);
    const [control] = await renderedFills(page, `.settings-content ${controlSel}`);
    expect(
      lum(control) - lum(panel),
      `${path}: ${controlSel} (${control}) is not lighter than ${panelSel} (${panel})`,
    ).toBeGreaterThan(RAISED_BY);
  }
});

test("the selected tab wears the shell's tint on every tab; the register material stays inside its tab", async ({ page }) => {
  // The register material sets its tokens inside its tab, never on <body>:
  // there the tab bar's selected pill would go ink on Companies and AI and
  // gold on the other tabs, flipping with the tab. The tab bar is the shell's;
  // the material is the tab's.
  await page.addInitScript(() => localStorage.setItem("theme", "dark"));
  await page.setViewportSize({ width: 1280, height: 800 });
  const selected = async (path: string, name: string) => {
    await page.goto(path);
    const tab = page.getByRole("tab", { name });
    await expect(tab).toHaveAttribute("aria-selected", "true");
    return tab.evaluate((el) => [getComputedStyle(el).backgroundColor, getComputedStyle(el).color]);
  };
  const privacy = await selected("/settings/privacy", "Privacy");
  expect(await selected("/settings/companies", "Followed companies")).toEqual(privacy);
  expect(await selected("/settings/intelligence", "AI")).toEqual(privacy);

});

for (const theme of ["dark", "light"] as const) {
  test(`the action colour is the same on every tab, whatever material the tab wears (${theme})`, async ({ page }) => {
    // The register material must not restate the action set as ink, or Start,
    // links and focus rings turn white/black on Followed companies and AI and
    // gold on the other tabs. One accent, every tab.
    await page.addInitScript((t) => localStorage.setItem("theme", t), theme);
    await page.setViewportSize({ width: 1280, height: 800 });
    const accent = async (path: string) => {
      await page.goto(path);
      const content = page.locator(".settings-content").first();
      await expect(content).toBeVisible();
      return content.evaluate((el) => {
        const probe = document.createElement("span");
        probe.style.color = "var(--app-action)";
        probe.style.borderColor = "var(--app-action-ring)";
        el.appendChild(probe);
        const out = [getComputedStyle(probe).color, getComputedStyle(probe).borderTopColor];
        probe.remove();
        return out;
      });
    };
    const plugins = await accent("/settings/plugins");
    expect(await accent("/settings/companies")).toEqual(plugins);
    expect(await accent("/settings/intelligence")).toEqual(plugins);
    expect(plugins[0]).toBe(theme === "dark" ? "rgb(219, 203, 144)" : "rgb(138, 97, 15)");
  });
}

test("every Settings panel is the same colour, whatever material it wears", async ({ page }) => {
  // Companies and Intelligence wear `data-material="register"`; Plugins and
  // Schedule do not. The material exists so a plate can be OPAQUE (sticky
  // headers and dialog paper have to cover rows sliding under them); it must
  // not also make that plate a different COLOUR, warm paper against the
  // default material's cool composite, side by side under one tab bar.
  //
  // Pinned, not merely compared, so that re-tinting every panel together stays
  // a deliberate act rather than a drift that happens to keep them equal.
  await page.addInitScript(() => localStorage.setItem("theme", "dark"));
  await page.setViewportSize({ width: 1280, height: 800 });

  for (const path of [
    "/settings/intelligence",
    "/settings/plugins",
    "/settings/schedule",
  ]) {
    await page.goto(path);
    await expect(page.locator(".settings-card, .intel-card").first()).toBeVisible();
    const fills = await renderedFills(page, ".settings-content .settings-card, .settings-content .intel-card");
    expect(fills.length, `${path} rendered no panel`).toBeGreaterThan(0);
    for (const fill of fills) {
      expect(fill, `${path}: a panel is not the shared panel colour`).toBe("rgb(17, 17, 18)");
    }
  }
});

test("the wash sits behind the design, never through it", async ({ page }) => {
  // The wash is the PAGE's light, so a PANEL laid on the page must occlude it.
  // `--settings-surface` is a 2.8%-alpha tint — right for a control nested in a
  // panel, wrong for the panel itself: the beam shines straight THROUGH a
  // translucent panel, so it reads as lying on top of the design. Every panel
  // is a solid colour, as the ledger scope's surface is.
  //
  // Scoped to PANELS, not to "anything translucent". The Companies register
  // deliberately paints no card of its own, so its rows, switches and bars sit
  // directly on the page as tints — and a tint is supposed to let the page
  // through. Only a surface that FRAMES content has to be opaque.
  await page.setViewportSize({ width: 1280, height: 800 });

  const PANELS = ".settings-card, .settings-section, .intel-card";
  for (const path of [
    "/settings/companies",
    "/settings/intelligence",
    "/settings/plugins",
    "/settings/schedule",
  ]) {
    await page.goto(path);
    await expect(page.locator(".settings-design-system")).toBeVisible();
    const seeThrough = await page.evaluate((sel) => {
      const alpha = (c: string) => {
        const m = c.match(/[\d.]+/g);
        return m && m.length === 4 ? parseFloat(m[3]) : 1;
      };
      return [...document.querySelectorAll(`.settings-design-system ${sel}`)]
        .filter((el) => alpha(getComputedStyle(el as HTMLElement).backgroundColor) < 1)
        .map((el) => (el as HTMLElement).className.toString().split(" ").slice(0, 2).join("."));
    }, PANELS);
    expect(seeThrough, `${path}: a panel lets the page's light through it`).toEqual([]);
  }
});

test("the page header sits at one height on every tab", async ({ page }) => {
  // Switching tabs must not move the furniture. The ledger tabs (Companies,
  // Intelligence) zero the scroller's padding, and they MUST, because
  // `sticky; top: 0` pins to the content edge and any scroller padding opens a
  // band where rows stay visible above the pinned header. So the offset has one
  // source on every tab, the page head; a tab taking it from scroller padding
  // instead makes the h1 AND the tab bar under it jump on every switch.
  //
  // Measured through the real tab controls rather than separate page loads,
  // because the jump is something you see WHILE switching.
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/settings/companies");
  // Settings is a lazy route chunk, so the screen is not in the
  // document the instant the navigation resolves. Wait for the thing being
  // measured.
  await expect(page.locator(".settings-design-system .page-hero h1")).toBeVisible();

  const geometry = async () =>
    page.evaluate(() => {
      const main = document.querySelector(".settings-design-system") as HTMLElement;
      const head = main.querySelector(".page-hero") as HTMLElement;
      const bar = main.querySelector(".settings-tabbar") as HTMLElement;
      const h1 = head.querySelector("h1") as HTMLElement;
      return {
        h1Top: Math.round(h1.getBoundingClientRect().top),
        barTop: Math.round(bar.getBoundingClientRect().top),
      };
    });

  const baseline = await geometry();
  // Not a self-fulfilling comparison: pin the expected offset too, so a change
  // that moves every tab together still has to be deliberate. 44 (the top
  // bar) + 28 (the page header's own top air, `.main > .page-hero`, the same
  // on every tab of the rail: tests/ux/page-header.spec.ts).
  expect(baseline.h1Top).toBe(72);

  for (const label of ["AI", "Plugins", "Schedule", "Followed companies"]) {
    await page.getByRole("tab", { name: label }).click();
    await expect(page.getByRole("tab", { name: label })).toHaveAttribute("aria-selected", "true");
    expect(await geometry()).toEqual(baseline);
  }
});

test("every panelled Settings tab insets its panel by the same gutter", async ({ page }) => {
  // The panelled tabs present their screen as one panel laid on the page,
  // and a panel means one gutter: `.settings-card` (Plugins, Schedule) and
  // `.intel-card` (Intelligence) both pad by --app-space-5.
  //
  // Nothing in the markup shows a lost gutter. The legacy `.settings-section`'s
  // sealed `padding: 6px` ties on specificity with a section's own inset and
  // wins on source order alone (settings.css is bundled last), leaving the
  // content flush against its border while the panel is still the right
  // colour, the right radius and in the right place.
  //
  // Companies is excluded on purpose. Its register is a different material
  // (full-bleed rows, no panel), not a tab that forgot its pad.
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/settings/plugins");
  // Lazy route chunk: wait for the panel before measuring it.
  await expect(page.locator(".settings-content section h2").first()).toBeVisible();

  const panel = async () =>
    page.evaluate(() => {
      const content = document.querySelector(".settings-content") as HTMLElement;
      const section = content.querySelector("section") as HTMLElement;
      const heading = section.querySelector("h2") as HTMLElement;
      const box = section.getBoundingClientRect();
      const style = getComputedStyle(section);
      return {
        // Pinned as well as compared: a change that re-pads all three together
        // still has to be deliberate.
        padding: [style.paddingTop, style.paddingRight, style.paddingBottom, style.paddingLeft]
          .join(" "),
        // The gutter as the eye reads it — border included, and immune to a
        // panel that pads correctly while its heading carries an inset of its own.
        headingInset: Math.round(heading.getBoundingClientRect().left - box.left),
        // A panel may not buy its inset by shrinking away from the column.
        offsetInColumn: Math.round(box.left - content.getBoundingClientRect().left),
        width: Math.round(box.width),
      };
    });

  const baseline = await panel();
  expect(baseline.padding).toBe("28px 28px 28px 28px");
  expect(baseline.headingInset).toBe(29); // 28px gutter + the 1px hairline
  expect(baseline.offsetInColumn).toBe(0);

  for (const label of ["AI", "Schedule"]) {
    await page.getByRole("tab", { name: label }).click();
    await expect(page.getByRole("tab", { name: label })).toHaveAttribute("aria-selected", "true");
    await expect(page.locator(".settings-content section h2").first()).toBeVisible();
    expect(await panel(), `${label} panel is inset differently`).toEqual(baseline);
  }
});

test("settings uses a horizontal section menu; the persona rail never renders here", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/settings/companies");

  // Horizontal tabbar above the content (the app-wide menu concept).
  const navBox = await page.getByRole("tablist", { name: "Settings sections" }).boundingBox();
  const panelBox = await page.getByRole("tabpanel").boundingBox();
  expect((navBox?.y ?? 0) + (navBox?.height ?? 0)).toBeLessThanOrEqual((panelBox?.y ?? 1) + 1);
  expect(navBox?.height ?? 999).toBeLessThan(80);

  // The persona rail lives in Profile › Direction with the scope surface:
  // no Settings tab may render it.
  for (const section of ["companies", "intelligence", "plugins", "schedule"]) {
    await page.goto(`/settings/${section}`);
    await expect(page.getByRole("complementary", { name: "Your radar" })).toHaveCount(0);
  }
});

for (const theme of ["dark", "light"] as const) {
  test(`a switch that is on looks the same on every tab, whatever material the tab wears (${theme})`, async ({ page }) => {
    // A switch shows a state, not an action, so it does not take the action
    // colour: whichever material the tab wears, one control has one look, and
    // it is ink everywhere.
    await page.addInitScript((t) => localStorage.setItem("theme", t), theme);
    await page.setViewportSize({ width: 1280, height: 800 });
    const on = async (path: string) => {
      await page.goto(path);
      const track = page.locator(".ui-switch-track:checked").first();
      await expect(track).toBeVisible();
      return track.evaluate((el) => getComputedStyle(el).backgroundColor);
    };
    const register = await on("/settings/companies");
    expect(await on("/settings/plugins")).toBe(register);
    expect(register).toBe(theme === "dark" ? "rgb(236, 234, 228)" : "rgb(27, 26, 22)");
  });
}

test("a card below 640px is inset 20px on every side", async ({ page }) => {
  // Fail-first: the narrow override padded a card 14/14/20, off the rule's
  // one narrow step (docs/ui.md: space-4 for any card below 640px).
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/settings/plugins");
  const card = page.locator(".settings-content .settings-card").first();
  await expect(card).toBeVisible();
  const inset = await card.evaluate((el) => {
    const style = getComputedStyle(el);
    return [style.paddingTop, style.paddingRight, style.paddingBottom, style.paddingLeft];
  });
  expect(inset).toEqual(["20px", "20px", "20px", "20px"]);
});
