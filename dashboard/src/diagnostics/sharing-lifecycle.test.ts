import { afterEach, expect, it, vi } from "vitest";
import type { UsageGroup, UsageState } from "../api";
import { usageStateFixture } from "../test/fixtures";

const NEW_ID = "0b5c1f7e-2d4a-4c8e-9f10-6a7b8c9d0e1f";

function state(groups: UsageGroup[], install_id?: string): UsageState {
  const result = usageStateFixture("shared", install_id ? { install_id } : {});
  return {
    ...result,
    groups: result.groups.map((group) => ({ ...group, status: groups.includes(group.group) ? "shared" : "declined" })),
  };
}

async function load() {
  vi.resetModules();
  let release!: () => void;
  let started!: () => void;
  const ready = new Promise<void>((resolve) => { release = resolve; });
  const importing = new Promise<void>((resolve) => { started = resolve; });
  let id = "persisted-browser-id";
  const posthog = {
    init: vi.fn(), set_config: vi.fn(),
    reset: vi.fn((options: { bootstrap?: { distinctID?: string } }) => { id = options.bootstrap?.distinctID ?? "anonymous"; }),
    get_distinct_id: vi.fn(() => id), identify: vi.fn(),
    opt_out_capturing: vi.fn(), opt_in_capturing: vi.fn(),
    has_opted_out_capturing: vi.fn(() => true),
  };
  vi.doMock("posthog-js/dist/module.full.no-external", async () => {
    started();
    await ready;
    return { default: posthog };
  });
  return { ...await import("./sharing"), posthog, importing, release };
}

afterEach(() => { vi.doUnmock("posthog-js/dist/module.full.no-external"); });

it("does not start capture when all consent is revoked during the SDK import", async () => {
  const sdk = await load();
  const pending = sdk.applySharing(state(["usage", "crashes", "questions"]));
  await sdk.importing;
  await sdk.applySharing(state([]));
  sdk.release();
  await pending;
  expect(sdk.posthog.init).not.toHaveBeenCalled();
  expect(sdk.posthog.identify).not.toHaveBeenCalled();
  expect(sdk.posthog.opt_in_capturing).not.toHaveBeenCalled();
});

it("initializes once with only the latest groups and ID after overlapping first shares", async () => {
  const sdk = await load();
  const first = sdk.applySharing(state(["usage", "crashes", "questions"]));
  await sdk.importing;
  const latest = state(["crashes"], NEW_ID);
  const second = sdk.applySharing(latest);
  sdk.release();
  await Promise.all([first, second]);
  expect(sdk.posthog.init).toHaveBeenCalledExactlyOnceWith(latest.project_key, expect.objectContaining({
    bootstrap: {}, autocapture: false, capture_pageview: false, capture_exceptions: false, disable_surveys: true,
  }));
  expect(sdk.posthog.set_config).toHaveBeenLastCalledWith(expect.objectContaining({
    bootstrap: { distinctID: NEW_ID, isIdentifiedID: true }, capture_exceptions: true,
  }));
  expect(sdk.posthog.reset).toHaveBeenCalledExactlyOnceWith({
    resetDeviceID: true, bootstrap: { distinctID: NEW_ID, isIdentifiedID: true },
  });
  expect(sdk.posthog.identify).not.toHaveBeenCalled();
});

it("can start a later share after an import finishes with consent revoked", async () => {
  const sdk = await load();
  const pending = sdk.applySharing(state(["usage"]));
  await sdk.importing;
  await sdk.applySharing(state([]));
  sdk.release();
  await pending;
  await sdk.applySharing(state(["questions"], NEW_ID));
  expect(sdk.posthog.init).toHaveBeenCalledTimes(1);
  expect(sdk.posthog.set_config.mock.calls[0][0]).toMatchObject({
    bootstrap: { distinctID: NEW_ID }, autocapture: false, disable_surveys: false,
  });
});

it.each<UsageGroup[]>([["usage"], ["crashes"], ["questions"]])(
  "resets device persistence before using a new install ID while sharing %s",
  async (group) => {
    const sdk = await load();
    sdk.release();
    await sdk.applySharing(state([group]));
    vi.clearAllMocks();
    await sdk.applySharing(state([group], NEW_ID));
    expect(sdk.posthog.reset).toHaveBeenCalledExactlyOnceWith({
      resetDeviceID: true, bootstrap: { distinctID: NEW_ID, isIdentifiedID: true },
    });
    expect(sdk.posthog.reset.mock.invocationCallOrder[0]).toBeLessThan(
      sdk.posthog.opt_in_capturing.mock.invocationCallOrder[0],
    );
    const config = sdk.posthog.set_config.mock.calls[0][0];
    expect(config.capture_exceptions).toBe(group === "crashes");
    expect(config.disable_surveys).toBe(group !== "questions");
    expect(Boolean(config.autocapture)).toBe(group === "usage");
  },
);

it("rotates a stopped client's identity without enabling capture and keeps it on resume", async () => {
  const sdk = await load();
  sdk.release();
  await sdk.applySharing(state(["usage"]));
  await sdk.applySharing(state([]));
  vi.clearAllMocks();
  await sdk.applySharing(state([], NEW_ID));
  expect(sdk.posthog.reset).toHaveBeenCalledExactlyOnceWith({
    resetDeviceID: true, bootstrap: { distinctID: NEW_ID, isIdentifiedID: true },
  });
  expect(sdk.posthog.opt_out_capturing).toHaveBeenCalled();
  expect(sdk.posthog.opt_in_capturing).not.toHaveBeenCalled();
  expect(sdk.posthog.identify).not.toHaveBeenCalled();
  await sdk.applySharing(state(["usage"], NEW_ID));
  expect(sdk.posthog.reset).toHaveBeenCalledTimes(1);
  expect(sdk.posthog.identify).toHaveBeenLastCalledWith(NEW_ID);
});
