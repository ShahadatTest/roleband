import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, type Job, type JobDetail, type ListingHistory } from "../../api";
import { jobFixture } from "../../test/fixtures";
import { ListingAge, eventLine } from "./ListingAge";

vi.mock("../../api", () => ({ api: { jobHistory: vi.fn() } }));

/* One age, with where it counts from, and the history only when
   asked for. The fixture is the shape the history route serves: a posting the
   employer dated before we saw it, that went away and came back, whose employer
   later moved its date, with one earlier posting of the same role and one
   possible match nobody has confirmed. */

const history: ListingHistory = {
  headline: { since: "2026-04-12T00:00:00Z", days: 170, basis: "employer" },
  role: { since: "2026-01-12T00:00:00Z", days: 260, postings: 2 },
  events: [
    { at: "2026-01-12T00:00:00Z", kind: "earlier_posting", job_id: 77, req_id: "REQ-1182", title: "Staff PM", until: "2026-03-03T00:00:00Z", link: "confirmed", from_at: null, to_at: null, field: null, count: null },
    { at: "2026-04-12T00:00:00Z", kind: "employer_published", job_id: null, req_id: null, title: null, until: null, link: null, from_at: null, to_at: null, field: null, count: null },
    { at: "2026-07-23T00:00:00Z", kind: "first_seen", job_id: null, req_id: null, title: null, until: null, link: null, from_at: null, to_at: null, field: null, count: null },
    { at: "2026-08-09T00:00:00Z", kind: "closed", job_id: null, req_id: null, title: null, until: null, link: null, from_at: null, to_at: null, field: null, count: null },
    { at: "2026-08-14T00:00:00Z", kind: "reopened", job_id: null, req_id: null, title: null, until: null, link: null, from_at: null, to_at: null, field: null, count: null },
    { at: "2026-09-02T00:00:00Z", kind: "redated", job_id: null, req_id: null, title: null, until: null, link: null, from_at: "2026-04-12T00:00:00Z", to_at: "2026-09-02T00:00:00Z", field: null, count: null },
    { at: "2026-09-20T00:00:00Z", kind: "edited", job_id: null, req_id: null, title: null, until: null, link: null, from_at: null, to_at: null, field: "title", count: 2 },
    { at: "2026-09-29T00:00:00Z", kind: "last_seen", job_id: null, req_id: null, title: null, until: null, link: null, from_at: null, to_at: null, field: null, count: null },
  ],
  unconfirmed: [{ link_id: 9, job_id: 88, req_id: "REQ-1305", title: "Staff PM", listed_since: "2026-05-01T00:00:00Z" }],
};

const job: Job = {
  ...jobFixture,
  listed_since: "2026-04-12T00:00:00Z",
  listed_days: 170,
  listed_basis: "employer",
  role_since: "2026-01-12T00:00:00Z",
  role_days: 260,
  role_postings: 2,
};

const renderAge = (props: Partial<JobDetail> = {}, onOpen = vi.fn(), onShowPostings = vi.fn()) =>
  render(
    <MemoryRouter>
      <dl>
        <ListingAge job={{ ...job, ...props }} column={null} onOpen={onOpen} onShowPostings={onShowPostings} />
      </dl>
    </MemoryRouter>,
  );

const read = vi.mocked(api.jobHistory);

beforeEach(() => {
  read.mockReset();
  read.mockResolvedValue(history);
});

describe("ListingAge", () => {
  it("says the one age and where it counts from, and reads no history until asked", () => {
    renderAge();
    expect(screen.getByText("170 days")).toBeVisible();
    expect(screen.getByText(/^since .*, the employer's date$/)).toBeVisible();
    expect(screen.getByText(/^First listed .* · 2 postings$/)).toBeVisible();
    expect(read).not.toHaveBeenCalled();
  });

  it("says when the age counts from our own sighting, and has no Role row for a posting alone", () => {
    renderAge({ listed_basis: "sighting", role_since: null, role_days: null, role_postings: null });
    expect(screen.getByText(/^since .*, when first seen$/)).toBeVisible();
    expect(screen.queryByText("Role")).toBeNull();
  });

  it("opens the history once, marks the start, and never counts a later date or an unconfirmed match", async () => {
    const onOpen = vi.fn();
    const user = userEvent.setup();
    renderAge({}, onOpen);
    await user.click(screen.getByRole("button", { name: "History" }));
    const panel = await screen.findByRole("dialog", { name: "Listing history" });
    const events = await within(panel).findByRole("list", { name: "Events" });
    expect(read).toHaveBeenCalledTimes(1);
    expect(events).toHaveTextContent("Published by the employer · the start");
    expect(events).toHaveTextContent("First seen");
    expect(events).not.toHaveTextContent("First seen · the start");
    expect(events).toHaveTextContent(/Employer changed its date to .* · never the start/);
    expect(events).toHaveTextContent("Came back, same requisition");
    expect(events).toHaveTextContent("Title changed 2 times");
    expect(panel).toHaveTextContent("Possibly the same role: REQ-1305, not counted until confirmed.");
    expect(within(panel).getByRole("button", { name: "Review" })).toBeVisible();
    // An earlier posting of the role opens where it is named.
    await user.click(within(events).getByRole("button", { name: /Earlier posting REQ-1182 listed, closed/ }));
    expect(onOpen).toHaveBeenCalledWith(77);
  });

  it("shows this cover's postings, never another page's, and closes the history", async () => {
    // A Job detail opened over another one leaves the page behind it in the
    // document, posting stack and all, first in document order. The stack is
    // the cover's to scroll to, never looked up.
    const behind = document.createElement("section");
    behind.className = "lineage-stack";
    behind.scrollIntoView = vi.fn();
    document.body.prepend(behind);
    try {
      const onShowPostings = vi.fn();
      const user = userEvent.setup();
      renderAge({}, vi.fn(), onShowPostings);
      await user.click(screen.getByRole("button", { name: "History" }));
      const panel = await screen.findByRole("dialog", { name: "Listing history" });
      await user.click(await within(panel).findByRole("button", { name: "Compare the postings" }));

      expect(onShowPostings).toHaveBeenCalledTimes(1);
      expect(behind.scrollIntoView).not.toHaveBeenCalled();
      expect(screen.queryByRole("dialog", { name: "Listing history" })).toBeNull();
    } finally {
      behind.remove();
    }
  });

  it("says a failed read plainly and offers to read it again", async () => {
    read.mockRejectedValueOnce(new Error("503"));
    const user = userEvent.setup();
    renderAge();
    await user.click(screen.getByRole("button", { name: "History" }));
    const panel = await screen.findByRole("dialog", { name: "Listing history" });
    expect(await within(panel).findByText(/Couldn't read the history/)).toBeVisible();
    await user.click(within(panel).getByRole("button", { name: "Retry" }));
    expect(await within(panel).findByRole("list", { name: "Events" })).toBeVisible();
  });
});

describe("eventLine", () => {
  it("marks the start on whichever evidence the headline counts from", () => {
    const published = history.events[1];
    const seen = history.events[2];
    expect(eventLine(published, "employer").note).toBe("the start");
    expect(eventLine(seen, "employer").note).toBeUndefined();
    expect(eventLine(published, "sighting").note).toBeUndefined();
    expect(eventLine(seen, "sighting").note).toBe("the start");
  });

  it("names another posting by its requisition or title, and reads whole without either", () => {
    const earlier = history.events.find((event) => event.kind === "earlier_posting")!;
    expect(eventLine(earlier, "employer").text).toBe("Earlier posting REQ-1182 listed, closed Mar 3, 2026");
    // With neither, no placeholder is spliced in ("Earlier posting another posting listed").
    const unnamed = { ...earlier, req_id: null, title: null };
    expect(eventLine(unnamed, "employer").text).toBe("An earlier posting was listed, closed Mar 3, 2026");
    expect(eventLine({ ...unnamed, until: null }, "employer").text).toBe("An earlier posting was listed");
    const later = { ...unnamed, kind: "later_posting" as const };
    expect(eventLine(later, "employer").text).toBe("Reposted");
    expect(eventLine({ ...later, req_id: "REQ-1305" }, "employer").text).toBe("Reposted as REQ-1305");
  });
});
