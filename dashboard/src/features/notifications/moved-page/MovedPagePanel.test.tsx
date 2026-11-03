import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { MovedBoard, Notification } from "../../../api";
import { NotificationRow } from "../NotificationRow";
import type { MovedPageVerbs } from "./MovedPagePanel";
import { foundSentence, movedPageOf } from "./model";

/* "{Company}'s careers page is gone": a careers page can move to another
 * board, or be renamed to a name no guess reaches. The notice is where the
 * person answers: find it, use it, give its link, or stop following. */

const gone: Notification = {
  id: 77,
  created_at: "2026-10-04T16:06:01Z",
  priority: "normal",
  category: "coverage",
  title: "Hex Technologies's careers page is gone · 2 days",
  body: "Its careers page is no longer at its last address.",
  job_id: null,
  run_id: null,
  source_type: "binding",
  read_at: null,
  dismissed_at: null,
  company: null,
  meta: { company: "hex-technologies", display: "Hex Technologies", cause: "board_missing", held_open: 3 },
};

const hex: MovedBoard = {
  adapter: "ashby", board_token: "hex", board_region: null, roles: 36, shared: 30, found_by: "name",
};

function verbs(found: MovedBoard | null = hex): MovedPageVerbs & Record<string, ReturnType<typeof vi.fn>> {
  return {
    find: vi.fn(async () => found),
    move: vi.fn(async () => true),
    stopFollowing: vi.fn(async () => {}),
  };
}

function renderRow(n: Notification, v?: MovedPageVerbs) {
  const noop = vi.fn();
  return render(
    <NotificationRow
      n={n} isOpen={false} copied={null} onCopy={async () => {}} onOpen={noop} onToggle={noop}
      onMarkRead={noop} onDismiss={noop} onOpenJob={noop} movedPage={v}
    />,
  );
}

describe("a careers page gone from its address", () => {
  it("finds the new page and moves the company to exactly what was found", async () => {
    const v = verbs();
    renderRow(gone, v);
    const group = screen.getByRole("group", { name: "Hex Technologies's careers page" });

    await userEvent.click(within(group).getByRole("button", { name: "Find new careers page" }));
    expect(v.find).toHaveBeenCalledWith("hex-technologies", undefined);
    expect(await within(group).findByText(
      "Found it: 36 roles, 30 of them roles seen at Hex Technologies before.",
    )).toBeInTheDocument();

    await userEvent.click(within(group).getByRole("button", { name: "Use this careers page" }));
    expect(v.move).toHaveBeenCalledWith({ company: "hex-technologies", display: "Hex Technologies" }, hex);
  });

  it("asks for the link when nothing is found, and checks that link", async () => {
    const v = verbs(null);
    renderRow(gone, v);
    await userEvent.click(screen.getByRole("button", { name: "Find new careers page" }));
    expect(await screen.findByText(
      "Couldn't find it. Paste the link to Hex Technologies's new careers page.",
    )).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Use this careers page" })).not.toBeInTheDocument();

    await userEvent.type(screen.getByLabelText("Careers page link"), "https://jobs.ashbyhq.com/hex");
    await userEvent.click(screen.getByRole("button", { name: "Check" }));
    expect(v.find).toHaveBeenLastCalledWith("hex-technologies", "https://jobs.ashbyhq.com/hex");
    expect(await screen.findByText("That link isn't a careers page that can be read.")).toBeInTheDocument();
  });

  it("rejecting a suggestion asks for the link instead of moving", async () => {
    const v = verbs();
    renderRow(gone, v);
    await userEvent.click(screen.getByRole("button", { name: "Find new careers page" }));
    await userEvent.click(await screen.findByRole("button", { name: "Not this one" }));
    expect(screen.getByLabelText("Careers page link")).toBeInTheDocument();
    expect(v.move).not.toHaveBeenCalled();
  });

  it("can stop following the company", async () => {
    const v = verbs();
    renderRow(gone, v);
    await userEvent.click(screen.getByRole("button", { name: "Stop following" }));
    expect(v.stopFollowing).toHaveBeenCalledWith({ company: "hex-technologies", display: "Hex Technologies" });
    expect(v.find).not.toHaveBeenCalled();
  });

  it("offers nothing on any other Coverage notice", () => {
    renderRow({ ...gone, meta: { ...gone.meta, cause: "unreachable" } }, verbs());
    expect(screen.queryByRole("button", { name: "Find new careers page" })).not.toBeInTheDocument();
    expect(movedPageOf("coverage", { company: "x", cause: "empty_listing" })).toBeNull();
    expect(movedPageOf("sync_failed", { company: "x", cause: "board_missing" })).toBeNull();
  });
});

describe("what was found is said as the evidence it was found by", () => {
  it.each([
    [{ ...hex, found_by: "page" as const, roles: 11 }, "Amigo's own careers page links to it: 11 roles."],
    [{ ...hex, found_by: "address" as const, roles: 1 }, "That page lists 1 role."],
    [{ ...hex, found_by: "address" as const, roles: null }, "That page answers."],
    [{ ...hex, roles: 2, shared: 1 }, "Found it: 2 roles, 1 of them a role seen at Amigo before."],
    // With no total, "of them" has nothing to refer to, so the count stands alone.
    [{ ...hex, roles: null, shared: 30 }, "Found it: 30 roles seen at Amigo before."],
    [{ ...hex, roles: null, shared: 1 }, "Found it: 1 role seen at Amigo before."],
  ])("%o", (board, sentence) => {
    expect(foundSentence(board, "Amigo")).toBe(sentence);
  });
});
