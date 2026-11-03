import { beforeEach, describe, expect, it, vi } from "vitest";
import { usageStateFixture } from "../test/fixtures";
import type { UsageGroup, UsageState } from "../api";

/* The browser side of usage sharing (docs/architecture.md): the privacy
   rules are in code, so they are held here, against the config the library
   receives and the events it would send. */

const posthog = vi.hoisted(() => ({
  init: vi.fn(),
  set_config: vi.fn(),
  opt_out_capturing: vi.fn(),
  opt_in_capturing: vi.fn(),
  has_opted_out_capturing: vi.fn(() => false),
  startSessionRecording: vi.fn(),
  stopSessionRecording: vi.fn(),
  identify: vi.fn(),
  reset: vi.fn(),
  get_distinct_id: vi.fn(() => "8f14e45f-ceea-4e7a-9b3a-1f2d3c4b5a69"),
}));
vi.mock("posthog-js/dist/module.full.no-external", () => ({ default: posthog }));

const CANARY = "zyxwv-robotics";

function withShared(groups: UsageGroup[], overrides: Partial<UsageState> = {}): UsageState {
  const state = usageStateFixture("declined", { install_id: "8f14e45f-ceea-4e7a-9b3a-1f2d3c4b5a69", ...overrides });
  state.groups = state.groups.map((group) => ({ ...group, status: groups.includes(group.group) ? "shared" : "declined" }));
  return state;
}

async function load() {
  vi.resetModules();
  return import("./sharing");
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("what the library is told", () => {
  it("holds the privacy rules whatever is shared", async () => {
    const { sharingConfig, sharedGroups } = await load();
    for (const groups of [[], ["usage"], ["crashes"], ["questions"], ["usage", "crashes", "questions"]] as UsageGroup[][]) {
      const state = withShared(groups);
      const config = sharingConfig(state, sharedGroups(state));
      expect(config.api_host).toBe("https://eu.i.posthog.com");
      expect(config.disable_external_dependency_loading).toBe(true);
      expect(config.opt_out_capturing_by_default).toBe(true);
      expect(config.opt_in_site_apps).toBe(false);
      expect(config.disable_web_experiments).toBe(true);
      expect(config.save_referrer).toBe(false);
      expect(config.mask_all_text).toBe(true);
      expect(config.mask_all_element_attributes).toBe(true);
      // RoleBand records no sessions, whatever is shared.
      expect(config.disable_session_recording).toBe(true);
      expect(config.enable_recording_console_log).toBe(false);
      expect(config.bootstrap?.distinctID).toBe(state.install_id);
    }
  });

  it("turns on only what is shared", async () => {
    const { sharingConfig, sharedGroups } = await load();
    const crashesOnly = withShared(["crashes"]);
    const config = sharingConfig(crashesOnly, sharedGroups(crashesOnly));
    expect(config.capture_exceptions).toBe(true);
    expect(config.autocapture).toBe(false);
    expect(config.capture_pageview).toBe(false);
    expect(config.capture_heatmaps).toBe(false);
    expect(config.disable_session_recording).toBe(true);
    expect(config.disable_surveys).toBe(true);
    const everything = withShared(["usage", "crashes", "questions"]);
    const all = sharingConfig(everything, sharedGroups(everything));
    expect(all.autocapture).toEqual({ capture_copied_text: false });
    expect(all.capture_pageview).toBe("history_change");
    expect(all.capture_exceptions).toBe(true);
    expect(all.disable_surveys).toBe(false);
  });

  it("shares nothing when the machine says so, or there is no key or ID", async () => {
    const { sharedGroups } = await load();
    const off = { usage: false, crashes: false, questions: false };
    expect(sharedGroups(withShared(["usage"], { blocked_by: "DO_NOT_TRACK" }))).toEqual(off);
    expect(sharedGroups(withShared(["usage"], { project_key: "" }))).toEqual(off);
    expect(sharedGroups(withShared(["usage"], { install_id: null }))).toEqual(off);
  });
});

describe("what an event carries", () => {
  it("reduces addresses to screens", async () => {
    const { screenPath } = await load();
    expect(screenPath("/")).toBe("/");
    expect(screenPath("/jobs/48213")).toBe("/jobs/:id");
    expect(screenPath(`/company/${CANARY}`)).toBe("/company/:id");
    expect(screenPath("/settings/privacy")).toBe("/settings/privacy");
    expect(screenPath("/statistics/compensation")).toBe("/statistics/compensation");
    expect(screenPath(`/${CANARY}`)).toBe("/:screen");
  });

  it("cleans messages of addresses, emails, quoted text and long numbers", async () => {
    const { redactMessage } = await load();
    const cleaned = redactMessage(
      `Failed to load https://boards.example.com/${CANARY}/jobs for ada@example.com: "${CANARY} Senior PM" id 482133`,
    );
    expect(cleaned).not.toContain(CANARY);
    expect(cleaned).not.toContain("ada@");
    expect(cleaned).not.toContain("482133");
    expect(cleaned).toContain("Failed to load");
  });

  it("cleans text in curly quotes and guillemets, each pair on its own", async () => {
    // The app's own copy quotes in curly quotes, so a message can carry them.
    const { redactMessage } = await load();
    for (const [open, close] of [["“", "”"], ["‘", "’"], ["«", "»"]]) {
      const cleaned = redactMessage(`title ${open}${CANARY} Staff${close} failed`);
      expect(cleaned).toBe("title <text> failed");
    }
    const two = redactMessage(`a “${CANARY}” and “second ${CANARY}” failed`);
    expect(two).toBe("a <text> and <text> failed");
  });

  it("rewrites every URL, drops referrers and titles, and remembers what left", async () => {
    const { beforeSend, recentEvents } = await load();
    const event = beforeSend({
      uuid: "u", event: "$pageview",
      properties: {
        $current_url: `${window.location.origin}/company/${CANARY}?tab=roles`,
        $pathname: `/company/${CANARY}`,
        $referrer: `https://www.google.com/search?q=${CANARY}`,
        $title: `${CANARY} | RoleBand`,
        $exception_list: [{ type: "TypeError", value: `Cannot read "${CANARY}"` }],
      },
      $set_once: { $initial_current_url: `${window.location.origin}/jobs/77` },
    } as never);
    const text = JSON.stringify(event);
    expect(text).not.toContain(CANARY);
    expect((event as { properties: Record<string, unknown> }).properties.$current_url).toBe(`${window.location.origin}/company/:id`);
    expect(recentEvents[0].event).toBe("$pageview");
  });

  /* The shapes below are the ones posthog-js builds itself: session entry
     properties on every event, heatmap buffers keyed by the page address,
     web vitals nested per metric, and the target of an outbound click. */
  const origin = window.location.origin;

  it("rewrites the session entry properties the library adds to every event", async () => {
    const { beforeSend } = await load();
    const event = beforeSend({
      uuid: "u", event: "$autocapture",
      properties: {
        $current_url: `${origin}/jobs/48213`,
        $session_entry_url: `${origin}/company/${CANARY}?q=${CANARY}`,
        $session_entry_pathname: `/company/${CANARY}`,
        $session_entry_host: window.location.host,
        $session_entry_referrer: `https://${CANARY}.example/search?q=staff`,
        $session_entry_referring_domain: `${CANARY}.example`,
        $session_entry_search_engine: "google",
        $session_entry_ph_keyword: CANARY,
        $external_click_url: `https://boards.example.com/${CANARY}/jobs/482133`,
      },
    } as never);
    const properties = (event as { properties: Record<string, unknown> }).properties;
    expect(JSON.stringify(event)).not.toContain(CANARY);
    expect(JSON.stringify(event)).not.toContain("48213");
    expect(properties.$session_entry_url).toBe(`${origin}/company/:id`);
    expect(properties.$session_entry_pathname).toBe("/company/:id");
    expect(properties.$session_entry_host).toBe(window.location.host);
    expect(properties).not.toHaveProperty("$session_entry_referrer");
    expect(properties).not.toHaveProperty("$external_click_url");
  });

  it("rewrites addresses used as keys, and merges what lands on one screen", async () => {
    const { beforeSend } = await load();
    const event = beforeSend({
      uuid: "u", event: "$$heatmap",
      properties: {
        $current_url: `${origin}/jobs/48213`,
        $heatmap_data: {
          [`${origin}/jobs/48213?company=${CANARY}`]: [{ x: 10, y: 20, type: "click" }],
          [`${origin}/jobs/77`]: [{ x: 30, y: 40, type: "click" }],
        },
      },
    } as never);
    const data = (event as { properties: Record<string, unknown> }).properties.$heatmap_data as Record<string, unknown[]>;
    expect(JSON.stringify(event)).not.toContain(CANARY);
    expect(Object.keys(data)).toEqual([`${origin}/jobs/:id`]);
    expect(data[`${origin}/jobs/:id`]).toHaveLength(2);
  });

  it("rewrites addresses nested inside a metric, and keeps the app's own script files", async () => {
    const { beforeSend } = await load();
    const asset = `${origin}/assets/index-4f2a9c.js`;
    const event = beforeSend({
      uuid: "u", event: "$web_vitals",
      properties: {
        $current_url: `${origin}/company/${CANARY}`,
        $web_vitals_LCP_event: {
          name: "LCP", value: 1840,
          $current_url: `${origin}/company/${CANARY}`,
          attribution: { navigationURL: `/company/${CANARY}`, url: `${origin}/company/${CANARY}/logo.png` },
        },
        $web_vitals_LCP_value: 1840,
        $exception_list: [{ type: "TypeError", value: "x", stacktrace: { frames: [{ filename: asset, lineno: 3 }] } }],
      },
    } as never);
    const properties = (event as { properties: Record<string, unknown> }).properties;
    expect(JSON.stringify(event)).not.toContain(CANARY);
    expect(properties.$web_vitals_LCP_event).toMatchObject({
      name: "LCP", value: 1840, $current_url: `${origin}/company/:id`, attribution: { navigationURL: "/company/:id" },
    });
    expect(JSON.stringify(properties.$exception_list)).toContain(asset);
  });
});

describe("starting and stopping", () => {
  it("loads nothing while nothing is shared", async () => {
    const { applySharing } = await load();
    await applySharing(withShared([]));
    expect(posthog.init).not.toHaveBeenCalled();
  });

  it("starts on a share, never records a session, and stops on decline", async () => {
    const { applySharing } = await load();
    const usage = withShared(["usage"]);
    await applySharing(usage);
    expect(posthog.init).toHaveBeenCalledTimes(1);
    expect(posthog.init.mock.calls[0][0]).toBe(usage.project_key);
    expect(posthog.identify).toHaveBeenCalledWith(usage.install_id);

    await applySharing(withShared(["usage", "crashes", "questions"]));
    expect(posthog.init).toHaveBeenCalledTimes(1);
    expect(posthog.set_config).toHaveBeenCalled();
    expect(posthog.startSessionRecording).not.toHaveBeenCalled();

    await applySharing(withShared([]));
    expect(posthog.opt_out_capturing).toHaveBeenCalled();
    expect(posthog.startSessionRecording).not.toHaveBeenCalled();
  });
});
