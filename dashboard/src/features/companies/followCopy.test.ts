import { activate } from "../../copy/activate";
import { wordsLanguage } from "../../copy/runtime";
import { describe, expect, it } from "vitest";
import type { CompanyDiscoveryCompany } from "../../api";
import { SITE_WALL_SENTENCE, awaitingConsent, consentsFor, followCopy, wallSentence } from "./followCopy";
import type { SectorGroup } from "./companiesModel";

/* The follow confirmations' words are the consent a walled company is
 * collected under: what is recorded must be what was shown. */

const company = (over: Partial<CompanyDiscoveryCompany>): CompanyDiscoveryCompany => ({
  slug: "acme", display: "Acme", careers_url: null, sectors: ["ai"], aliases: [],
  connector_state: "ready", parked_reason: null, selectable: true,
  tracked: false, enabled: false, visible: true, builtin: false, curated: false, directory: false,
  wall: null, consented: false, status: null, ...over,
});

const deepmind = company({ slug: "deepmind", display: "DeepMind", wall: "robots" });
const stripe = company({ slug: "stripe", display: "Stripe" });
const none = { volume: null, seconds: null } as const;

describe("follow confirmations and the consent they record", () => {
  it("records exactly the words shown, once per walled company it starts to collect", () => {
    const pending = { kind: "include" as const, companies: [deepmind, stripe], estimate: none };
    const copy = followCopy(pending);
    expect(copy).toEqual({
      title: "Follow the whole list?",
      paragraphs: [
        "Your radar starts with a curated list of well-known companies, so your first roles come from employers you know.",
        "More companies bring more roles, and each scan takes longer.",
        "Some of these companies limit automated collection on their careers sites. " +
          "By following them, you choose to collect their public postings.",
        "You can unfollow any company in Settings › Followed companies.",
      ],
      safe: "Keep curated list",
      act: "Follow all 2",
    });
    expect(consentsFor(pending)).toEqual([
      { slug: "deepmind", locale: "en", text: [copy.title, ...copy.paragraphs].join("\n\n") },
    ]);
  });

  it("a sector's Follow all shows and records the same consent sentence as the whole list", () => {
    const group = { slug: "ai", display: "AI", members: [deepmind, stripe], connectable: [deepmind, stripe],
      bulk: [deepmind, stripe], trackedCount: 0 } as unknown as SectorGroup;
    const pending = { kind: "sector" as const, group, companies: [deepmind, stripe], estimate: none };
    const copy = followCopy(pending);
    expect(copy.paragraphs[copy.paragraphs.length - 1]).toBe(
      "Some of these companies limit automated collection on their careers sites. " +
        "By following them, you choose to collect their public postings.",
    );
    expect(consentsFor(pending)).toEqual([
      { slug: "deepmind", locale: "en", text: [copy.title, ...copy.paragraphs].join("\n\n") },
    ]);
    const clear = { ...pending, companies: [stripe], group: { ...group, bulk: [stripe] } };
    expect(followCopy(clear).paragraphs.join(" ")).not.toContain("automated collection");
  });

  it("names no wall and records nothing when the set has no unconsented walled company", () => {
    const consented = { ...deepmind, consented: true };
    const pending = { kind: "include" as const, companies: [consented, stripe], estimate: none };
    expect(followCopy(pending).paragraphs).toEqual([
      "Your radar starts with a curated list of well-known companies, so your first roles come from employers you know.",
      "More companies bring more roles, and each scan takes longer.",
      "You can unfollow any company in Settings › Followed companies.",
    ]);
    expect(consentsFor(pending)).toEqual([]);
    expect(awaitingConsent([consented, stripe])).toEqual([]);
  });

  it("states the site's reason, names no company, and says nothing when nothing walls it", () => {
    // Every wall is the SITE's. A company the product itself leaves
    // to the user is not walled at all: it never reaches a dialog, so there is
    // no sentence to write for it.
    for (const site of [deepmind, { ...deepmind, wall: "bot_wall" as const }]) {
      expect(wallSentence(site)).toBe(SITE_WALL_SENTENCE);
    }
    expect(SITE_WALL_SENTENCE).not.toMatch(/DeepMind/);
    expect(wallSentence(stripe)).toBeNull();
  });

  it("an individual walled follow shows the reason and what following means", () => {
    const copy = followCopy({ kind: "walled-follow", company: deepmind });
    expect(copy.title).toBe("Follow DeepMind?");
    expect(copy.paragraphs).toEqual([
      SITE_WALL_SENTENCE,
      "By following, you choose to collect DeepMind's public job listings. " +
        "You can unfollow at any time, and collection stops.",
    ]);
  });

  it("warns once about the walled companies in Follow the whole list, naming none of them", () => {
    const wise = company({ slug: "wise", display: "Wise", wall: "bot_wall" });
    const pending = { kind: "include" as const, companies: [deepmind, wise, stripe], estimate: none };
    const paragraphs = followCopy(pending).paragraphs;
    expect(paragraphs.filter((line) => line.includes("limit automated collection"))).toHaveLength(1);
    expect(paragraphs.join(" ")).not.toMatch(/DeepMind|Wise|\d/);
    // Both are consented to, in the words shown.
    expect(consentsFor(pending).map((entry) => entry.slug)).toEqual(["deepmind", "wise"]);
  });

  it("the list and the other companies is one question that names no number and no company, and consents for each walled one", () => {
    const wise = company({ slug: "wise", display: "Wise", wall: "bot_wall" });
    const pending = { kind: "everything" as const, companies: [deepmind, wise, stripe] };
    const copy = followCopy(pending);
    expect(copy).toEqual({
      title: "Follow the other companies too?",
      paragraphs: [
        "Your radar adds the other companies to the ones on the list.",
        "Some of these companies' careers sites limit automated collection. " +
          "By picking this, you choose to collect their public postings.",
        "With more companies, scans take longer.",
        "Change it any time in Settings.",
      ],
      safe: "Cancel",
      act: "Follow them",
    });
    expect([copy.title, ...copy.paragraphs].join(" ")).not.toMatch(/\d|DeepMind|Wise|Stripe/);
    const text = [copy.title, ...copy.paragraphs].join("\n\n");
    expect(consentsFor(pending)).toEqual([
      { slug: "deepmind", locale: "en", text },
      { slug: "wise", locale: "en", text },
    ]);
  });

  it("the list and the other companies without a walled company to follow says nothing of walls and consents to nothing", () => {
    for (const companies of [[stripe], [{ ...deepmind, consented: true }, stripe], []]) {
      const pending = { kind: "everything" as const, companies };
      expect(followCopy(pending).paragraphs.join(" ")).not.toMatch(/limit|collect/);
      expect(consentsFor(pending)).toEqual([]);
    }
  });

  it("an individual follow consents; an unfollow and a bulk unfollow consent to nothing", () => {
    const follow = { kind: "walled-follow" as const, company: deepmind };
    expect(followCopy(follow)).toMatchObject({ title: "Follow DeepMind?", safe: "Cancel", act: "Follow DeepMind" });
    expect(consentsFor(follow).map((entry) => entry.slug)).toEqual(["deepmind"]);
    expect(consentsFor({ kind: "walled-unfollow", company: deepmind })).toEqual([]);
    expect(consentsFor({ kind: "exclude", companies: [deepmind] })).toEqual([]);
  });
});

it("records the rendered consent snapshot even after the locale changes", async () => {
  await activate("es");
  const pending = { kind: "walled-follow" as const, company: deepmind };
  const shown = { copy: followCopy(pending), locale: wordsLanguage() };
  await activate("en");
  expect(consentsFor(pending, shown)).toEqual([{ slug: "deepmind", locale: "es", text: [shown.copy.title,...shown.copy.paragraphs].join("\n\n") }]);
});
