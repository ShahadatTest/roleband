import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { DigestPanel, parseDigest } from "./DigestPanel";

const withRouter = (ui: React.ReactElement) => <MemoryRouter>{ui}</MemoryRouter>;

const META = {
  day: "2026-09-04",
  count: 12,
  ranked: true,
  companies: ["google", "apple"],
  top: [
    { job_id: 9, company: "google", title: "Staff PM, Ads", fit: 0.71, fit_band: "Strong" },
    { job_id: 4, company: "apple", title: "TPM, Silicon", fit: 0.52, fit_band: "Good" },
  ],
};

describe("parseDigest", () => {
  it("reads a well-formed digest meta", () => {
    const d = parseDigest(META);
    expect(d).not.toBeNull();
    expect(d?.count).toBe(12);
    expect(d?.top.map((e) => e.job_id)).toEqual([9, 4]);
  });

  it("returns null rather than throwing on a row that is not a digest", () => {
    // `meta` is untyped JSONB, and most rows in the feed have none of
    // these keys. A parser that throws would take the whole list down.
    expect(parseDigest(null)).toBeNull();
    expect(parseDigest(undefined)).toBeNull();
    expect(parseDigest({})).toBeNull();
    expect(parseDigest({ sync_state: "running" })).toBeNull();
    expect(parseDigest({ count: 3 })).toBeNull();
    expect(parseDigest({ count: "3", top: [] })).toBeNull();
  });

  it("skips malformed entries instead of rendering a broken row", () => {
    const d = parseDigest({ count: 2, top: [{ job_id: 1, title: "Real" }, { title: "no id" }, 7, null] });
    expect(d?.top).toHaveLength(1);
    expect(d?.top[0].title).toBe("Real");
  });
});

describe("DigestPanel", () => {
  it("lists the day's roles as links that open the job", async () => {
    const onOpenJob = vi.fn();
    const digest = parseDigest(META)!;
    render(withRouter(<DigestPanel digest={digest} onOpenJob={onOpenJob} />));

    const first = screen.getByRole("link", { name: /Staff PM, Ads/ });
    // A role has a URL: the anchor is what buys Enter, the status-bar
    // destination and cmd-click. A button would give up all three.
    expect(first).toHaveAttribute("href", "/company/google/job/9");

    await userEvent.click(first);
    expect(onOpenJob).toHaveBeenCalledWith(9, "google");
  });

  it("shows the fit band per role so the ranking is legible", () => {
    render(withRouter(<DigestPanel digest={parseDigest(META)!} onOpenJob={vi.fn()} />));
    expect(screen.getByText("Strong")).toBeInTheDocument();
    expect(screen.getByText("Good")).toBeInTheDocument();
  });

  it("accounts for the roles it did not name", () => {
    // The digest counts the whole day but names only the top few; silently
    // dropping the remainder would misreport the day.
    render(withRouter(<DigestPanel digest={parseDigest(META)!} onOpenJob={vi.fn()} />));
    expect(screen.getByText(/10 more roles opened today/)).toBeInTheDocument();
  });

  it("says so when there is no intent signal to rank by", () => {
    const digest = parseDigest({ ...META, ranked: false, count: 2 })!;
    render(withRouter(<DigestPanel digest={digest} onOpenJob={vi.fn()} />));
    expect(screen.getByText(/Unranked/)).toBeInTheDocument();
  });

  it("does not claim a remainder when it named every role", () => {
    const digest = parseDigest({ ...META, count: 2 })!;
    render(withRouter(<DigestPanel digest={digest} onOpenJob={vi.fn()} />));
    expect(screen.queryByText(/more role/)).not.toBeInTheDocument();
  });
});
