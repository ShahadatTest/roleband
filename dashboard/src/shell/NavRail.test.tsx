import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { NavRail } from "./NavRail";

vi.mock("../context/JobWorkspace", () => ({
  useJobWorkspace: () => ({ compareIds: new Set<number>() }),
}));

// Mutable so a test can put the rail in front of a real queue depth.
let stats: Record<string, number> = { notif_unread: 0, review_pending: 0 };
vi.mock("../context/MissionState", () => ({
  useMissionStats: () => stats,
}));

beforeEach(() => {
  stats = { notif_unread: 0, review_pending: 0 };
});

const rail = (expanded = false) =>
  render(
    <MemoryRouter>
      <NavRail expanded={expanded} onToggleExpanded={vi.fn()} theme="dark" onToggleTheme={vi.fn()} />
    </MemoryRouter>
  );

describe("NavRail", () => {
  it("starts as an icon rail and expands only from the rail toggle", async () => {
    const user = userEvent.setup();
    const onToggleExpanded = vi.fn();

    render(
      <MemoryRouter>
        <NavRail expanded={false} onToggleExpanded={onToggleExpanded} theme="dark" onToggleTheme={vi.fn()} />
      </MemoryRouter>
    );

    expect(screen.getByRole("navigation", { name: "Primary" })).toHaveClass("collapsed");
    expect(screen.getByRole("button", { name: "Expand navigation" })).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("link", { name: "Radar" })).toHaveAttribute("data-tip", "Radar");

    await user.click(screen.getByRole("button", { name: "Expand navigation" }));
    expect(onToggleExpanded).toHaveBeenCalledTimes(1);
  });

  it("marks the rail with the product mark, hidden from readers, not a letter", () => {
    const { container } = rail();
    const tile = container.querySelector(".brand-mark");
    const mark = tile?.querySelector("svg[data-brand-mark]");
    expect(mark).not.toBeNull();
    expect(mark).toHaveAttribute("aria-hidden", "true");
    expect(mark?.querySelectorAll("circle[r='43.9'], circle[r='28.6'], circle[r='13.2']")).toHaveLength(3);
    expect(tile).toHaveTextContent(/^$/);
  });

  it("exposes a collapse control when expanded", () => {
    render(
      <MemoryRouter>
        <NavRail expanded onToggleExpanded={vi.fn()} theme="dark" onToggleTheme={vi.fn()} />
      </MemoryRouter>
    );

    expect(screen.getByRole("navigation", { name: "Primary" })).toHaveClass("expanded");
    expect(screen.getByRole("button", { name: "Collapse navigation" })).toHaveAttribute("aria-expanded", "true");
  });

  /* The badge policy, at the two counts that decide it.
   *
   * `review_pending` is the pending duplicate queue, which can sit in the
   * hundreds — so a saturated `99+` badge would be the one rail item that
   * never settles and never says anything. */
  it("shows a count a user can act on as the number it is", () => {
    stats = { notif_unread: 0, review_pending: 12 };
    rail();

    const review = screen.getByRole("link", { name: "Duplicates, 12 pending" });
    const badge = review.querySelector(".rail-badge")!;
    expect(badge).toHaveTextContent("12");
    expect(badge).not.toHaveClass("rail-badge-dot");
  });

  it("stops claiming to be a count past the cap, keeping the exact number", () => {
    stats = { notif_unread: 0, review_pending: 342 };
    rail();

    // The number is on the item — as its name, its hover tooltip collapsed
    // (`data-tip`) and expanded (`title`) — not saturated inside the badge.
    const review = screen.getByRole("link", { name: "Duplicates, 342 pending" });
    expect(review).toHaveAttribute("data-tip", "Duplicates, 342 pending");
    expect(review).toHaveAttribute("title", "Duplicates, 342 pending");

    const badge = review.querySelector(".rail-badge")!;
    expect(badge).toHaveClass("rail-badge-dot");
    expect(badge).toHaveTextContent("");
    expect(review).not.toHaveTextContent("99+");
  });

  it("leaves an item with nothing pending unbadged and unrenamed", () => {
    rail();

    const review = screen.getByRole("link", { name: "Duplicates" });
    expect(review.querySelector(".rail-badge")).toBeNull();
    expect(screen.getByRole("link", { name: "Notifications" })).toBeTruthy();
  });

});
