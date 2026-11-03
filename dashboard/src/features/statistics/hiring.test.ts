import { describe, expect, it } from "vitest";
import type { HiringCompany } from "../../api";
import { matchCompanies, topCompanies } from "./hiring";

const c = (company: string, open: number, newToday = 0, closedToday = 0): HiringCompany => ({
  company, open, new_today: newToday, closed_today: closedToday,
});

const companies = [c("a", 9), c("b", 7, 2), c("c", 5), c("d", 3, 1, 1), c("e", 0, 0, 4)];

describe("topCompanies", () => {
  it("keeps the server's order and folds the rest into one row that counts it", () => {
    const { rows, rest, total } = topCompanies(companies, 2);
    expect(rows.map((x) => x.company)).toEqual(["a", "b"]);
    expect(rest).toEqual({ companies: 2, open: 8, newToday: 1, closedToday: 1 });
    expect(total).toBe(4);
  });

  it("drops a company with nothing open: today's closings alone are not hiring", () => {
    expect(topCompanies(companies).rows.map((x) => x.company)).not.toContain("e");
  });

  it("folds nothing when every company fits", () => {
    expect(topCompanies(companies, 15)).toEqual({ rows: companies.slice(0, 4), rest: null, total: 4 });
  });
});

describe("matchCompanies", () => {
  const name = (slug: string) => ({ a: "Nestlé", b: "Société Générale", c: "Acme" })[slug] ?? slug;
  it("matches by display name, ignoring case and accents, and keeps everything for an empty query", () => {
    expect(matchCompanies(companies, "nestle", name).map((x) => x.company)).toEqual(["a"]);
    expect(matchCompanies(companies, "GÉNÉ", name).map((x) => x.company)).toEqual(["b"]);
    expect(matchCompanies(companies, "  ", name)).toHaveLength(5);
  });
});
