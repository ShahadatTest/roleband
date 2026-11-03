/* The Intelligence tab: where each capability runs, the matching-tier field,
   and the switch/setup flows for assistants, your own model and online
   services. The switch tests carry the confirm/cancel workflow. */

import { expect, mockApi, mockGet, test } from "./fixtures";
import type { CloudLLMState, LocalLLMState, LocalLLMTestResult, LocalServerControlResult, LocalServerStatus } from "../../src/api";
import {
  cloudModelProfileFixture,
  jobFixture,
  jobListFixture,
  localModelStateFixture,
  localModelTestResultFixture,
  localServerStatusFixture,
} from "../../src/test/fixtures";
import { installSettingsRoutes, intelligence, intelligenceFit, otherLocalModelProfile } from "./settingsHarness";
import { msg } from "../../src/test/msg";

test.beforeEach(async ({ page }) => {
  await installSettingsRoutes(page);
});

test("intelligence states where each capability runs, up front", async ({ page }) => {
  await page.goto("/settings/intelligence");

  // Three cards, each an instrument — no Advanced drawer, no Experimental pen.
  const ranking = page.getByRole("region", { name: "Fit ranking" });
  const assistants = page.getByRole("region", { name: "MCP server" });
  const capabilities = page.getByRole("region", { name: "Extended capabilities" });
  await expect(ranking).toBeVisible();
  await expect(assistants).toBeVisible();
  await expect(capabilities).toBeVisible();
  await expect(page.getByText("Advanced", { exact: true })).toHaveCount(0);

  // Origin is a label on the card, not a discovery at the bottom of the page.
  await expect(ranking.getByText("On this computer")).toBeVisible();
  await expect(assistants.getByText("Cloud-connected")).toBeVisible();
  // The header states the direction of travel; the recipients are named on the
  // tiles, so the header does not date itself when a third client appears.
  await expect(assistants.getByText(/Anthropic, OpenAI/)).toHaveCount(0);
});

test("the field puts the selected roles on top, named beside it", async ({ page }) => {
  await page.route("/api/jobs?**", (route) => route.fulfill({
    json: {
      ...jobListFixture,
      ranked_by: "intent",
      items: jobListFixture.items.slice(0, 2),
    },
  }));
  await page.goto("/settings/intelligence");

  const ranking = page.getByRole("region", { name: "Fit ranking" });
  await expect(ranking.getByText(/1,410 open roles, ranked by how well they fit/)).toBeVisible();
  await expect(ranking.getByText("leadership in AI/frontier tech")).toBeVisible();
  // The instrument itself, with its band counts readable to assistive tech.
  await expect(ranking.getByRole("group", { name: /Strong 62/ })).toBeVisible();
  await expect(ranking.getByText("Preview")).toBeVisible();
  await expect(ranking.getByText(/your best fits/)).toBeVisible();

  // The selected roles link to the roles themselves.
  const first = ranking.getByRole("link", { name: jobListFixture.items[0].title });
  await expect(first).toBeVisible();
});

test("the aim sentence is edited on the ranking card and saves alone", async ({ page }) => {
  let written: unknown = null;
  await mockApi(page, "PUT", "/api/settings/intent", async (route) => {
    written = route.request().postDataJSON();
    await route.fulfill({ json: { intent_statement: "Staff infrastructure leadership" } });
  });
  // The ranking answers with whatever sentence is SAVED, as the server does.
  // Answering by read count (first read old, later reads new) breaks under
  // the dev server's StrictMode: effects run twice on mount there, so the
  // second mount read would already serve the new sentence.
  let fitReads = 0;
  await page.unroute("/api/intelligence/fit");
  await mockGet(page, "/api/intelligence/fit", (route) => {
    fitReads += 1;
    return route.fulfill({
      json: written === null
        ? intelligenceFit
        : { ...intelligenceFit, intent_statement: "Staff infrastructure leadership" },
    });
  });
  await page.goto("/settings/intelligence");

  const ranking = page.getByRole("region", { name: "Fit ranking" });
  await expect(ranking.getByText("leadership in AI/frontier tech")).toBeVisible();
  await expect(ranking.getByRole("link", { name: /Direction/ })).toHaveCount(0);

  await ranking.getByRole("button", { name: "Edit your aim" }).click();
  const input = ranking.getByLabel("Your aim, in one sentence");
  await expect(input).toBeFocused();
  await input.fill("Staff infrastructure leadership");
  const readsBeforeSave = fitReads;
  await ranking.getByRole("button", { name: "Save" }).click();

  await expect.poll(() => written).toEqual({ intent_statement: "Staff infrastructure leadership" });
  await expect(ranking.getByText("Staff infrastructure leadership")).toBeVisible();
  await expect(ranking.getByRole("button", { name: "Edit your aim" })).toBeFocused();
  // A new sentence re-ranks every role: the save reads the ranking again.
  expect(fitReads).toBeGreaterThan(readsBeforeSave);
});

test("clicking a band of the field previews that band's roles; clicking again goes back", async ({ page }) => {
  await page.route("/api/jobs?**", (route) => route.fulfill({
    json: { ...jobListFixture, ranked_by: "intent", items: jobListFixture.items.slice(0, 2) },
  }));
  await page.route("/api/intelligence/fit/band/weak**", (route) => route.fulfill({
    json: {
      band: "weak",
      items: [{ ...jobFixture, id: 909, title: "Regional Retail Ops Lead", company: "meta" }],
    },
  }));
  await page.goto("/settings/intelligence");

  const ranking = page.getByRole("region", { name: "Fit ranking" });
  const weak = ranking.getByRole("button", { name: "Weak: 492 roles" });
  await expect(weak).toHaveAttribute("aria-pressed", "false");

  // Click: the preview swaps to the band's sample and names the pool it drew from.
  await weak.click();
  await expect(weak).toHaveAttribute("aria-pressed", "true");
  await expect(ranking.getByText(/the strongest of Weak · 492 roles/)).toBeVisible();
  await expect(ranking.getByRole("link", { name: "Regional Retail Ops Lead" })).toBeVisible();
  await expect(ranking.getByText(/\+491 more/)).toBeVisible();

  // Click again: back to the best matches.
  await weak.click();
  await expect(ranking.getByText(/your best fits/)).toBeVisible();
  await expect(ranking.getByRole("link", { name: jobListFixture.items[0].title })).toBeVisible();
});

test("a switch is never one click: the confirm states the trade, the cost and the way back", async ({ page }) => {
  let tierWrite: unknown = null;
  await page.route("/api/intelligence/matching/tier", async (route) => {
    tierWrite = route.request().postDataJSON();
    await route.fulfill({ json: intelligence });
  });
  await page.goto("/settings/intelligence");

  const ranking = page.getByRole("region", { name: "Fit ranking" });
  // Named for a person, never by the quantization.
  await expect(ranking.getByText("Big model")).toBeVisible();
  await expect(page.getByText(/Exact|Compact|fp32|int8/)).toHaveCount(0);

  await ranking.getByRole("button", { name: "Switch to the small model" }).click();
  const dialog = page.getByRole("dialog", { name: "Ranking model switch" });
  await expect(dialog).toBeVisible();

  // The accessible name is a heading the user can see, not a second string
  // only assistive tech is told.
  await expect(dialog.getByRole("heading", { name: "Ranking model switch" })).toBeVisible();

  // A work order: the routing slip states the direction, the hero states the
  // measured cost — duration plus the exact role count.
  await expect(dialog.getByText("about 15 min")).toBeVisible();
  await expect(dialog.getByText(/4,114 roles re-ranked/)).toBeVisible();

  // The recommendation reads in two tiers. The lead is the decision, split
  // into its two thoughts — the verdict, then the one reason to switch anyway;
  // the evidence is its own quieter line below. The limit is RAM — disk is
  // never mentioned.
  await expect(dialog.getByText("The big model produces better results.")).toBeVisible();
  await expect(dialog.getByText("Switch only if you want to free RAM.")).toBeVisible();
  // The evidence is a labelled comparison of two real readings, not prose.
  await expect(dialog.getByText("Small model is built for")).toBeVisible();
  await expect(dialog.getByText("16 GB")).toBeVisible();
  await expect(dialog.getByText("Your computer has")).toBeVisible();
  await expect(dialog.getByText("32 GB")).toBeVisible();
  await expect(dialog.getByText(/disk|storage/i)).toHaveCount(0);

  // The actions are a row, not a stacked column (the ledger form's own
  // `> div { display: grid }` would pile them vertically if it won).
  const cancelBox = await dialog.getByRole("button", { name: "Cancel" }).boundingBox();
  const startBox = await dialog.getByRole("button", { name: "Start the switch" }).boundingBox();
  expect(Math.abs((cancelBox?.y ?? 0) - (startBox?.y ?? 99))).toBeLessThan(4);

  // The shell takes focus on open but must not paint a focus ring around the
  // whole dialog — and focus is never on the confirm, so a stray Enter on open
  // cannot commit the switch.
  await expect(dialog).toHaveCSS("outline-style", "none");

  // The awake requirement and both escape hatches.
  await expect(dialog.getByText(/Keep the computer awake/)).toBeVisible();
  await expect(dialog.getByText(/Keep working while it runs/)).toBeVisible();
  await expect(dialog.getByText(/Stop anytime, restart anytime. Nothing is lost/)).toBeVisible();

  // Cancelling changes nothing at all.
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(dialog).toBeHidden();
  expect(tierWrite).toBeNull();

  await ranking.getByRole("button", { name: "Switch to the small model" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Start the switch" }).click();
  await expect.poll(() => tierWrite).toEqual({ tier: "int8" });
});

test("a running switch shows progress and stops by going back, never by a bare kill", async ({ page }) => {
  let stopped = false;
  const converting = {
    ...intelligence,
    matching: {
      ...intelligence.matching,
      tier: "int8",
      chosen_by: "user",
      reembedding: true,
      job_phase: "converting",
      corpus_embedded: 1212,
      stale_count: 2902,
      estimate_seconds: 780,
    },
  };
  await page.route("/api/intelligence", (route) =>
    route.fulfill({ json: stopped ? intelligence : converting }));
  await page.route("/api/intelligence/matching/stop", async (route) => {
    stopped = true;
    await route.fulfill({ json: intelligence });
  });
  await page.goto("/settings/intelligence");

  const ranking = page.getByRole("region", { name: "Fit ranking" });
  await expect(ranking.getByText("Switching to the small model")).toBeVisible();
  await expect(ranking.getByRole("progressbar", { name: "Switching progress" })).toBeVisible();
  await expect(ranking.getByText(/1,212 of 4,114 roles updated · about 13 min left/)).toBeVisible();
  await expect(ranking.getByText(/You can keep working meanwhile/)).toBeVisible();

  // One action, and it means stop AND revert — a bare stop would leave the
  // nightly pass to finish the switch the user just cancelled.
  await ranking.getByRole("button", { name: "Stop and go back to the big model" }).click();
  await expect.poll(() => stopped).toBe(true);
  await expect(ranking.getByText("Big model")).toBeVisible();
});

test("a model download can be stopped before any roles are converted", async ({ page }) => {
  let stopped = false;
  const downloading = {
    ...intelligence,
    matching: {
      ...intelligence.matching,
      tier: "int8",
      chosen_by: "user",
      status: "downloading",
      reembedding: true,
      job_phase: "downloading",
      downloaded_bytes: 96 * 1024 ** 2,
      total_bytes: 146 * 1024 ** 2,
      corpus_embedded: 0,
      stale_count: 4114,
    },
  };
  await page.route("/api/intelligence", (route) =>
    route.fulfill({ json: stopped ? intelligence : downloading }));
  await page.route("/api/intelligence/matching/stop", async (route) => {
    stopped = true;
    await route.fulfill({ json: intelligence });
  });
  await page.goto("/settings/intelligence");

  const ranking = page.getByRole("region", { name: "Fit ranking" });
  await expect(ranking.getByText(/downloading, 96 of 146 MB/)).toBeVisible();
  await ranking.getByRole("button", { name: "Stop and go back to the big model" }).click();

  await expect.poll(() => stopped).toBe(true);
  await expect(ranking.getByText("Big model")).toBeVisible();
});

test("a switch that stopped halfway says so instead of looking finished", async ({ page }) => {
  await page.route("/api/intelligence", (route) => route.fulfill({
    json: {
      ...intelligence,
      matching: {
        ...intelligence.matching,
        tier: "int8",
        chosen_by: "user",
        reembedding: false,
        job_phase: "none",
        stale_count: 2264,
        other_tier_count: 2264,
        estimate_seconds: 660,
      },
    },
  }));
  let resumed = false;
  await page.route("/api/intelligence/matching/resume", async (route) => {
    resumed = true;
    await route.fulfill({ json: intelligence });
  });
  await page.goto("/settings/intelligence");

  const ranking = page.getByRole("region", { name: "Fit ranking" });
  await expect(ranking.getByText("The switch to the small model is paused.")).toBeVisible();
  await expect(ranking.getByText(/The rest finishes tonight on its own/)).toBeVisible();
  await expect(ranking.getByText("1,850 of 4,114 roles updated")).toBeVisible();

  // Finishing is its OWN call: re-selecting the tier would pin the choice and
  // start nothing, because the tier is not the thing that is changing.
  await ranking.getByRole("button", { name: /Finish now, about 11 min/ }).click();
  await expect.poll(() => resumed).toBe(true);
});

test("assistants: the data sheet gates setup behind one conscious switch", async ({
  page,
  isMobile,
}) => {
  await page.goto("/settings/intelligence");
  const assistants = page.getByRole("region", { name: "MCP server" });

  // What will be seen is stated before anything can connect.
  await expect(assistants.getByText("What will be shared")).toBeVisible();
  await expect(assistants.getByText("What will not be shared")).toBeVisible();
  await expect(assistants.getByText(/full posting/)).toBeVisible();
  // A connected app can make this computer open pages, so the sheet says so.
  await expect(assistants.getByText("Public web pages it asks to open from this computer")).toBeVisible();
  await expect(assistants.getByText(/profile and intent statement/)).toBeVisible();

  // Nothing is reachable until the gate is on — and that holds for every
  // tile, the open door included.
  const setup = assistants.getByRole("button", { name: "Set up" });
  await expect(setup).toHaveCount(3);
  for (let i = 0; i < 3; i++) {
    await expect(setup.nth(i)).toBeDisabled();
    // An unavailable action names what would make it available.
    await expect(setup.nth(i)).toHaveAttribute("title", "Allow assistant apps to connect first");
  }
  // And the tiles say it in text, not by fading — a faded tile fades the app's
  // own name, and its opacity compounded with the disabled button inside it.
  await expect(assistants.getByText(/Anthropic · not allowed to connect/)).toBeVisible();

  // The write grant gates nothing while nothing may connect, so it is absent
  // rather than rendered disabled and greyed beside the gate.
  await expect(
    assistants.getByLabel("Allow assistant apps to update your progress"),
  ).toHaveCount(0);

  await assistants.getByLabel("Allow assistant apps to connect").click();
  await expect(assistants.getByLabel("Allow assistant apps to connect")).toBeChecked();
  await expect(setup.first()).toBeEnabled();

  // The gate describes what it opens, not the two clients we ship a recipe
  // for. Naming vendors here would contradict the third tile, which exists
  // precisely because MCP is a protocol and any client can speak it.
  const note = assistants.locator(".intel-gate-note");
  await expect(note).toHaveText("sent to the apps you connect · your own account");
  expect(await note.textContent()).not.toMatch(/Anthropic|OpenAI|Claude|Codex/);
  // ...and at desktop width it stays a clause on the gate's own line. The note
  // is `margin-left: auto` in a wrapping flex row, so a longer string silently
  // drops to a second line and the two grants stop lining up. The wrap is
  // correct on a narrow screen,
  // so this is a desktop-only claim.
  if (!isMobile) {
    const noteBox = (await note.boundingBox())!;
    const labelBox = (await assistants.getByText("Allow assistant apps to connect").boundingBox())!;
    expect(Math.abs(noteBox.y - labelBox.y)).toBeLessThan(6);
  }

  // Once the gate is open both grants live in one frame: the write switch is a
  // narrower grant of what the gate opened, not a neighbouring setting.
  const grants = assistants.locator(".intel-grants");
  await expect(grants.getByLabel("Allow assistant apps to connect")).toHaveCount(1);
  await expect(grants.getByLabel("Allow assistant apps to update your progress")).toHaveCount(1);

  // Set up is a dialog carrying the literal snippet.
  await setup.first().click();
  const dialog = page.getByRole("dialog", { name: "Set up the Claude app" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByText(/mcpServers/)).toBeVisible();
  await dialog.getByRole("button", { name: "Done" }).click();
  await expect(dialog).toBeHidden();

  // The open door hands over the SAME standard block, not a second recipe
  // that could drift from it.
  await setup.nth(2).click();
  const other = page.getByRole("dialog", { name: "Set up another MCP app" });
  await expect(other).toBeVisible();
  await expect(other.getByText(/Most apps that speak MCP take this JSON/)).toBeVisible();
  await expect(other.getByText(/mcpServers/)).toBeVisible();
  await other.getByRole("button", { name: "Done" }).click();
  await expect(other).toBeHidden();

  // Updates stay a second, separate choice.
  await assistants.getByLabel("Allow assistant apps to update your progress").click();
  await expect(assistants.getByLabel("Allow assistant apps to update your progress")).toBeChecked();
  await expect(assistants.getByText("stage · notes · next action · recipe drafts · audited")).toBeVisible();
});

test("your own model: the probe decides the action, configuration is a dialog", async ({ page }) => {
  let serverAction: unknown = null;
  let testedDraft: unknown = null;
  await page.route("/api/intelligence/local-models/server", async (route) => {
    if (route.request().method() === "POST") {
      serverAction = route.request().postDataJSON();
      await route.fulfill({
        json: {
          ...localServerStatusFixture, state: "server_unreachable", reachable: false,
          action: "stop", action_ok: true, action_detail: "oMLX stopped.",
        } satisfies LocalServerControlResult,
      });
      return;
    }
    await route.fulfill({ json: { ...localServerStatusFixture, detail: "oMLX is running." } satisfies LocalServerStatus });
  });
  await page.route("/api/intelligence/local-models/active/select", async (route) => {
    await route.fulfill({
      json: { ...localModelStateFixture, active_profile_id: otherLocalModelProfile.id } satisfies LocalLLMState,
    });
  });
  await page.route("/api/intelligence/local-models/profile67890/test", async (route) => {
    testedDraft = route.request().postDataJSON();
    await route.fulfill({
      json: {
        ...localModelTestResultFixture,
        profile_id: otherLocalModelProfile.id,
        model: "draft-qwen-model",
        metrics: { ...localModelTestResultFixture.metrics, wall_time_ms: 120, total_tokens: 12 },
      } satisfies LocalLLMTestResult,
    });
  });
  await page.goto("/settings/intelligence");
  const capabilities = page.getByRole("region", { name: "Extended capabilities" });

  // Reachable server: the row offers Stop, and the state says running.
  await expect(capabilities.getByText(/running/)).toBeVisible();
  const stop = capabilities.getByRole("button", { name: "Stop" });
  await expect(stop).toBeVisible();

  await stop.click();
  await expect.poll(() => serverAction).toEqual({ action: "stop" });
  await expect(capabilities.getByText(/server stopped/)).toBeVisible();
  await expect(capabilities.getByRole("button", { name: "Start" })).toBeVisible();

  // Configuration is one step in, with the saved connections and the fields.
  await capabilities.getByRole("button", { name: "Configure your own model" }).click();
  const dialog = page.getByRole("dialog", { name: "Configure your own model" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByLabel("Use Local Ornith")).toBeChecked();
  await expect(dialog.getByLabel("Use Local Qwen")).not.toBeChecked();
  await expect(dialog.getByLabel("Server address")).toHaveValue("http://127.0.0.1:8000/v1");
  await expect(dialog.getByText("Generation and reasoning parameters")).toBeVisible();

  // A saved connection's row holds its NAME, which the form's uppercase mono
  // field-label style would also claim, rendering "LOCAL ORNITH".
  const savedRow = dialog.locator(".intel-profile-list label").first();
  await expect(savedRow).toContainText("Local Ornith");
  expect(await savedRow.evaluate((el) => getComputedStyle(el).textTransform)).toBe("none");

  await dialog.getByRole("button", { name: "Test connection" }).click();
  await expect(dialog.getByText("Connection succeeded")).toBeVisible();

  // Selecting a saved connection replaces the form draft; testing then sends
  // the values on screen, not the persisted profile.
  await dialog.getByLabel("Use Local Qwen").click();
  await expect(dialog.getByLabel("Name")).toHaveValue("Local Qwen");
  await expect(dialog.getByLabel("Model ID")).toHaveValue("Qwen3-30B-A3B-4bit");
  await dialog.getByLabel("Model ID").fill("draft-qwen-model");
  await dialog.getByRole("button", { name: "Test connection" }).click();
  await expect.poll(() => testedDraft).toMatchObject({
    profile: { name: "Local Qwen", model: "draft-qwen-model" },
  });
});

test("your own model: every field owns its column, and the popup is a field like the rest", async ({
  page,
}) => {
  await page.goto("/settings/intelligence");
  const capabilities = page.getByRole("region", { name: "Extended capabilities" });
  await capabilities.getByRole("button", { name: "Configure your own model" }).click();
  const dialog = page.getByRole("dialog", { name: "Configure your own model" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByLabel("Server address")).toHaveValue(/^http/);
  // The parameters live in the same grid, so they are measured too — closed,
  // every rect is zero and each assertion below would pass vacuously.
  await dialog.getByText("Generation and reasoning parameters").click();
  await expect(dialog.getByLabel("Max tokens")).toBeVisible();

  // Geometry, read through the label-for-control relationship the form already
  // declares. `.ledger-form > div` is what stacks a label OVER its control, and
  // a child combinator stops at the field grid: cells it misses fall back to
  // `display: block`, so every label sits BESIDE its control and every control
  // keeps the UA's intrinsic width whatever column it is placed in, truncating
  // a value like "Server address".
  const fields = await dialog.evaluate((root) =>
    [...root.querySelectorAll<HTMLLabelElement>(".intel-dialog-grid label[for]")].map((label) => {
      const control = root.querySelector<HTMLElement>(`#${CSS.escape(label.htmlFor)}`)!;
      // The cell is the grid item, which is the select wrapper's parent too.
      const cell = control.closest<HTMLElement>(".intel-dialog-grid > *")!;
      const l = label.getBoundingClientRect();
      const c = control.getBoundingClientRect();
      const box = cell.getBoundingClientRect();
      return {
        name: label.textContent,
        stacked: l.bottom <= c.top + 1,
        fillsColumn: c.width > box.width - 2,
        height: Math.round(c.height),
        top: Math.round(c.top),
      };
    }),
  );

  expect(fields.map((f) => f.name)).toEqual([
    "Name", "Server type", "Server address", "Model ID", "API key",
    "Max tokens", "Temperature", "Top p", "Timeout (s)", "Thinking budget",
  ]);
  for (const field of fields) {
    expect(field.stacked, `${field.name}: label sits above its control`).toBe(true);
    expect(field.fillsColumn, `${field.name}: control fills its column`).toBe(true);
  }

  // A select is a text control here, so it is one of the fields in every
  // respect. Left out of the form's control rule it renders at the platform's
  // own short height in a row with 34px inputs.
  const byName = new Map(fields.map((f) => [f.name, f]));
  expect(byName.get("Server type")!.height).toBe(byName.get("Name")!.height);
  expect(Math.abs(byName.get("Server type")!.top - byName.get("Name")!.top))
    .toBeLessThanOrEqual(1);

  // The switch's own text is not a field label. `.ledger-form label` is the
  // uppercase mono column heading, and if it matched this label too the one
  // control that carries its text to the RIGHT would announce "ENABLE MODEL
  // THINKING": a column heading for a control that has no column.
  const switchRow = dialog.locator(".intel-dialog-check");
  await expect(switchRow).toHaveText("Enable model thinking");
  expect(
    await switchRow.evaluate((el) => getComputedStyle(el).textTransform),
  ).toBe("none");

  // Delete is the only irreversible button here. It leaves the confirm cluster,
  // and a single click only arms it.
  const actions = dialog.locator(".ledger-form-actions");
  const del = actions.getByRole("button", { name: "Delete" });
  const save = actions.getByRole("button", { name: "Save" });
  const delBox = (await del.boundingBox())!;
  const saveBox = (await save.boundingBox())!;
  const rowBox = (await actions.boundingBox())!;
  expect(delBox.x).toBeLessThan(saveBox.x);
  expect(saveBox.x - (delBox.x + delBox.width), "delete is not in the confirm cluster")
    .toBeGreaterThan(rowBox.width / 3);

  await del.click();
  await expect(actions.getByRole("button", { name: /^Confirm delete / })).toBeVisible();
});

test("a computer without oMLX gets no Start button it could not honour", async ({ page }) => {
  await page.route("/api/intelligence/local-models/server", (route) => route.fulfill({
    json: {
      ...localServerStatusFixture, installed: false, binary: null, managed: false,
      state: "server_unreachable", reachable: false, detail: "oMLX is not installed on this computer.",
    } satisfies LocalServerStatus,
  }));
  await page.goto("/settings/intelligence");
  const capabilities = page.getByRole("region", { name: "Extended capabilities" });

  await expect(capabilities.getByText(/not installed/)).toBeVisible();
  await expect(capabilities.getByRole("button", { name: /^(Start|Stop)$/ })).toHaveCount(0);
});

test("the standing permission is confirmed before connecting an online service", async ({ page }) => {
  await page.goto("/settings/intelligence");
  const capabilities = page.getByRole("region", { name: "Extended capabilities" });

  // No service yet, but the gate is a standing permission — answerable now,
  // like the MCP connect gate — so every row keeps the same shape AND the
  // switch actually works.
  await expect(capabilities.getByText("Online model services")).toBeVisible();
  await expect(capabilities.getByText(/None connected/)).toBeVisible();
  const futureGate = capabilities.getByLabel("Send postings to online services");
  await expect(futureGate).toBeEnabled();
  await expect(futureGate).not.toBeChecked();

  let egressWrite: unknown = null;
  await page.route("/api/intelligence/egress", async (route) => {
    egressWrite = route.request().postDataJSON();
    await route.fulfill({
      json: { ...intelligence, routing: { egress_enabled: true, tiers: [] } },
    });
  });
  await futureGate.click();
  const consent = page.getByRole("dialog", { name: msg("ai-egress-title") });
  await expect(consent.getByText(msg("ai-egress-empty"))).toBeVisible();
  expect(egressWrite).toBeNull();
  await consent.getByRole("button", { name: msg("ai-egress-allow") }).click();
  await expect.poll(() => egressWrite).toEqual({ enabled: true });

  // Adding is a dialog that names the boundary.
  await capabilities.getByRole("button", { name: "Add" }).click();
  const dialog = page.getByRole("dialog", { name: "Add an online model service" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByLabel("Server address (HTTPS)")).toHaveValue("https://api.openai.com/v1");
  await expect(dialog.getByText(/billed separately/)).toBeVisible();
  await dialog.getByRole("button", { name: "Cancel" }).click();
});

test("a saved online service brings the egress switch and its own row", async ({ page }) => {
  await page.route("/api/intelligence/cloud-models", (route) => route.fulfill({
    json: {
      profiles: [{ ...cloudModelProfileFixture, id: "cloud-openai", name: "OpenAI production", enabled: true }],
    } satisfies CloudLLMState,
  }));
  await page.goto("/settings/intelligence");
  const capabilities = page.getByRole("region", { name: "Extended capabilities" });

  await expect(capabilities.getByLabel("Send postings to online services")).not.toBeChecked();
  // The gate exists but is off, and the row says what that means: nothing leaves.
  await expect(capabilities.getByText(/off · nothing is sent/)).toBeVisible();
  await expect(capabilities.getByLabel("Use OpenAI production")).toBeChecked();

  // The service's own switch is on, the permission above it is not, and the
  // action that would reach the vendor is unavailable — with the switch that
  // holds it named, because that switch is on a different row.
  const test = capabilities.getByRole("button", { name: "Test OpenAI production" });
  await expect(test).toBeDisabled();
  await expect(test).toHaveAttribute("title", /Allow sending postings/);
  await expect(capabilities.getByText(/blocked · online services are switched off/)).toBeVisible();

  // Setup is not use: the gear is the only way to correct the connection, so
  // it stays live whatever the switches say.
  await expect(
    capabilities.getByRole("button", { name: "Configure OpenAI production" }),
  ).toBeEnabled();
});

test("Intelligence types by rank: same-rank text never differs in colour or weight", async ({
  page,
}) => {
  // Colour and weight carry RANK on this screen. Where they also carried a
  // category ("not connected yet", "never shared") or an element choice
  // (`<b>` vs `<span>`), two things of one rank rendered as two ranks.
  const typeOf = (selector: string) =>
    page.evaluate(
      (sel) =>
        [...document.querySelectorAll<HTMLElement>(sel)].map((el) => {
          const cs = getComputedStyle(el);
          return { text: (el.textContent || "").trim(), key: `${cs.color}/${cs.fontWeight}` };
        }),
      selector,
    );
  const distinct = (rows: { key: string }[]) => [...new Set(rows.map((r) => r.key))];

  await page.goto("/settings/intelligence");
  const capabilities = page.getByRole("region", { name: "Extended capabilities" });
  await expect(capabilities.getByText("Online model services")).toBeVisible();

  // Three capability rows, three names. The cloud row has no service yet, but
  // its switch, its Add button and its badge are all live, so demoting its
  // name would say "inactive" about the most interactive row on the card.
  const names = await typeOf(".intel-cap-name");
  expect(names.map((n) => n.text)).toContain("Online model services");
  expect(distinct(names)).toHaveLength(1);

  // Both halves of the data sheet are one rank: what an app will see, and what
  // it never will. The second is the half a person needs in order to trust the
  // first, so it may not be the quieter of the two.
  const sheet = await typeOf(".intel-sheet li");
  expect(sheet.length).toBeGreaterThan(4);
  expect(distinct(sheet)).toHaveLength(1);

  // The two grants sit in one frame that exists to say they are one decision,
  // so on screen together they are one type. While the gate is shut the second
  // gates nothing and is not on screen at all, so the card never renders one
  // rank in two colours.
  const gate = page.getByLabel("Allow assistant apps to connect");
  await expect(gate).not.toBeChecked();
  expect(await typeOf(".intel-grant-name")).toHaveLength(1);

  await gate.click();
  await expect(page.getByLabel("Allow assistant apps to update your progress")).toBeEnabled();
  const both = await typeOf(".intel-grant-name");
  expect(both).toHaveLength(2);
  expect(distinct(both)).toHaveLength(1);
});

test("Apple Intelligence is an experiment: labelled, local, testable only when on", async ({ page }) => {
  await page.goto("/settings/intelligence");
  const capabilities = page.getByRole("region", { name: "Extended capabilities" });

  await expect(capabilities.getByText("Apple Intelligence")).toBeVisible();
  await expect(capabilities.getByText(/· experimental$/)).toBeVisible();

  // Off in the fixture: the switch is off and Test cannot run.
  const toggle = capabilities.getByLabel("Enable Apple Intelligence");
  await expect(toggle).not.toBeChecked();
  const test = capabilities.getByRole("button", { name: "Test Apple Intelligence" });
  await expect(test).toBeDisabled();
  await expect(test).toHaveAttribute("title", "Turn Apple Intelligence on to test it");
});
