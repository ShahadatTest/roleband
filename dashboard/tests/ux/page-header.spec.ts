import { expect, test } from "./fixtures";
import { installEveryRoute } from "./routesHarness";

/* ONE PAGE HEADER. Every tab of the rail names itself with the same h1, at the
   same height and the same left edge, so switching tabs moves nothing but the
   content. Measured through the rail, the way a jump is seen. */

const TABS = [
  { rail: "Radar", path: "/" },
  { rail: "Saved", path: "/favorites" },
  { rail: "Profile", path: "/profile" },
  { rail: "Insights", path: "/statistics" },
  { rail: "Companies", path: "/company" },
  { rail: "Duplicates", path: "/review" },
  { rail: "Notifications", path: "/notifications" },
  { rail: "Settings", path: "/settings" },
];

test.beforeEach(async ({ page }) => {
  await installEveryRoute(page);
});

test("every tab's title is its rail label, in one place, at one size", async ({ page, isMobile }) => {
  test.slow();
  // 1440 on a desktop: wide enough that a screen capping its content at the
  // app's 1200 measure centres it, and its title drifts right of the others.
  if (!isMobile) await page.setViewportSize({ width: 1440, height: 900 });
  const seen: string[] = [];
  for (const tab of TABS) {
    await page.goto(tab.path);
    const title = page.getByRole("main").first().getByRole("heading", { level: 1 });
    await expect(title).toHaveText(tab.rail);
    await expect(title).toBeVisible();
    // One h1 per screen: a panel's own title is an h2 under it.
    await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
    seen.push(`${tab.rail}: ${await title.evaluate((node) => {
      const box = node.getBoundingClientRect();
      const style = getComputedStyle(node);
      return `${Math.round(box.top)}/${Math.round(box.left)} ${style.fontSize}/${style.fontWeight}`;
    })}`);
  }
  const places = new Set(seen.map((line) => line.split(": ")[1]));
  expect(places.size, seen.join("\n")).toBe(1);
});

/* ONE TAB ROW. The screens whose parts are ui/TabBar show it the same way:
   the tabs at one height and one left edge under the title, the content 20px
   below them, and NO line in between. The tabs are filled pills and need no
   baseline: a line under the row, above a panel's own border, reads as two
   lines. Duplicates wears a band only while its row is pinned, which a
   second test scrolls to. */
const TABBED = [
  { rail: "Profile", path: "/profile" },
  { rail: "Insights", path: "/statistics" },
  { rail: "Duplicates", path: "/review" },
  { rail: "Settings", path: "/settings" },
];

test("every tab row sits in one place, with the content 20px below and no line between", async ({ page, isMobile }) => {
  test.skip(isMobile, "the rows scroll sideways on a phone; one desktop geometry is the claim");
  await page.setViewportSize({ width: 1440, height: 900 });
  const seen: string[] = [];
  for (const tab of TABBED) {
    await page.goto(tab.path);
    const tabs = page.getByRole("main").first().getByRole("tablist").first();
    await expect(tabs).toBeVisible();
    const measured = await tabs.evaluate((bar) => {
      const row = bar.getBoundingClientRect();
      const main = bar.closest("main")!;
      // The content: the highest PAINTED box below the tab row (its own
      // text, a border or a fill), not a layout wrapper around it. A fill in
      // the page's own canvas is not paint: it is how a sticky toolbar
      // (Settings' search row) covers what scrolls under it, unseen at rest.
      const probe = document.createElement("div");
      probe.style.background = "var(--app-canvas)";
      main.append(probe);
      const canvas = getComputedStyle(probe).backgroundColor;
      probe.remove();
      const painted = (node: HTMLElement) => {
        const style = getComputedStyle(node);
        const text = [...node.childNodes].some((child) => child.nodeType === 3 && child.textContent!.trim() !== "");
        const border = ["top", "right", "bottom", "left"].some((side) => parseFloat(style.getPropertyValue(`border-${side}-width`)) > 0 && style.getPropertyValue(`border-${side}-style`) !== "none");
        const fill = !/rgba\(.*, 0\)$|transparent/.test(style.backgroundColor) && style.backgroundColor !== canvas;
        return text || border || fill;
      };
      let contentTop = Infinity;
      for (const node of main.querySelectorAll<HTMLElement>("*")) {
        if (node.contains(bar) || bar.contains(node)) continue;
        const box = node.getBoundingClientRect();
        if (box.height > 0 && box.width > 0 && box.top >= row.bottom - 0.5 && painted(node)) contentTop = Math.min(contentTop, box.top);
      }
      // A line in the gap: a painted top or bottom border on a wide element.
      const lines: string[] = [];
      for (const node of main.querySelectorAll<HTMLElement>("*")) {
        const style = getComputedStyle(node);
        const box = node.getBoundingClientRect();
        if (box.width < main.clientWidth / 3) continue;
        for (const [side, y] of [["bottom", box.bottom], ["top", box.top]] as const) {
          const width = parseFloat(style.getPropertyValue(`border-${side}-width`));
          const painted = width > 0 && style.getPropertyValue(`border-${side}-style`) !== "none" && !/rgba\(.*, 0\)$|transparent/.test(style.getPropertyValue(`border-${side}-color`));
          if (painted && y > row.bottom + 0.5 && y < contentTop - 0.5) lines.push(`${node.className} ${side}@${Math.round(y)}`);
        }
      }
      return { top: Math.round(row.top), left: Math.round(row.left), gap: Math.round(contentTop - row.bottom), lines };
    });
    seen.push(`${tab.rail}: ${measured.top}/${measured.left} gap ${measured.gap}${measured.lines.length ? ` lines ${measured.lines.join(", ")}` : ""}`);
  }
  const report = seen.join("\n");
  expect(new Set(seen.map((line) => line.split(": ")[1])).size, report).toBe(1);
  expect(report).toContain("gap 20");
  expect(report).not.toContain("lines");
});

test("the Duplicates tab row takes a surface only while it is pinned", async ({ page, isMobile }) => {
  test.skip(isMobile, "one geometry");
  await page.setViewportSize({ width: 1280, height: 420 });
  await page.goto("/review");
  const toolbar = page.locator(".review-toolbar");
  await expect(page.getByRole("tablist", { name: "Duplicate review views" })).toBeVisible();
  const band = () => toolbar.evaluate((node) => getComputedStyle(node, "::before").opacity);
  await expect(toolbar).not.toHaveAttribute("data-stuck");
  expect(await band()).toBe("0");
  // The fixture queue is one pair, too short to scroll: give the page room,
  // then scroll it, so the row pins as it does over a real queue.
  await page.locator(".review").evaluate((review) => {
    const room = document.createElement("div");
    room.style.height = "2000px";
    review.append(room);
  });
  await page.getByRole("main").first().evaluate((main) => main.scrollTo({ top: 400 }));
  await expect(toolbar).toHaveAttribute("data-stuck", "true");
  await expect.poll(band).toBe("1");
});

/* Saved's header must not take the Board's wide measure while its count and
   list keep the app's centred 1200 (at 1440 the header rule would run
   115..1397 over content starting at 156). The page is one measure; the list keeps the
   Board's beacon margin inside it, as on the Board. */
test("Saved's header, count and list share the page's edges", async ({ page, isMobile }) => {
  test.skip(isMobile, "one column on a phone; the drift is a wide-screen measure");
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/favorites");
  const main = page.getByRole("main").first();
  await expect(main.getByRole("heading", { level: 1, name: "Saved" })).toBeVisible();
  await expect(main.locator(".results-head")).toBeVisible();
  const edges = await main.evaluate((root) =>
    [...root.children].map((child) => {
      const box = child.getBoundingClientRect();
      return `${child.className.toString().split(" ")[0]} ${Math.round(box.left)}..${Math.round(box.right)}`;
    }),
  );
  const spans = new Set(edges.map((line) => line.split(" ")[1]));
  expect(spans.size, edges.join("\n")).toBe(1);
});
