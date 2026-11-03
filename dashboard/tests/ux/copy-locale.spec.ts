import { expect, test, type Page } from "./fixtures";
import { unbracketed } from "./pseudoScan";
import { installEveryRoute } from "./routesHarness";
import { msg } from "../../src/test/msg";

/* Languages, switched live (docs/copy.md, section 6).
 *
 * A switch remounts the UI below the data providers: no reload, the URL kept,
 * the account's choice saved. A stored choice paints first; the account's
 * choice wins over the device's. The pseudo locale (`en-XA`, listed only with
 * the copy-check flag) brackets every catalog message, so text that is not in
 * the catalog, or that a switch left behind, shows unbracketed. */

// By its class: the rail's accessible name is translated too.
const nav = (page: Page) => page.locator("nav.nav-rail");
const ES = { language: "es", region: null };

async function locale(page: Page, saved: { language: string; region: string | null }) {
  const puts: unknown[] = [];
  await page.route("/api/settings/locale", (route) => {
    if (route.request().method() === "PUT") {
      const body = route.request().postDataJSON();
      puts.push(body);
      saved = body;
      return route.fulfill({ json: body });
    }
    return route.fulfill({ json: saved });
  });
  return puts;
}

test.describe("switching language", () => {
  test("changes the app in place from Settings, saves it, and keeps the page", async ({ page }) => {
    await installEveryRoute(page);
    const puts = await locale(page, { language: "en", region: null });
    await page.goto("/settings/language");
    await expect(nav(page).getByRole("link", { name: msg("shell-nav-radar") })).toBeVisible();
    // A reload would drop this; a remount keeps the window.
    await page.evaluate(() => ((window as unknown as { __kept: number }).__kept = 1));

    await page.getByRole("combobox", { name: msg("settings-language-label") }).selectOption("es");

    await expect(nav(page).getByRole("link", { name: "Guardados" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Idioma" })).toBeVisible();
    await expect(page.getByRole("combobox", { name: "Idioma" })).toHaveValue("es");
    expect(puts).toEqual([ES]);
    await expect(page).toHaveURL(/\/settings\/language$/);
    await expect(page.locator("html")).toHaveAttribute("lang", "es");
    expect(await page.evaluate(() => (window as unknown as { __kept?: number }).__kept)).toBe(1);

    // On to Chinese, in place again.
    await page.getByRole("combobox", { name: "Idioma" }).selectOption("zh-Hans");
    await expect(nav(page).getByRole("link", { name: "已保存" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "语言" })).toBeVisible();
    await expect(page.locator("html")).toHaveAttribute("lang", "zh-Hans");

    await page.getByRole("combobox", { name: "语言" }).selectOption("en");
    await expect(nav(page).getByRole("link", { name: msg("shell-nav-saved") })).toBeVisible();
    await expect(page.locator("html")).toHaveAttribute("lang", "en");
    expect(puts).toEqual([ES, { language: "zh-Hans", region: null }, { language: "en", region: null }]);
  });

  test("a region changes how numbers and dates are written, not the words", async ({ page }) => {
    await installEveryRoute(page);
    const puts = await locale(page, { language: "en", region: null });
    await page.goto("/settings/language");
    const region = page.getByRole("combobox", { name: msg("settings-region-label") });
    await region.selectOption("es-ES");
    // The words stay English; the sample is written the Spanish way.
    const lead = msg("settings-region-description", { number: "1234,5", date: "\u0000" }).split("\u0000")[0];
    await expect(page.getByText(new RegExp(`^${lead.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`))).toBeVisible();
    await expect(nav(page).getByRole("link", { name: msg("shell-nav-radar") })).toBeVisible();
    expect(puts).toEqual([{ language: "en", region: "es-ES" }]);
  });

  test("the account's choice wins over this device's memory, and is remembered for the next first paint", async ({ page }) => {
    await installEveryRoute(page);
    await locale(page, ES);
    // This device last chose English; the account says Spanish.
    await page.addInitScript(() => localStorage.setItem("roleband.locale", JSON.stringify({ language: "en", region: null })));
    await page.goto("/favorites");
    await expect(nav(page).getByRole("link", { name: "Guardados" })).toBeVisible();
    expect(await page.evaluate(() => localStorage.getItem("roleband.locale"))).toBe(JSON.stringify(ES));
  });
});

test.describe("the pseudo locale", () => {
  const ROUTES = ["/", "/favorites", "/profile", "/statistics", "/company", "/review", "/notifications", "/settings"];
  // Screens whose copy is all in the catalog: their scan below is blocking,
  // not a report. Every route; a new route joins as it ships.
  const MIGRATED = ROUTES;

  test("is listed only with the copy-check flag, and never saved for the account", async ({ page }) => {
    await installEveryRoute(page);
    const puts = await locale(page, { language: "en", region: null });
    await page.goto("/settings/language");
    const language = page.getByRole("combobox", { name: msg("settings-language-label") });
    await expect(language.locator("option[value='en-XA']")).toHaveCount(0);

    await page.evaluate(() => localStorage.setItem("roleband.copy-check", "1"));
    await page.reload();
    await page.getByRole("combobox", { name: msg("settings-language-label") }).selectOption("en-XA");
    await expect(nav(page).getByRole("link", { name: /^⟦Ŕàðàŕ/ })).toBeVisible();
    expect(puts).toEqual([]);
  });

  test("after a live switch, the shell and every migrated message are bracketed on every route (the rest is reported)", async ({ page }, info) => {
    await installEveryRoute(page);
    await locale(page, { language: "en", region: null });
    await page.addInitScript(() => localStorage.setItem("roleband.copy-check", "1"));
    await page.goto("/settings/language");
    await page.getByRole("combobox", { name: msg("settings-language-label") }).selectOption("en-XA");

    const links = await nav(page).getByRole("link").count();
    expect(links).toBeGreaterThanOrEqual(ROUTES.length - 1);
    for (let i = 0; i < links; i++) {
      // The nav, clicked: client-side, so this is the switched app, not a fresh boot.
      await nav(page).getByRole("link").nth(i).click();
      await expect(page.locator("main h1, [role='main'] h1, h1").first()).toBeVisible();
      await page.waitForLoadState("networkidle");
      const route = new URL(page.url()).pathname;
      const scan = await page.evaluate(() => {
        const navNames = [...document.querySelectorAll('nav[aria-label="Primary"] a')].map(
          (a) => a.getAttribute("aria-label") ?? a.textContent ?? "",
        );
        let plain = 0;
        let bracketed = 0;
        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
        for (let n = walker.nextNode(); n; n = walker.nextNode()) {
          const text = (n.textContent ?? "").trim();
          const el = n.parentElement;
          if (!text || !/\p{L}/u.test(text) || !el?.offsetParent || el.closest("[data-copy]")) continue;
          if (text.includes("⟦")) bracketed++;
          else plain++;
        }
        return { navNames, plain, bracketed };
      });
      // Blocking: what is in the catalog shows the switch, on every route.
      for (const name of scan.navNames) expect(name, `${route}: ${name}`).toMatch(/^⟦/);
      // Blocking: the shell (rail and top bar) is all catalog, so
      // nothing in it, text or accessible name, may be left unbracketed.
      const shellPlain = await page.evaluate(() => {
        const out: string[] = [];
        for (const root of document.querySelectorAll(".nav-rail, .topbar")) {
          const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
          for (let n = walker.nextNode(); n; n = walker.nextNode()) {
            const text = (n.textContent ?? "").trim();
            const el = n.parentElement;
            if (!text || !/\p{L}/u.test(text) || !el || el.closest("[aria-hidden='true'], [data-copy]") || text.includes("⟦")) continue;
            out.push(text);
          }
          for (const el of root.querySelectorAll("[aria-label], [title]")) {
            for (const attr of ["aria-label", "title"]) {
              const value = el.getAttribute(attr);
              if (value && /\p{L}/u.test(value) && !value.includes("⟦")) out.push(`${attr}=${value}`);
            }
          }
        }
        return out;
      });
      expect(shellPlain, `${route}: shell text not from the catalog`).toEqual([]);
      // Blocking on a migrated screen (docs/copy.md): the whole
      // screen is catalog, third-party text is marked by ui/Content, and a
      // formatted figure ($650K, 12%) is the format module's, not a message.
      if (MIGRATED.includes(route)) {
        const screenPlain = await unbracketed(page);
        expect(screenPlain, `${route}: text not from the catalog on a migrated screen`).toEqual([]);
      }
      // Reported: text not in the catalog yet, which migrating a screen takes to zero.
      info.annotations.push({ type: "unbracketed text", description: `${route}: ${scan.plain} plain, ${scan.bracketed} bracketed` });
    }
  });
});

test.describe("locale ordering and requested choices", () => {
  test.use({locale:"en-US"});
  test("automatic and equivalent explicit region settle without freezing controls", async ({page}) => {
    await installEveryRoute(page);
    const puts=await locale(page,{language:"en",region:null});
    await page.goto("/settings/language");
    const region=page.getByRole("combobox",{name:msg("settings-region-label")});
    const language=page.getByRole("combobox",{name:msg("settings-language-label")});
    await region.selectOption("en-US");
    await expect(region).toBeEnabled();await expect(region).toHaveValue("en-US");
    await expect(language).toBeEnabled();
    await region.selectOption("system");
    await expect(region).toBeEnabled();await expect(region).toHaveValue("system");
    await language.selectOption("es");
    await expect(nav(page).getByRole("link",{name:"Guardados"})).toBeVisible();
    expect(puts.slice(0,2)).toEqual([{language:"en",region:"en-US"},{language:"en",region:null}]);
  });
  test("a delayed boot read cannot undo a later user save", async ({page}) => {
    await installEveryRoute(page);
    let release!:()=>void;const pending=new Promise<void>(resolve=>{release=resolve;});
    const puts:unknown[]=[];
    await page.route("/api/settings/locale",async route=>{
      if(route.request().method()==="PUT") { const body=route.request().postDataJSON();puts.push(body);await route.fulfill({json:body}); }
      else { await pending;await route.fulfill({json:{language:"en",region:null}}); }
    });
    await page.goto("/settings/language");
    await page.getByRole("combobox",{name:msg("settings-language-label")}).selectOption("es");
    await expect(nav(page).getByRole("link",{name:"Guardados"})).toBeVisible();
    release();
    await expect.poll(()=>page.evaluate(()=>JSON.parse(localStorage.getItem("roleband.locale")!).language)).toBe("es");
    await expect(page.getByRole("combobox",{name:"Idioma"})).toHaveValue("es");
    expect(puts).toEqual([{language:"es",region:null}]);
  });
  test("bad stored regions and rejected saves keep the page usable", async ({page}) => {
    await installEveryRoute(page);
    await page.addInitScript(()=>localStorage.setItem("roleband.locale",JSON.stringify({language:"en",region:"en-12-34"})));
    await page.route("/api/settings/locale",route=>route.fulfill(route.request().method()==="PUT"?{status:503,json:{detail:{code:"server"}}}:{json:{language:"en",region:null}}));
    await page.goto("/settings/language");
    const language=page.getByRole("combobox",{name:msg("settings-language-label")});
    await language.selectOption("es");
    await expect(page.getByRole("alert")).toHaveText(msg("settings-save-failed"));
    await expect(language).toBeEnabled();await expect(language).toHaveValue("en");
    await expect(page.getByRole("combobox",{name:msg("settings-region-label")})).toBeEnabled();
  });
});
