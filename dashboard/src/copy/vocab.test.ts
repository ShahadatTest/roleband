// Product vocabulary named by slug. The backend sends slugs; these
// names come from `copy/en/vocab.ftl`, and `backend/tests/test_vocab_catalog.py`
// holds the other half: every slug the backend can send has a message.
import { afterEach, describe, expect, it } from "vitest";
import { activate } from "./activate";
import {
  domainHint, domainName, levelName, placeName, roleName, sectionTitle, sectorName, skillName, sourceName, trackName,
} from "./vocab";

afterEach(() => activate("en"));

describe("names by slug", () => {
  it("names each kind from the catalog, underscores included", () => {
    expect(domainName("ai_ml")).toBe("AI & Machine Learning");
    expect(domainHint("logistics_fulfillment")).toMatch(/^Supply chain/);
    expect(trackName("product_program")).toBe("Product & Program");
    expect(roleName("engineering_management")).toBe("Engineering Management");
    expect(sectorName("cloud-data-devtools")).toBe("Cloud, data & devtools");
    expect(sourceName("sec_edgar")).toBe("SEC EDGAR");
    expect(skillName("dotnet")).toBe(".NET");
    expect(levelName("director_plus")).toBe("Director+");
  });

  it("names the empty buckets, and shows a slug it does not know as itself", () => {
    expect(domainName(null)).toBe("Unclassified");
    expect(roleName(null)).toBe("Other");
    expect(skillName("from_a_newer_server")).toBe("from_a_newer_server");
    // A plugin's source is the plugin's to name (`source_names`), never the catalog's.
    expect(sourceName("acme.legacy")).toBe("acme.legacy");
    expect(levelName(null)).toBe("");
  });

  it("follows the active language", async () => {
    await activate("en-XA");
    expect(trackName("management")).toMatch(/^⟦Ṁàñàĝéɱéñţ/);
    expect(skillName("python")).toMatch(/^⟦Þýţĥöñ/);
  });
});

describe("places", () => {
  it("names RoleBand's own groupings from the catalog and keeps a country's or a city's own name", async () => {
    await activate("en-XA");
    expect(placeName({ slug: "dc_metro", display: "Washington, DC", kind: "metro" })).toMatch(/^⟦Ŵàšĥîñĝţöñ/);
    expect(placeName({ slug: "europe", display: "Europe", kind: "region" })).toMatch(/^⟦Éûŕöþé/);
    // A country is its own name, never the badge's short form "UK".
    expect(placeName({ slug: "uk", display: "United Kingdom", kind: "country" })).toBe("United Kingdom");
    expect(placeName({ slug: "city_5391959", display: "San Francisco", kind: "city" })).toBe("San Francisco");
  });
});

describe("section headings", () => {
  it("names the two headings RoleBand writes itself and leaves an employer's as written", async () => {
    await activate("en-XA");
    expect(sectionTitle("job_description", "Job description")).toMatch(/^⟦Ĵöƀ ðéšçŕîþţîöñ/);
    expect(sectionTitle("pay_and_benefits", "Compensation")).toMatch(/^⟦Çöɱþéñšàţîöñ/);
    // The employer's own words, even when they match RoleBand's under another key.
    expect(sectionTitle("compensation", "Compensation")).toBe("Compensation");
    expect(sectionTitle("pay_and_benefits", "Pay & Benefits")).toBe("Pay & Benefits");
    expect(sectionTitle(null, "About the team")).toBe("About the team");
  });
});
