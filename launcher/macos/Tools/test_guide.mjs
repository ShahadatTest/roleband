import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve, dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { createRequire } from "node:module";
import { execFileSync } from "node:child_process";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const require = createRequire(join(root, "dashboard/package.json"));
const { chromium, webkit } = require("@playwright/test");
const work = await mkdtemp(join(tmpdir(), "roleband-guide-test-"));
const output = join(work, "site");
execFileSync("python3", [join(root, "launcher/macos/Tools/install_guide.py"), output]);
const url = pathToFileURL(join(output, "index.html")).href;
try {
  for (const [name, engine] of [["chromium", chromium], ["webkit", webkit]]) {
    const browser = await engine.launch({ headless: true });
    try {
      const context = await browser.newContext({ offline: true });
      const page = await context.newPage();
      const errors = [];
      page.on("pageerror", error => errors.push(error.message));
      const heading = title => page.getByRole("heading", { name: title, exact: true });
      await page.goto(url);
      await heading("Install the app").waitFor();
      assert.equal(await page.locator("section:visible").count(), 1);
      assert.equal(await page.getByRole("button", { name: "Back", exact: true }).isVisible(), false);
      await page.getByRole("button", { name: "I copied it" }).click();
      await heading("Open the installed app").waitFor();
      await page.getByRole("combobox").selectOption("es");
      await heading("Abre la app instalada").waitFor();
      assert.equal(await page.locator("html").getAttribute("lang"), "es");
      await page.reload();
      await heading("Abre la app instalada").waitFor();
      await page.getByRole("combobox").selectOption("en");
      await page.getByRole("button", { name: "My app opened" }).click();
      await heading("Continue in RoleBand").waitFor();
      await page.getByRole("button", { name: "Back", exact: true }).click();
      await heading("Open the installed app").waitFor();
      await page.getByRole("button", { name: "I'm seeing this" }).click();
      await heading("Allow the first open").waitFor();
      assert.equal(await page.getByRole("link", { name: "Open security settings" }).getAttribute("href"),
        "x-apple.systempreferences:com.apple.preference.security");
      await page.getByText("No approval button?", { exact: true }).click();
      assert.equal(await page.getByText(/Try to open the installed app again/).isVisible(), true);
      await page.getByRole("combobox").selectOption("zh-Hans");
      await heading("允许首次打开").waitFor();
      assert.equal(await page.getByRole("link", { name: "打开安全设置" }).count(), 1);
      await page.getByRole("combobox").selectOption("en");
      await page.getByRole("button", { name: "I allowed it" }).click();
      await page.getByRole("button", { name: "Setup is open" }).click();
      assert.equal(await page.getByRole("status").textContent(), "Continue in the app. You can close this guide.");
      assert.equal(await page.getByRole("button", { name: "Setup is open" }).isVisible(), false);
      await page.goto(url + "#unknown/not-a-step");
      await heading("Install the app").waitFor();
      await page.getByRole("button", { name: "I copied it" }).focus();
      await page.keyboard.press("Enter");
      await heading("Open the installed app").waitFor();
      for (const locale of ["en", "es", "zh-Hans"]) {
        for (const step of ["copy", "open", "approve", "setup"]) {
          await page.goto(url + "#" + locale + "/" + step);
          const actions = page.locator("section:visible .actions").last();
          const primary = await actions.locator(".primary").boundingBox();
          const row = await actions.boundingBox();
          assert.ok(Math.abs(primary.x + primary.width - row.x - row.width) < 1,
            `${name} ${locale} ${step}: primary action must be on the right`);
          const secondary = actions.locator(".secondary");
          if (await secondary.count()) {
            const other = await secondary.boundingBox();
            assert.ok(other.x + other.width <= primary.x, "Secondary action precedes primary visually");
            assert.equal(await actions.locator(":scope > :first-child").getAttribute("class"), "flow-action secondary",
              "Keyboard order follows visual order");
          }
        }
      }
      for (const theme of ["light", "dark"]) {
        await page.emulateMedia({ colorScheme: theme, reducedMotion: "reduce" });
        await page.setViewportSize({ width: 375, height: 812 });
        for (const step of ["copy", "open", "approve", "setup"]) {
          await page.goto(url + "#es/" + step);
          assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, `${name} ${theme} ${step} overflows`);
        }
      }
      assert.equal(await page.locator("img").evaluateAll(images => images.every(image => image.complete && image.naturalWidth > 0)), true);
      assert.deepEqual(errors, []);
      await context.close();
      const noScript = await browser.newContext({ javaScriptEnabled: false, offline: true });
      const plain = await noScript.newPage();
      await plain.goto(url);
      assert.equal(await plain.locator("section:visible").count(), 4);
      await plain.getByRole("link", { name: "Español", exact: true }).click();
      await plain.getByRole("heading", { name: "Instala la app", exact: true }).waitFor();
      await noScript.close();
      console.log(`${name}: offline guide navigation, language, branches, keyboard, responsive themes and no-JavaScript fallback passed`);
    } finally { await browser.close(); }
  }
} finally { await rm(work, { recursive: true, force: true }); }
