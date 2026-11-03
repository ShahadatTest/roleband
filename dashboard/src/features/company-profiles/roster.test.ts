import { describe, expect, it } from "vitest";
import type { CompanyProfileSummary } from "../../api";
import { companyProfileSummaryFixture, profileSectorOrderFixture } from "../../test/fixtures";
import { NO_SECTOR, OTHER_SECTION, groupOf, renderOrder, rosterSections } from "./roster";

const row = (slug: string, display_name: string, over: Partial<CompanyProfileSummary> = {}): CompanyProfileSummary => ({
  ...companyProfileSummaryFixture,
  slug,
  display_name,
  sectors: [],
  in_dataset: false,
  ...over,
});

describe("rosterSections", () => {
  it("orders groups by the sector order the server sends, not by the companies' own order", () => {
    const sections = rosterSections(
      [
        row("stripe", "Stripe", { in_dataset: true, sectors: ["fintech"] }),
        row("openai", "OpenAI", { in_dataset: true, sectors: ["ai"] }),
        row("meta", "Meta", { in_dataset: true, sectors: ["faang"] }),
      ],
      profileSectorOrderFixture,
    );
    expect(sections[0].groups.map((g) => g.key)).toEqual(["sector:faang", "sector:ai", "sector:fintech"]);
  });

  it("sorts rows by name, ignoring case, whatever order the slugs arrive in", () => {
    const [other] = rosterSections(
      // Slug order (aaa, bbb, mmm, zzz) is not name order.
      [row("aaa", "zeta labs"), row("zzz", "Alpha"), row("bbb", "10xteam"), row("mmm", "beta")],
      profileSectorOrderFixture,
    );
    expect(other.groups[0].members.map((c) => c.display_name)).toEqual(["10xteam", "Alpha", "beta", "zeta labs"]);
  });

  it("puts a researched company in no sector at the end of the dataset, and an unresearched one under other", () => {
    const sections = rosterSections(
      [
        row("flexport", "Flexport", { in_dataset: true }),
        row("plain", "Plain"),
        row("google", "Google", { in_dataset: true, sectors: ["faang"] }),
      ],
      profileSectorOrderFixture,
    );
    expect(sections.map((s) => [s.key, s.groups.map((g) => g.key)])).toEqual([
      ["dataset", ["sector:faang", NO_SECTOR]],
      [OTHER_SECTION, [OTHER_SECTION]],
    ]);
  });

  it("counts a company in two sectors once, while each sector lists it", () => {
    const [dataset] = rosterSections(
      [row("microsoft", "Microsoft", { in_dataset: true, sectors: ["technology", "gaming"] })],
      profileSectorOrderFixture,
    );
    expect(dataset.count).toBe(1);
    expect(dataset.groups.map((g) => g.members.length)).toEqual([1, 1]);
    // The first group holding it is the one to unfold.
    expect(groupOf([dataset], "microsoft")).toBe("sector:technology");
    expect(renderOrder([dataset]).map((c) => c.slug)).toEqual(["microsoft", "microsoft"]);
  });

  it("keeps a sector this build does not know, after the known ones, rather than dropping its companies", () => {
    const [dataset] = rosterSections(
      [
        row("new", "Newco", { in_dataset: true, sectors: ["space"] }),
        row("meta", "Meta", { in_dataset: true, sectors: ["faang"] }),
      ],
      profileSectorOrderFixture,
    );
    expect(dataset.groups.map((g) => g.key)).toEqual(["sector:faang", "sector:space"]);
  });

  it("drops an empty section rather than drawing a heading over nothing", () => {
    expect(rosterSections([], profileSectorOrderFixture)).toEqual([]);
    expect(rosterSections([row("plain", "Plain")], profileSectorOrderFixture).map((s) => s.key)).toEqual([OTHER_SECTION]);
    expect(groupOf([], "plain")).toBeNull();
  });
});
