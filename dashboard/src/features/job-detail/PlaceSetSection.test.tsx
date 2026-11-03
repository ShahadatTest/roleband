import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { PlaceSetDetail } from "../../api";
import { api } from "../../api";
import { jobFixture } from "../../test/fixtures";
import { ToastProvider } from "../../ui/Toast";
import { fmtDate } from "../../format";
import { PlaceSetSection, siblingDifferences, statedRange, placeSetTitle } from "./PlaceSetSection";

vi.mock("../../api", () => ({ api: { placeSet: vi.fn(), reviewPlaceSet: vi.fn() } }));

const placeSet = vi.mocked(api.placeSet);
const reviewPlaceSet = vi.mocked(api.reviewPlaceSet);

const row = (id: number, city: string) => ({
  ...jobFixture,
  id,
  company: "aecom",
  title: "Project Director - Controls Analytics",
  locations: [`${city}, United Kingdom`],
});

/* Complete as `GET /api/jobs/{id}/place-set` sends it for AECOM's role. */
function inSet(label: string | null = null): PlaceSetDetail {
  return {
    job_id: 11,
    place_set: {
      id: 4,
      size: 3,
      places: ["London, UK", "St Albans, UK", "Bristol, UK"],
      employer_label: label,
      rule_version: "place_set/v1",
      members: [
        { job: row(10, "London"), is_this: false, relation: "place", same_place: false, stated_pay: null },
        { job: row(11, "St Albans"), is_this: true, relation: "place", same_place: false, stated_pay: null },
        { job: row(12, "Bristol"), is_this: false, relation: "place", same_place: false, stated_pay: null },
      ],
    },
    rejected: false,
    rejected_at: null,
  };
}

const split: PlaceSetDetail = {
  job_id: 11,
  place_set: null,
  rejected: true,
  rejected_at: "2026-10-03T12:00:00Z",
};

const Wrap = ({ children }: { children: ReactNode }) => (
  <MemoryRouter>
    <ToastProvider>{children}</ToastProvider>
  </MemoryRouter>
);

/* The role listed again at one place. This posting (11) was listed
   again in London, where 10 holds the place; 12 is in Bristol. */
function listedAgain(): PlaceSetDetail {
  return {
    job_id: 11,
    place_set: {
      id: 5,
      size: 3,
      places: ["London, UK", "Bristol, UK"],
      employer_label: null,
      rule_version: "place_set/v4",
      members: [
        { job: { ...row(10, "London"), listed_since: "2026-05-26T00:00:00Z" }, is_this: false, relation: "place", same_place: true, stated_pay: null },
        { job: { ...row(11, "London"), listed_since: "2026-08-01T00:00:00Z" }, is_this: true, relation: "relisted", same_place: false, stated_pay: null },
        { job: { ...row(12, "Bristol"), listed_since: "2026-06-02T00:00:00Z" }, is_this: false, relation: "place", same_place: false, stated_pay: null },
      ],
    },
    rejected: false,
    rejected_at: null,
  };
}

describe("PlaceSetSection", () => {
  beforeEach(() => vi.clearAllMocks());

  it("names the role's other places as links to their postings, never this one", async () => {
    placeSet.mockResolvedValue(inSet());
    const onOpen = vi.fn();
    render(<PlaceSetSection jobId={11} onOpen={onOpen} />, { wrapper: Wrap });

    const section = await screen.findByRole("region", { name: "Also listed in" });
    expect(within(section).getByText("Also listed in 2 other places")).toBeInTheDocument();
    const links = within(section).getAllByRole("link");
    expect(links.map((a) => a.textContent)).toEqual(["London, United Kingdom", "Bristol, United Kingdom"]);
    expect(within(section).queryByText(/St Albans/)).not.toBeInTheDocument();
    expect(within(section).getByText(/same description at each place/)).toBeInTheDocument();
    // A text may name its own place and that place's pay, and carry
    // that place's benefits or legal text, or a few reworded words.
    expect(within(section).getByText(/apart from the place and what comes with it/)).toBeInTheDocument();
    expect(within(section).getByText(/local compensation, benefits or legal text/)).toBeInTheDocument();

    await userEvent.click(links[1]);
    expect(onOpen).toHaveBeenCalledWith(12, "aecom");
  });

  it("says a posting at this place is the role listed again, and dates every posting", async () => {
    // Fails "every member is another place" (the header would read "2 other
    // places", naming London as somewhere else) and "a relisting looks like
    // a place" (no date, the one thing that differs).
    placeSet.mockResolvedValue(listedAgain());
    render(<PlaceSetSection jobId={11} onOpen={vi.fn()} />, { wrapper: Wrap });

    const section = await screen.findByRole("region", { name: "Also listed in" });
    expect(within(section).getByText("Also listed in 1 other place, and 2 times here")).toBeInTheDocument();
    expect(within(section).getAllByRole("link").map((a) => a.textContent)).toEqual([
      `Same place · listed ${fmtDate("2026-05-26T00:00:00Z")}`,
      `Bristol, United Kingdom · listed ${fmtDate("2026-06-02T00:00:00Z")}`,
    ]);
    expect(within(section).getByText(/second posting at the same place is the role listed again/)).toBeInTheDocument();
  });

  it("titles a role listed only at this place by how many times", () => {
    expect(placeSetTitle(0, 2)).toBe("Listed 3 times here");
    expect(placeSetTitle(2, 0)).toBe("Also listed in 2 other places");
    expect(placeSetTitle(1, 1)).toBe("Also listed in 1 other place, and 2 times here");
  });

  it("names the employer's requisition only when every posting shares it", async () => {
    placeSet.mockResolvedValue(inSet("JR101332"));
    render(<PlaceSetSection jobId={11} onOpen={vi.fn()} />, { wrapper: Wrap });
    expect(await screen.findByText(/files them all under JR101332/)).toBeInTheDocument();
  });

  it("splits the posting out on Different roles, and Undo brings the places back", async () => {
    placeSet.mockResolvedValue(inSet());
    reviewPlaceSet.mockResolvedValueOnce(split).mockResolvedValueOnce(inSet());
    const user = userEvent.setup();
    render(<PlaceSetSection jobId={11} onOpen={vi.fn()} />, { wrapper: Wrap });

    await user.click(await screen.findByRole("button", { name: "Different roles" }));
    expect(reviewPlaceSet).toHaveBeenCalledWith(11, "different");
    expect(screen.queryByRole("region", { name: "Also listed in" })).not.toBeInTheDocument();
    expect(await screen.findByText("Marked as a different role")).toBeInTheDocument();

    const toastUndo = screen
      .getAllByRole("button", { name: "Undo" })
      .find((button) => button.closest(".place-set-note") === null)!;
    await user.click(toastUndo);
    expect(reviewPlaceSet).toHaveBeenLastCalledWith(11, "pending");
    expect(await screen.findByRole("region", { name: "Also listed in" })).toBeInTheDocument();
  });

  it("keeps a way back for a posting split out earlier", async () => {
    placeSet.mockResolvedValue(split);
    reviewPlaceSet.mockResolvedValue(inSet());
    render(<PlaceSetSection jobId={11} onOpen={vi.fn()} />, { wrapper: Wrap });

    expect(await screen.findByText(/You marked this posting as a different role/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(reviewPlaceSet).toHaveBeenCalledWith(11, "pending");
    expect(await screen.findByRole("region", { name: "Also listed in" })).toBeInTheDocument();
  });

  it("says nothing for a posting in no set, and says it could not look on a failure", async () => {
    placeSet.mockResolvedValue({ job_id: 11, place_set: null, rejected: false, rejected_at: null });
    const { container, unmount } = render(<PlaceSetSection jobId={11} onOpen={vi.fn()} />, { wrapper: Wrap });
    await waitFor(() => expect(placeSet).toHaveBeenCalled());
    expect(container.querySelector(".place-set, .place-set-note")).toBeNull();
    unmount();

    placeSet.mockRejectedValue(new Error("offline"));
    render(<PlaceSetSection jobId={11} onOpen={vi.fn()} />, { wrapper: Wrap });
    expect(await screen.findByRole("status")).toHaveTextContent("Couldn't load this role's other places. Try again.");
  });

  it("states a failed verdict and keeps the places", async () => {
    placeSet.mockResolvedValue(inSet());
    reviewPlaceSet.mockRejectedValue(new Error("409 this posting is not listed with other places"));
    render(<PlaceSetSection jobId={11} onOpen={vi.fn()} />, { wrapper: Wrap });
    await userEvent.click(await screen.findByRole("button", { name: "Different roles" }));
    expect(await screen.findByText(/Couldn't record the verdict/)).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Also listed in" })).toBeInTheDocument();
  });

  it("says what a sibling states differently: its pay band, and no pay where it states none", async () => {
    const base = inSet();
    const pay = (low: number, high: number) => ({ low, high, currency: "GBP", period: "year" });
    base.place_set!.members = [
      { ...base.place_set!.members[0], stated_pay: pay(60_000, 75_000) },
      { ...base.place_set!.members[1], stated_pay: pay(52_000, 64_000) },
      { ...base.place_set!.members[2], stated_pay: null },
    ];
    placeSet.mockResolvedValue(base);
    render(<PlaceSetSection jobId={11} onOpen={vi.fn()} />, { wrapper: Wrap });
    const section = await screen.findByRole("region", { name: "Also listed in" });
    const [london, bristol] = within(section).getAllByRole("listitem");
    expect(london).toHaveTextContent(`posts ${statedRange(pay(60_000, 75_000))}`);
    expect(bristol).toHaveTextContent("posts no range");
  });

  it("says nothing about pay where a sibling states the same band", async () => {
    const base = inSet();
    const same = { low: 52_000, high: 64_000, currency: "GBP", period: "year" };
    base.place_set!.members = base.place_set!.members.map((m) => ({ ...m, stated_pay: same }));
    placeSet.mockResolvedValue(base);
    render(<PlaceSetSection jobId={11} onOpen={vi.fn()} />, { wrapper: Wrap });
    const section = await screen.findByRole("region", { name: "Also listed in" });
    expect(section).not.toHaveTextContent("states");
  });

  it("dates a sibling listed on another day than this posting", () => {
    const self = { job: { listed_since: "2026-08-01T10:00:00Z" }, stated_pay: null };
    expect(siblingDifferences({ job: { listed_since: "2026-08-01T22:00:00Z" }, stated_pay: null }, self, false)).toEqual([]);
    expect(siblingDifferences({ job: { listed_since: "2026-06-02T00:00:00Z" }, stated_pay: null }, self, false))
      .toEqual([expect.stringContaining("listed")]);
  });
});
