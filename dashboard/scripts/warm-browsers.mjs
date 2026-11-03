// Opens a first page in each browser playwright.config.ts uses, with that
// project's device, and prints how long each step took.
//
// On a fresh CI runner the first page a browser opens can take tens of seconds
// (WebKit worst), and the suite would otherwise bill that to whichever test
// opened it, inside its 30 s budget. Run before the suite, this pays the
// machine's one-time cost outside any test and leaves the number in the log.
import { chromium, devices, webkit } from "@playwright/test";

const browsers = [
  ["chromium", chromium, devices["Desktop Chrome"]],
  ["webkit", webkit, devices["iPhone 14"]],
];

for (const [name, type, device] of browsers) {
  const started = Date.now();
  const browser = await type.launch();
  const launched = Date.now();
  const context = await browser.newContext(device);
  const page = await context.newPage();
  const opened = Date.now();
  await page.setContent("<p style=\"font-family: sans-serif\">RoleBand ñ 你好</p>");
  const painted = Date.now();
  await browser.close();
  console.log(`${name}: launch ${launched - started} ms, first page ${opened - launched} ms, first content ${painted - opened} ms`);
}
