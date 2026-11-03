import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Notification } from "../../api";
import { activate } from "../../copy/activate";
import { NotificationRow } from "./NotificationRow";

/* A scan that only ran out of RoleBand's own time is written as its
 * own category at low priority with `sync_state: "partial"`. Filed under
 * `sync_warning` it would wear "Scan finished with problems" as its icon's name
 * and "Scan problems" as its badge, over a title saying nothing went wrong. */
const unfinished: Notification = {
  id: 41,
  created_at: "2026-09-27T08:40:00Z",
  priority: "low",
  category: "sync_unfinished",
  title: "Scan ran out of time before 2 companies",
  body: "Finished at 2026-09-27 08:40 UTC after 40m 0s. Not reached before the scan ran out of time: Meta, Stripe.",
  job_id: null,
  run_id: 1968,
  source_type: "run",
  read_at: null,
  dismissed_at: null,
  company: null,
  meta: { sync_state: "partial", unreached_sources: ["meta", "stripe"], cut_short_sources: [] },
};

function renderRow(n: Notification) {
  const noop = vi.fn();
  return render(
    <NotificationRow
      n={n}
      isOpen={false}
      copied={null}
      onCopy={async () => {}}
      onOpen={noop}
      onToggle={noop}
      onMarkRead={noop}
      onDismiss={noop}
      onOpenJob={noop}
    />,
  );
}

describe("NotificationRow for a scan that ran out of time", () => {
  it("names it as what it is, never as a problem", () => {
    renderRow(unfinished);

    expect(screen.getByRole("img", { name: "Scan ran out of time" })).toBeInTheDocument();
    expect(screen.getByText("Ran out of time")).toHaveClass("ui-badge");
    expect(screen.queryByText(/problems/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("img", { name: /problems/i })).not.toBeInTheDocument();
  });

  it("wears a neutral priority chip, not a warning's hue", () => {
    renderRow(unfinished);
    expect(screen.getByText("low")).toHaveClass("ui-badge-neutral");

    // Control: a real warning keeps its hue, so the chip still carries state.
    renderRow({ ...unfinished, id: 42, category: "sync_warning", priority: "normal", meta: { sync_state: "warning" } });
    expect(screen.getByText("normal")).toHaveClass("ui-badge-warning");
  });
});

describe("NotificationRow's words", () => {
  const said: Notification = {
    ...unfinished,
    id: 43,
    title: "Scan ran out of time before 1 company",
    body: "Finished at 2026-09-27 08:40 UTC after 40m 0s.",
    meta: {
      sync_state: "partial",
      say: {
        title: { k: "notif-unfinished-u", p: { unreached: { k: "notif-companies", p: { count: 1 } } } },
        body: [{ k: "notif-finished-at", p: { at: "2026-09-27 08:40 UTC", duration: { k: "notif-duration-minutes", p: { m: 40, s: 0 } } } }],
      },
    },
  };

  it("are the catalog's in the reader's language, nested phrases included", async () => {
    await activate("en-XA");
    try {
      renderRow(said);
      expect(screen.getByText(/^⟦Šçàñ ŕàñ öûţ öƒ ţîɱé ƀéƒöŕé ⟦1 çöɱþàñý/)).toBeInTheDocument();
      expect(screen.getByText(/^⟦Ƒîñîšĥéð àţ 2026-09-27 08:40 UTC àƒţéŕ ⟦40ɱ 0š/)).toBeInTheDocument();
      expect(screen.queryByText(said.title)).not.toBeInTheDocument();
    } finally {
      await activate("en");
    }
  });

  it("are the stored English when the row carries no keys", () => {
    renderRow(unfinished);
    expect(screen.getByText(unfinished.title)).toBeInTheDocument();
  });
});
