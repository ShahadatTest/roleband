import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, type SourceOutcome, type SyncTarget } from "../../api";
import { activate } from "../../copy/activate";
import { msg } from "../../test/msg";
import { SyncScopePopover } from "./SyncScopePopover";

/* Each company's last outcome reads as a badge in the person's words, and an
   outcome the backend names, a scan this computer paused included, is never
   dropped from its row. */

vi.mock("../../context/SyncState", () => ({ useSyncActions: () => ({ triggerSync: vi.fn() }) }));

function target(slug: string, last_outcome: SourceOutcome | null): SyncTarget {
  return {
    slug, display: slug[0].toUpperCase() + slug.slice(1), adapter: "greenhouse", age_hours: 3, automatic: true,
    coverage: null, last_full_scan_at: null, last_outcome, last_sync_at: null, retryable: false, stale: false,
  };
}

describe("the scan picker's last outcome", () => {
  it("names each outcome in the catalog's words, and says nothing for a clean scan", async () => {
    vi.spyOn(api, "syncTargets").mockResolvedValue({
      freshness_max_hours: 24,
      companies: [target("google", "suspended"), target("meta", "lossy"), target("apple", "degraded"),
        target("stripe", "ok")],
    });
    render(<SyncScopePopover isOpen anchor={document.body} onClose={vi.fn()} onFailed={vi.fn()} />);

    const row = async (name: string) => (await screen.findByLabelText(name)).closest("label") as HTMLElement;
    expect(within(await row("Google")).getByText(msg("scan-sync-scope-popover-paused"))).toBeInTheDocument();
    expect(within(await row("Meta")).getByText(msg("scan-sync-scope-popover-a-few-rows-unread"))).toBeInTheDocument();
    expect(within(await row("Apple")).getByText(msg("scan-sync-scope-popover-partial"))).toBeInTheDocument();
    expect((await row("Stripe")).querySelector(".ui-badge")).toBeNull();
    expect((await row("Google")).querySelector(".ui-badge")).not.toBeNull();
  });
});

describe("the scan picker's select-all count", () => {
  afterEach(() => activate("en"));

  async function selectAllText(): Promise<string | null> {
    const box = await screen.findByRole("checkbox", { name: msg("scan-sync-scope-popover-select-all-shown-companies") });
    return box.closest("label")?.textContent ?? null;
  }

  it("is one sentence a translation can punctuate, with and without a filter", async () => {
    await activate("zh-Hans");
    vi.spyOn(api, "syncTargets").mockResolvedValue({
      freshness_max_hours: 24,
      companies: [target("google", null), target("meta", null), target("apple", null)],
    });
    render(<SyncScopePopover isOpen anchor={document.body} onClose={vi.fn()} onFailed={vi.fn()} />);

    expect(await selectAllText()).toBe(msg("scan-sync-scope-popover-all-shown", { choice: "no", shown: 3, total: 3 }));
    await userEvent.type(screen.getByRole("searchbox", { name: msg("scan-sync-scope-popover-filter-companies-to-scan") }), "goo");
    expect(await selectAllText()).toBe(msg("scan-sync-scope-popover-all-shown", { choice: "yes", shown: 1, total: 3 }));
    expect(await selectAllText()).not.toMatch(/All shown/);
  });
});
