import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { LineageDetail } from "../../api";
import { api } from "../../api";
import { activate } from "../../copy/activate";
import { duplicateProposalFixture, jobDetailRowFixture } from "../../test/fixtures";
import { msg } from "../../test/msg";
import { LineageStack } from "./LineageStack";

vi.mock("../../api", () => ({ api: { lineage: vi.fn() } }));

const mockLineage = (d: LineageDetail) =>
  vi.mocked(api.lineage).mockResolvedValue(d);

/* A two-posting stack, complete as `GET /api/jobs/{id}/lineage` sends it. */
function detail(): LineageDetail {
  const posting = { lineage_id: 10, lineage_size: null };
  const original = jobDetailRowFixture({ ...posting, id: 1, req_id: "A", title: "Staff SWE", lineage_seq: 1, lineage_role: "original" });
  const repost = jobDetailRowFixture({ ...posting, id: 2, req_id: "B", title: "Staff SWE, Inference", lineage_seq: 2, lineage_role: "repost" });
  return {
    lineage_id: 10,
    root_job_id: 1,
    company: "openai",
    size: 2,
    open_members: 2,
    first_seen: "2026-01-01T00:00:00Z",
    last_seen: "2026-07-12T00:00:00Z",
    members: [
      { seq: 1, role: "original", job: original, link: null, diff_vs_prev: null },
      {
        seq: 2,
        role: "repost",
        job: repost,
        link: duplicateProposalFixture({
          id: 5, job_id: 2, prior_job_id: 1, method: "title+embedding", confidence: "auto", score: 0.94, gap_days: 12,
        }),
        diff_vs_prev: { title: { from: "Staff SWE", to: "Staff SWE, Inference" } },
      },
    ],
  };
}

describe("LineageStack", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows the posting count and opens on the newest member", async () => {
    mockLineage(detail());
    render(<LineageStack jobId={2} />);
    expect(await screen.findByText("2 postings of this role")).toBeInTheDocument();
    // Newest (repost) selected by default -> its title + its diff show.
    expect(screen.getByRole("heading", { name: "Staff SWE, Inference" })).toBeInTheDocument();
    expect(screen.getByText("Title changed")).toBeInTheDocument();
  });

  it("pages back to the earlier posting", async () => {
    mockLineage(detail());
    const user = userEvent.setup();
    render(<LineageStack jobId={2} />);
    await screen.findByText("2 postings of this role");
    await user.click(screen.getByRole("button", { name: "Previous posting" }));
    expect(screen.getByRole("heading", { name: "Staff SWE" })).toBeInTheDocument();
    // The original posting has no diff.
    expect(screen.queryByText("Title changed")).not.toBeInTheDocument();
  });

  it("renders nothing for a standalone job", async () => {
    mockLineage({ lineage_id: null, size: 1, members: [] });
    const { container } = render(<LineageStack jobId={9} />);
    await waitFor(() => expect(api.lineage).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});

describe("LineageStack in the reader's words", () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => activate("en"));

  it("says what a posting is and its status in Spanish, never the API's codes", async () => {
    await activate("es");
    mockLineage(detail());
    render(<LineageStack jobId={2} />);
    await screen.findByText(msg("role-lineage-stack-postings-of-this-role", { size: 2 }));

    const reposted = msg("role-lineage-stack-role", { role: "repost" });
    const head = document.querySelector(".lineage-member-head") as HTMLElement;
    expect(within(head).getByText(msg("role-lineage-stack-badge", { choice: "yes", role: reposted, seq: 2 }))).toBeInTheDocument();
    expect(within(head).getByText(msg("role-job-status-open"))).toBeInTheDocument();
    expect(head).not.toHaveTextContent(/\b(repost|open)\b/);

    const dots = within(screen.getByRole("list", { name: msg("role-lineage-stack-postings") })).getAllByRole("button");
    expect(dots.map((dot) => dot.getAttribute("aria-label"))).toEqual([
      msg("role-lineage-stack-posting", { choice: "yes", seq: 1, role: msg("role-lineage-stack-role", { role: "original" }) }),
      msg("role-lineage-stack-posting", { choice: "yes", seq: 2, role: reposted }),
    ]);
  });

  it("reads a posting with no part or place by its position, never as null", async () => {
    const d = detail();
    d.members = d.members.map((m) => ({ ...m, role: null, seq: null }));
    mockLineage(d);
    render(<LineageStack jobId={2} />);
    await screen.findByText(msg("role-lineage-stack-postings-of-this-role", { size: 2 }));

    const dots = within(screen.getByRole("list", { name: msg("role-lineage-stack-postings") })).getAllByRole("button");
    expect(dots.map((dot) => dot.getAttribute("aria-label"))).toEqual([
      msg("role-lineage-stack-posting", { choice: "no", seq: 1, role: "" }),
      msg("role-lineage-stack-posting", { choice: "no", seq: 2, role: "" }),
    ]);
    expect(dots.map((dot) => dot.getAttribute("title"))).toEqual([
      msg("role-lineage-stack-badge", { choice: "no", seq: 1, role: "" }),
      msg("role-lineage-stack-badge", { choice: "no", seq: 2, role: "" }),
    ]);
    const head = document.querySelector(".lineage-member-head") as HTMLElement;
    expect(within(head).getByText(msg("role-lineage-stack-badge", { choice: "no", seq: 2, role: "" }))).toBeInTheDocument();
    const named = [...document.querySelectorAll("[aria-label], [title]")]
      .flatMap((e) => [e.getAttribute("aria-label"), e.getAttribute("title")]);
    expect([document.body.textContent, ...named].join(" ")).not.toMatch(/null/);
  });
});
