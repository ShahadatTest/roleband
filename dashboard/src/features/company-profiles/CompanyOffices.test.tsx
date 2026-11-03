import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { CompanyLocation } from "../../api";
import { CompanyOffices, groupByCountry } from "./CompanyOffices";

const loc = (
  city: string,
  open_count: number,
  country: string | null,
  is_hq = false,
): CompanyLocation => ({ city, open_count, country, is_hq, groups: [] });

/* Shaped like a large employer's payload: one dominant country whose tail is
   the whole problem, a couple of small ones, and a city the taxonomy could not
   place. */
const locations: CompanyLocation[] = [
  loc("Seattle, WA", 308, "united_states", true),
  loc("Bellevue, WA", 177, "united_states"),
  loc("Arlington, VA", 97, "united_states"),
  loc("Nashville, TN", 95, "united_states"),
  loc("Austin, TX", 87, "united_states"),
  loc("New York, NY", 81, "united_states"),
  loc("Boston, MA", 40, "united_states"),
  loc("Denver, CO", 12, "united_states"),
  loc("London", 9, "uk"),
  loc("Leicester", 4, "uk"),
  loc("Reykjavik, Iceland", 1, "iceland"),
  loc("Wilmington, DE", 4, null),
];

describe("groupByCountry", () => {
  it("orders countries by open roles, not by city count or name", () => {
    // Iceland would come first alphabetically; a 3-city country with 3 roles
    // would come first by city count. Neither is the question a job seeker asks.
    const out = groupByCountry([
      loc("Reykjavik, Iceland", 1, "iceland"),
      loc("Dublin", 1, "ireland"),
      loc("Cork", 1, "ireland"),
      loc("Galway", 1, "ireland"),
      loc("Seattle, WA", 300, "united_states"),
    ]);
    expect(out.map((s) => s.country)).toEqual(["united_states", "ireland", "iceland"]);
    expect(out[0].openTotal).toBe(300);
  });

  it("sinks unmapped cities to the bottom however many roles they hold", () => {
    const out = groupByCountry([
      loc("Reykjavik, Iceland", 1, "iceland"),
      loc("Wilmington, DE", 500, null),
    ]);
    expect(out.map((s) => s.label)).toEqual(["Iceland", "Location not mapped"]);
  });

  it("pins the HQ to the top of its own country, not the whole list", () => {
    const out = groupByCountry([
      loc("Cupertino, CA", 5, "united_states"),
      loc("Austin, TX", 90, "united_states", true),
      loc("London", 300, "uk"),
    ]);
    expect(out[0].country).toBe("uk");
    expect(out[1].cities[0].city).toBe("Austin, TX");
  });
});

describe("CompanyOffices", () => {
  it("groups cities under their country and caps each section at six", () => {
    render(<CompanyOffices locations={locations} />);

    const us = screen.getByRole("list", { name: "Offices in United States" });
    // 8 US cities, 6 shown.
    expect(within(us).getAllByRole("listitem")).toHaveLength(6);
    expect(within(us).getByText("Seattle, WA")).toBeInTheDocument();
    expect(within(us).queryByText("Denver, CO")).toBeNull();

    // Small countries are not truncated, and the unmapped city is rendered
    // rather than dropped.
    const uk = screen.getByRole("list", { name: "Offices in UK" });
    expect(within(uk).getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByText("Wilmington, DE")).toBeInTheDocument();
  });

  it("reveals and re-hides a country's tail", async () => {
    const user = userEvent.setup();
    render(<CompanyOffices locations={locations} />);

    await user.click(screen.getByRole("button", { name: "Show 2 more in United States" }));
    const us = () => screen.getByRole("list", { name: "Offices in United States" });
    expect(within(us()).getAllByRole("listitem")).toHaveLength(8);
    expect(within(us()).getByText("Denver, CO")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Show fewer" }));
    expect(within(us()).getAllByRole("listitem")).toHaveLength(6);
  });

  it("narrows to the selected countries and drops the rest of the sections", async () => {
    const user = userEvent.setup();
    render(<CompanyOffices locations={locations} />);

    await user.click(screen.getByRole("button", { name: "Filter by country" }));
    await user.click(screen.getByRole("option", { name: /^UK/ }));

    expect(screen.getByRole("list", { name: "Offices in UK" })).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Offices in United States" })).toBeNull();
    expect(screen.queryByText("Wilmington, DE")).toBeNull();
    expect(screen.getByText("2 of 12 cities")).toBeInTheDocument();
  });

  it("searching reaches a city hidden in the tail without expanding by hand", async () => {
    const user = userEvent.setup();
    render(<CompanyOffices locations={locations} />);

    // Denver is US city #8 — invisible until the search finds it. This is the
    // whole point of the search box: the cap must not make a city unreachable.
    expect(screen.queryByText("Denver, CO")).toBeNull();
    await user.type(screen.getByLabelText("Search cities"), "denver");

    expect(screen.getByText("Denver, CO")).toBeInTheDocument();
    // Sections that match nothing are removed, not shown empty.
    expect(screen.queryByRole("list", { name: "Offices in UK" })).toBeNull();
    expect(screen.getByText("1 of 12 cities")).toBeInTheDocument();
  });

  it("says so when a search matches no office at all", async () => {
    const user = userEvent.setup();
    render(<CompanyOffices locations={locations} />);

    await user.type(screen.getByLabelText("Search cities"), "atlantis");
    expect(screen.getByText("No office matches that search.")).toBeInTheDocument();
  });
});
