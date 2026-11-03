import { describe, expect, it } from "vitest";
import {
  pluginAdoptingFixture, pluginFixture, pluginRunContinuingFixture, pluginRunErroredFixture, pluginRunFixture,
  pluginRunStoppedFixture,
} from "../../test/fixtures";
import { msg } from "../../test/msg";
import {
  PLUGIN_SLOTS, aboutTime, removeWords, ago, companiesRead, freshest, lastUpdate, leftToRead, outOf, paceTime, rowState, runLine,
  runOutcome, slotWord, timingLine,
} from "./pluginWords";
import { duration, list } from "../../copy/format";
import { removedRows } from "./usePluginActions";

/* The words the plugin screens build from wire codes. Every code the wire can
   send has its own catalog branch; a code it cannot is answered neutrally,
   never with another code's words. */

describe("slot words", () => {
  it("every PluginSlot has its own branch, none of them the catalog's fallback", () => {
    const fallback = msg("settings-plugins-section-slot", { slot: "not_a_slot" });
    const words = PLUGIN_SLOTS.map(slotWord);
    expect(PLUGIN_SLOTS).toHaveLength(4);
    expect(new Set(words).size).toBe(PLUGIN_SLOTS.length);
    for (const [i, slot] of PLUGIN_SLOTS.entries()) {
      expect(words[i], `${slot} reads as the fallback`).not.toBe(fallback);
      expect(words[i]).toBe(msg("settings-plugins-section-slot", { slot: slot.replaceAll(".", "_") }));
    }
  });

  it("a slot the catalog does not know reads as no other slot", () => {
    const unknown = msg("settings-plugins-section-slot", { slot: "company_offices" });
    expect(PLUGIN_SLOTS.map(slotWord)).not.toContain(unknown);
  });

  it("codes the catalog does not know fall back to neutral words, not a real value's", () => {
    expect(msg("settings-plugins-section-state", { state: "archived" }))
      .not.toBe(msg("settings-plugins-section-state", { state: "removed" }));
    expect(msg("settings-plugins-section-schedule", { schedule: "hourly" }))
      .not.toBe(msg("settings-plugins-section-schedule", { schedule: "manual" }));
    expect(msg("settings-plugin-settings-run", { outcome: "cancelled", when: "now" }))
      .not.toBe(msg("settings-plugin-settings-run", { outcome: "error", when: "now" }));
  });
});

describe("an update that continues", () => {
  // Uncounted (no progress): the outcome alone; a counted one is under "how far an update got".
  const continuing = pluginFixture({
    last_run: { ...pluginFixture().last_run!, outcome: "clean", continues: true, progress_done: null, progress_total: null },
  });

  it("reads as a pass in progress, never as a finished update", () => {
    expect(runOutcome(continuing.last_run!)).toBe("continues");
    expect(lastUpdate(continuing)).not.toBe(lastUpdate(pluginFixture()));
    const when = ago(continuing.last_run!.ended_at!);
    expect(runLine(continuing.last_run)).toBe(msg("settings-plugin-settings-run", { outcome: "continues", when }));
    expect(runLine(continuing.last_run)).not.toBe(msg("settings-plugin-settings-run", { outcome: "clean", when }));
    // No "next update" date beside it: the next update is the continuation.
    expect(timingLine(continuing)).not.toContain(msg("settings-plugins-section-next-update", { when: "" }).trim());
  });

  it("a clean run that finished its pass is a finished update", () => {
    expect(runOutcome(pluginFixture().last_run!)).toBe("clean");
  });
});

describe("a Start waiting for its run", () => {
  it("reads as updating at once, and never for a plugin that cannot run", () => {
    expect(rowState(pluginFixture(), true)).toBe("updating");
    expect(rowState(pluginFixture({ state: "disabled" }), true)).toBe("disabled");
    expect(lastUpdate(pluginFixture(), true)).toBe(
      msg("settings-plugin-settings-run", { outcome: "running", when: "" }),
    );
  });
});

describe("removed rows", () => {
  it("count the data the plugin added, not the coverage bookkeeping cleared with it", () => {
    expect(removedRows({ company_comp_level: 2804, company_benefit: 1120, plugin_coverage: 96 })).toBe(3924);
    expect(removedRows({ plugin_coverage: 12 })).toBe(0);
  });

  it("never count what was worked out from its rows or what it kept for itself", () => {
    expect(removedRows({ company_comp_level: 2, job_comp_estimate: 10_472, comp_snapshot: 80, plugin_state: 3,
                         plugin_report: 1, plugin_coverage: 2 })).toBe(2);
  });
});

describe("what Remove data deletes", () => {
  it("names the kinds it added, or, when none can be removed, what stays as history", () => {
    expect(removeWords(pluginFixture())).toEqual({ what: "rows", kinds: list([
      msg("settings-plugins-section-slot", { slot: "company_benefits" }),
      msg("settings-plugins-section-slot", { slot: "pay_levels" })]) });
    expect(removeWords(pluginFixture({ slots: ["pay.observations"], removable_slots: [] }))).toEqual({
      what: "history", kinds: msg("settings-plugins-section-slot", { slot: "pay_observations" }) });
  });
});

/** "4 of 1,180 companies", as the shared count says it. */
const read = (n: number, t: number) => msg("shared-results-of-company", { n, t, total: t });

describe("one casing for the last update", () => {
  // The row's first fact is the plugin page's own words, so the list and the
  // page never disagree, and a line starts capitalised.
  it("the row's line opens with exactly what the plugin's page says, for every kind of run", () => {
    const plugins = [
      pluginFixture(),
      pluginFixture({ last_run: pluginRunStoppedFixture() }),
      pluginFixture({ last_run: pluginRunContinuingFixture() }),
      pluginFixture({ last_run: null }),
    ];
    for (const plugin of plugins) {
      const line = timingLine(plugin);
      expect(line.startsWith(runLine(plugin.last_run))).toBe(true);
      expect(line[0]).toBe(line[0].toLocaleUpperCase());
    }
    expect(timingLine(pluginFixture(), true).startsWith(runLine(null, true))).toBe(true);
  });
});

describe("how far an update got", () => {
  it("a stopped update says when it stopped and after how many companies, on the row and standing alone", () => {
    const run = pluginRunStoppedFixture();
    const when = ago(run.ended_at!);
    const plugin = pluginFixture({ last_run: run });
    expect(lastUpdate(plugin)).toBe(msg("settings-plugin-settings-run-progress", { outcome: "stopped", when, read: read(4, 1180) }));
    expect(runLine(run)).toBe(msg("settings-plugin-settings-run-progress", { outcome: "stopped", when, read: read(4, 1180) }));
    expect(runLine(run)).toContain("1,180");
  });

  it("an update that continues says how far this part got, and that it carries on", () => {
    const run = pluginRunContinuingFixture();
    const when = ago(run.ended_at!);
    expect(runLine(run)).toBe(msg("settings-plugin-settings-run-progress", { outcome: "continues", when, read: read(300, 1180) }));
    expect(lastUpdate(pluginFixture({ last_run: run }))).toBe(
      msg("settings-plugin-settings-run-progress", { outcome: "continues", when, read: read(300, 1180) }),
    );
  });

  it("an update in flight says its live progress", () => {
    const run = pluginRunFixture({ outcome: "running", ended_at: null, progress_done: 12, progress_total: 96 });
    expect(lastUpdate(pluginFixture({ running: true, last_run: run }))).toBe(
      msg("settings-plugin-settings-run-progress", { outcome: "running", when: "", read: read(12, 96) }),
    );
    expect(runLine(run)).toBe(msg("settings-plugin-settings-run-progress", { outcome: "running", when: "", read: read(12, 96) }));
  });

  it("a finished update says no count, and one that never counted says none", () => {
    const clean = pluginRunFixture();
    expect(runLine(clean)).toBe(msg("settings-plugin-settings-run", { outcome: "clean", when: ago(clean.ended_at!) }));
    const uncounted = pluginRunErroredFixture({ progress_done: null, progress_total: null });
    expect(companiesRead(uncounted)).toBeNull();
    expect(runLine(uncounted)).toBe(msg("settings-plugin-settings-run", { outcome: "error", when: ago(uncounted.ended_at!) }));
  });
});

describe("what a plugin's own data answers for", () => {
  it("the row counts the most companies any one kind is fresh for, never the sum", () => {
    // Pay by level for 96 companies and benefits for 81: 96 companies, not 177.
    const plugin = pluginFixture();
    expect(freshest(plugin)).toBe(96);
    expect(timingLine(plugin)).toContain(msg("settings-plugins-section-read", { read: 96, companies: 120 }));
    expect(timingLine(plugin)).not.toContain("177");
    expect(freshest(pluginAdoptingFixture())).toBe(4);
  });

  it("a plugin that cannot answer is fresh for nothing, whatever it published", () => {
    expect(freshest(pluginFixture({ state: "disabled" }))).toBe(0);
    expect(freshest(pluginFixture({ state: "needs_approval", enabled: true }))).toBe(0);
    expect(timingLine(pluginFixture({ state: "disabled" }))).not.toContain(
      msg("settings-plugins-section-read", { read: 96, companies: 120 }),
    );
  });

  it("a read count is out of the followed companies, never fewer than it read", () => {
    expect(outOf(pluginFixture(), 96)).toBe(120);
    // A company read and unfollowed since still counts: never "130 of 120".
    expect(outOf(pluginFixture(), 130)).toBe(130);
  });
});

describe("how long the rest takes", () => {
  it("says a long time in whole hours, a shorter one in five minutes, never under a minute", () => {
    expect(aboutTime(76_000)).toBe(duration(21 * 3600));
    expect(aboutTime(2 * 3600 + 7 * 60)).toBe(duration(2 * 3600 + 5 * 60));
    expect(aboutTime(20)).toBe(duration(60));
  });

  it("says one company's time in whole minutes from a minute, else five seconds", () => {
    expect(paceTime(62)).toBe(duration(60));
    expect(paceTime(100)).toBe(duration(120));
    expect(paceTime(12)).toBe(duration(10));
  });

  it("says nothing without a pass under way", () => {
    expect(leftToRead(pluginFixture())).toBeNull();
    expect(leftToRead(pluginAdoptingFixture())).toEqual({ duration: duration(21 * 3600), pace: duration(60) });
  });
});
