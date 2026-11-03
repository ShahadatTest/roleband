import { describe, expect, it } from "vitest";
import type { ScopeLocation } from "../../../api";
import { UNIONS } from "../../../unions.gen";
import {
  ACCOUNTABLE, ANYWHERE, ROLE_QUESTIONS, TRACK_SLUGS, accountablePhrase, anywhereSlugs, answersFrom, answersWire, asAny, basesOf, canChoose,
  childNoun, childState, coveredBy, exceptedIn, exceptPhrase, exceptionsUnder, membersPhrase, unionOf, withChildPlaces,
  withChildToggled,
  domainsOf, excludedOf, interestsRows, joinOr, levelPhrase, linesFrom, namedThenCounted, placeProse, projectAnswers, reachesOf,
  rowOn, rowsPicked, sameAnswers, wherePhrase, whichRolesPhrase, withAnswer, withBase, withLine, withReach, withRow, withoutBase, withoutLine,
  type AnswerRoles, type TrackSlug,
} from "./walkModel";
import { buildScopeIndex, countUnderScope, type ScopeAxesSelection } from "../scopeCells";

/* The families the backend classifies (taxonomy/roles.py).
   The walk must be able to name every one of them under at least one answer,
   or a role the radar can find becomes one the profile cannot ask for. */
const FAMILIES = [
  "engineering_management", "product_management", "technical_program_management", "program_management",
  "ml_ai_research", "data_science", "data_engineering", "security_engineering", "infrastructure_sre",
  "hardware_engineering", "software_engineering", "design_ux", "developer_relations", "solutions_sales_eng",
  "technical_writing", "it_support", "sales_business_development", "customer_success",
  "marketing_communications", "business_operations_strategy", "finance_accounting", "people_recruiting",
  "legal_policy", "operations_facilities",
];

describe("the four answers", () => {
  it("are the four career tracks, each with a forward-facing label and examples", () => {
    expect(TRACK_SLUGS).toEqual(["management", "product_program", "technical", "business_customer"]);
    for (const answer of ACCOUNTABLE) {
      expect(answer.label).not.toMatch(/\(IC\)|Management \//);
      expect(answer.examples.length).toBeGreaterThan(10);
    }
  });

  /* What the track classifier files under each kind, per family: the
     families holding at least 1% of their kind, and the ones it never files
     there. */
  const HOLDS: Record<TrackSlug, string[]> = {
    management: [
      "business_operations_strategy", "customer_success", "data_science", "design_ux", "engineering_management",
      "finance_accounting", "hardware_engineering", "infrastructure_sre", "legal_policy", "marketing_communications",
      "ml_ai_research", "sales_business_development", "security_engineering", "software_engineering", "solutions_sales_eng",
    ],
    product_program: ["product_management", "technical_program_management", "program_management"],
    technical: [
      "data_engineering", "data_science", "design_ux", "hardware_engineering", "infrastructure_sre", "it_support",
      "ml_ai_research", "security_engineering", "software_engineering", "solutions_sales_eng",
    ],
    business_customer: [
      "business_operations_strategy", "customer_success", "finance_accounting", "legal_policy",
      "marketing_communications", "people_recruiting", "sales_business_development",
    ],
  };
  const NEVER: Record<TrackSlug, string[]> = {
    management: ["product_management", "technical_program_management", "program_management"],
    product_program: FAMILIES.filter((family) => !HOLDS.product_program.includes(family)),
    technical: ["engineering_management", "product_management", "technical_program_management", "program_management"],
    business_customer: ["solutions_sales_eng", "developer_relations", "engineering_management", "software_engineering"],
  };

  it("offer, under each kind, every family the classifier files there, and no family it never does", () => {
    for (const track of TRACK_SLUGS) {
      const named = ROLE_QUESTIONS[track].rows.flatMap((row) => [...row.families]);
      for (const family of HOLDS[track]) expect(named, `${family} under ${track} cannot be picked`).toContain(family);
      for (const family of NEVER[track]) expect(named, `${track} offers ${family}, which never occurs there`).not.toContain(family);
      expect(new Set(named).size, `${track} books a family twice`).toBe(named.length);
      for (const row of ROLE_QUESTIONS[track].rows) {
        if (ROLE_QUESTIONS[track].crafts) expect(ROLE_QUESTIONS[track].crafts).toContain(row.craft);
      }
    }
    // Every classified family is pickable under some kind.
    const anywhere = new Set(TRACK_SLUGS.flatMap((track) => ROLE_QUESTIONS[track].rows.flatMap((row) => [...row.families])));
    for (const family of FAMILIES) expect(anywhere, `${family} is unreachable from the walk`).toContain(family);
    // Specialists never see more than six rows at a time: the craft splits them.
    for (const craft of ROLE_QUESTIONS.technical.crafts ?? []) {
      expect(ROLE_QUESTIONS.technical.rows.filter((row) => row.craft === craft).length).toBeLessThanOrEqual(6);
    }
  });
});

describe("answers: which roles of each kind", () => {
  it("adds an answer with nothing ticked, narrows on the first tick, and gives every role back on the last untick", () => {
    const lead = withAnswer(new Map(), "management", true);
    expect(lead.get("management")).toBe("any");
    // Nothing ticked: no card is on, and every role of the kind is kept.
    expect(rowsPicked("management", "any")).toEqual([]);
    expect(ROLE_QUESTIONS.management.rows.some((row) => rowOn("any", row))).toBe(false);
    const engineers = withRow(lead, "management", "engineers", true);
    expect(rowsPicked("management", engineers.get("management")!).map((row) => row.key)).toEqual(["engineers"]);
    const again = withRow(engineers, "management", "designers", true);
    expect(rowsPicked("management", again.get("management")!).map((row) => row.key)).toEqual(["engineers", "designers"]);
    const back = withRow(withRow(again, "management", "designers", false), "management", "engineers", false);
    expect(back.get("management")).toBe("any");
    expect(withAnswer(again, "management", false).has("management")).toBe(false);
  });

  it("a click under one answer never touches another", () => {
    const both = withRow(withAnswer(withAnswer(new Map(), "management", true), "technical", true), "technical", "design", true);
    expect(both.get("management")).toBe("any");
    const narrowed = withRow(both, "management", "designers", true);
    // Hands-on keeps exactly what it had, design included or not, whatever Leading does.
    expect(sameAnswers(new Map([["technical", narrowed.get("technical")!]]), new Map([["technical", both.get("technical")!]]))).toBe(true);
  });

  it("survives its wire form, compares by content, and projects to the flat lists", () => {
    const answers = new Map<string, AnswerRoles>([["management", "any"], ["product_program", new Set(["product_management"])]]);
    expect(answersWire(answers)).toEqual([{ track: "management", roles: "any" }, { track: "product_program", roles: ["product_management"] }]);
    expect(sameAnswers(answersFrom(answersWire(answers)), answers)).toBe(true);
    expect(sameAnswers(answers, asAny(answers))).toBe(false);
    expect(sameAnswers(null, null)).toBe(true);
    expect(sameAnswers(answers, null)).toBe(false);
    const { tracks, roles } = projectAnswers(answers, FAMILIES);
    expect(tracks).toEqual(["management", "product_program"]);
    expect(roles).toEqual(FAMILIES); // "any" projects to every family
    expect(rowOn("any", ROLE_QUESTIONS.technical.rows[0])).toBe(false);
  });

  /* The funnel's invariants, exhaustively over a small joint: every state
     three answers can reach with nothing ticked or one row each. I1: adding
     an answer never lowers the count. I2: nothing ticked keeps every role, so
     the first tick never raises the count and the last untick never lowers
     it; between them a tick never lowers it and an untick never raises it.
     I3: a click never moves another answer's count. */
  it("adding never lowers, ticks and unticks move the count the way they say, and a click never moves another answer", () => {
    const index = buildScopeIndex({
      ready: true, companies: ["acme"], missing_companies: [], stale_companies: [], partial_companies: [], cities: [], scanned_places: {}, unplaced: 0,
      roles: ["engineering_management", "product_management", "technical_program_management", "software_engineering", "design_ux", "sales_business_development"],
      bands: ["senior"], tracks: ["management", "product_program", "technical"],
      location_sets: [["uk"]], domain_sets: [[]],
      cells: [
        [0, 0, 0, 0, 0, 4], [5, 0, 0, 0, 0, 7], [4, 0, 0, 0, 0, 2], // management: EM, sales managers, design managers
        [1, 0, 1, 0, 0, 5], [2, 0, 1, 0, 0, 3], // product: PM, TPM
        [3, 0, 2, 0, 0, 9], [4, 0, 2, 0, 0, 6], // technical: software, design
      ],
    });
    const base: ScopeAxesSelection = {
      roles: new Set(), bands: new Set(["senior"]), tracks: new Set(), locations: new Set(["uk"]), domains: new Set(),
    };
    const count = (answers: Map<string, AnswerRoles>, only?: string) => countUnderScope(index, {
      ...base, answers: only ? new Map([...answers].filter(([track]) => track === only)) : answers,
    });
    const TRACKS: TrackSlug[] = ["management", "product_program", "technical"];
    const states: Map<string, AnswerRoles>[] = [];
    const choices = (track: TrackSlug): (AnswerRoles | null)[] => [
      null, "any", ...ROLE_QUESTIONS[track].rows.map((row) => new Set(row.families) as AnswerRoles),
    ];
    for (const a of choices("management")) for (const b of choices("product_program")) for (const c of choices("technical")) {
      states.push(new Map([["management", a], ["product_program", b], ["technical", c]].filter(([, v]) => v !== null) as [string, AnswerRoles][]));
    }
    for (const state of states) {
      const total = count(state);
      for (const track of TRACKS) {
        const others = () => TRACKS.filter((other) => other !== track && state.has(other)).map((other) => count(state, other));
        const before = others();
        const moves: Map<string, AnswerRoles>[] = [];
        if (!state.has(track)) {
          const added = withAnswer(state, track, true);
          expect(count(added)).toBeGreaterThanOrEqual(total); // I1
          moves.push(added);
        } else {
          const roles = state.get(track)!;
          moves.push(withAnswer(state, track, false));
          for (const row of ROLE_QUESTIONS[track].rows) {
            const on = rowOn(roles, row);
            const next = withRow(state, track, row.key, !on);
            if (roles === "any") expect(count(next)).toBeLessThanOrEqual(total); // I2: the first tick narrows
            else if (next.get(track) === "any") expect(count(next)).toBeGreaterThanOrEqual(total); // I2: the last untick gives every role back
            else if (on) expect(count(next)).toBeLessThanOrEqual(total); // I2: untick never raises
            else expect(count(next)).toBeGreaterThanOrEqual(total); // I2: tick never lowers
            moves.push(next);
          }
        }
        for (const next of moves) {
          const after = TRACKS.filter((other) => other !== track && state.has(other)).map((other) => count(next, other));
          expect(after).toEqual(before); // I3: no other answer moves
        }
      }
    }
  });
});

const place = (
  slug: string, display: string, kind: ScopeLocation["kind"], parent: string | null,
): ScopeLocation => ({
  slug, display, kind, parent, count: 0, default_enabled: false, selected: false, uncovered_by: [], prominent: true, new: false,
});
const LOCATIONS: ScopeLocation[] = [
  place("silicon_valley", "Silicon Valley", "metro", "united_states"),
  place("new_york", "New York", "metro", "united_states"),
  place("united_states", "United States", "country", null),
  place("london", "London", "metro", "uk"),
  place("uk", "United Kingdom", "country", "europe"),
  place("germany", "Germany", "country", "europe"),
  place("france", "France", "country", "europe"),
  place("europe", "Europe", "region", null),
  place("singapore", "Singapore", "country", null),
];

describe("where: a base and a reach", () => {
  it("reads effective selections as bases and hides what an ancestor implies", () => {
    const bases = basesOf(LOCATIONS, new Set(["silicon_valley", "uk", "london"]));
    expect(bases.map((base) => base.display)).toEqual(["Silicon Valley", "United Kingdom"]);
  });

  it("offers a metro its own city and each ancestor, and never the whole world inside a row", () => {
    expect(reachesOf(LOCATIONS, "london").map((reach) => reach.label)).toEqual([
      "London only", "Anywhere in the UK", "Anywhere in Europe",
    ]);
    expect(reachesOf(LOCATIONS, "singapore").map((reach) => reach.label)).toEqual(["Anywhere in Singapore"]);
    // "Anywhere" in the UK row would read as a reach of the UK and swallow
    // the US base. The whole world is its own control.
    expect(anywhereSlugs(LOCATIONS)).toEqual(["united_states", "europe", "singapore"]);
  });

  it("names the base that already covers a searched place", () => {
    const selected = new Set(["uk", "silicon_valley"]);
    expect(coveredBy(LOCATIONS, selected, "london")?.slug).toBe("uk");
    expect(coveredBy(LOCATIONS, selected, "silicon_valley")?.slug).toBe("silicon_valley");
    expect(coveredBy(LOCATIONS, selected, "germany")).toBeNull();
    expect(coveredBy(LOCATIONS, selected, "united_states")).toBeNull();
  });

  it("widening a reach replaces the base with the wider place and drops what it now implies", () => {
    const selected = new Set(["london", "silicon_valley"]);
    const wider = new Set(withReach(LOCATIONS, selected, "london", "europe"));
    expect(wider).toEqual(new Set(["europe", "silicon_valley"]));
    const narrower = new Set(withReach(LOCATIONS, wider, "europe", "uk"));
    expect(narrower).toEqual(new Set(["uk", "silicon_valley"]));
  });

  it("anywhere is every top-level place, and reads back as one base", () => {
    const anywhere = new Set(withReach(LOCATIONS, new Set(["london"]), "london", ANYWHERE));
    expect(anywhere).toEqual(new Set(["united_states", "europe", "singapore"]));
    const bases = basesOf(LOCATIONS, anywhere);
    expect(bases).toEqual([{ slug: ANYWHERE, display: "Anywhere", kind: "anywhere" }]);
    expect(withoutBase(LOCATIONS, anywhere, ANYWHERE)).toEqual([]);
    expect(wherePhrase(LOCATIONS, anywhere)).toBe("anywhere");
  });

  it("adds a base unless an ancestor already implies it, and removes a base with everything beneath", () => {
    const selected = new Set(["uk"]);
    expect(new Set(withBase(LOCATIONS, selected, "london"))).toEqual(new Set(["uk"]));
    expect(new Set(withBase(LOCATIONS, selected, "silicon_valley"))).toEqual(new Set(["uk", "silicon_valley"]));
    expect(withoutBase(LOCATIONS, new Set(["europe", "silicon_valley", "uk"]), "europe")).toEqual(["silicon_valley"]);
  });

  it("says where in words: cities first, then every wide base under one 'anywhere'", () => {
    expect(wherePhrase(LOCATIONS, new Set(["london", "united_states"]))).toBe("in London or anywhere in the US");
    // The adverb once, never "anywhere in … or anywhere in …".
    expect(wherePhrase(LOCATIONS, new Set(["uk", "united_states"]))).toBe("anywhere in the US or the UK");
    expect(wherePhrase(LOCATIONS, new Set(["silicon_valley", "uk", "singapore"])))
      .toBe("in Silicon Valley or anywhere in the UK or Singapore");
    expect(wherePhrase(LOCATIONS, new Set())).toBeNull();
  });

  it("offers to choose inside a place only when it holds two or more places, and names them", () => {
    expect(canChoose(LOCATIONS, "europe")).toBe(true);
    expect(childNoun(LOCATIONS, "europe")).toBe("countries");
    expect(canChoose(LOCATIONS, "united_states")).toBe(true);
    expect(childNoun(LOCATIONS, "united_states")).toBe("cities");
    // The UK holds London alone: "Choose cities" with one city is not a choice.
    expect(canChoose(LOCATIONS, "uk")).toBe(false);
    expect(canChoose(LOCATIONS, "singapore")).toBe(false);
  });

  it("narrows a whole place to its members less the one unticked, and reads back as one row", () => {
    const whole = new Set(["europe", "silicon_valley"]);
    expect(childState(LOCATIONS, whole, "europe", "germany")).toBe("on");
    const narrowed = new Set(withChildToggled(LOCATIONS, whole, "europe", "germany"));
    // Nothing else is lost: the other two countries and the other base stay.
    expect(narrowed).toEqual(new Set(["uk", "france", "silicon_valley"]));
    const bases = basesOf(LOCATIONS, narrowed);
    expect(bases.map((base) => [base.display, base.kind])).toEqual([["Silicon Valley", "metro"], ["Europe", "group"]]);
    const europe = bases.find((base) => base.slug === "europe")!;
    expect(europe.members?.map((member) => member.slug)).toEqual(["uk", "france"]);
    expect(membersPhrase(LOCATIONS, europe)).toBe("Every country except Germany");
    // Cities inside a country are never "every city except": roles filed at
    // the country itself (remote, towns outside the metros) leave too, so the
    // phrase names what stays.
    const us = [
      ...LOCATIONS,
      place("austin", "Austin", "metro", "united_states"),
      place("dc_metro", "Washington, DC", "metro", "united_states"),
    ];
    const cities = basesOf(us, new Set(withChildToggled(us, new Set(["united_states"]), "united_states", "new_york")), "united_states")
      .find((base) => base.slug === "united_states")!;
    expect(membersPhrase(us, cities)).toBe("Only Silicon Valley, Austin and Washington, DC");
    // The sentence says the places kept, never the region they were chosen in.
    expect(wherePhrase(LOCATIONS, narrowed)).toBe("in Silicon Valley or anywhere in the UK or France");
  });

  it("ticking the last place back is the whole place again, not its members spelled out", () => {
    const narrowed = new Set(["uk", "france"]);
    const whole = new Set(withChildToggled(LOCATIONS, narrowed, "europe", "germany"));
    expect(whole).toEqual(new Set(["europe"]));
    expect(basesOf(LOCATIONS, whole)).toEqual([{ slug: "europe", display: "Europe", kind: "region" }]);
  });

  it("one place left is its own base, except while its parent's chooser is open", () => {
    const one = new Set(["france"]);
    expect(basesOf(LOCATIONS, one).map((base) => [base.display, base.kind])).toEqual([["France", "country"]]);
    const editing = basesOf(LOCATIONS, one, "europe");
    expect(editing.map((base) => [base.display, base.kind])).toEqual([["Europe", "group"]]);
    expect(membersPhrase(LOCATIONS, editing[0])).toBe("France");
    // Emptied while open: the row stays, and says so, instead of vanishing.
    const empty = basesOf(LOCATIONS, new Set(), "europe");
    expect(membersPhrase(LOCATIONS, empty[0])).toBe("No countries chosen yet");
    expect(basesOf(LOCATIONS, new Set())).toEqual([]);
  });

  it("a place with something chosen inside it is mixed, and ticking it takes the whole of it", () => {
    const selected = new Set(["london"]);
    expect(childState(LOCATIONS, selected, "europe", "uk")).toBe("mixed");
    expect(childState(LOCATIONS, selected, "europe", "germany")).toBe("off");
    expect(new Set(withChildToggled(LOCATIONS, selected, "europe", "uk"))).toEqual(new Set(["uk"]));
  });

  it("lists up to three kept places, then counts the rest in words", () => {
    const many: ScopeLocation[] = [
      place("latam", "Latin America", "region", null),
      ...["Argentina", "Brazil", "Chile", "Colombia", "Mexico", "Peru", "Uruguay", "Cuba", "Haiti"].map((name) =>
        place(name.toLowerCase(), name, "country", "latam")),
    ];
    const four = basesOf(many, new Set(["argentina", "brazil", "chile", "colombia"]))[0];
    // Four are said in full: "and 1 more" says less than the name.
    expect(membersPhrase(many, four)).toBe("Argentina, Brazil, Chile and Colombia");
    const five = basesOf(many, new Set(["argentina", "brazil", "chile", "colombia", "mexico"]))[0];
    expect(membersPhrase(many, five)).toBe("Argentina, Brazil, Chile and 2 more");
    const two = basesOf(many, new Set(["brazil", "mexico"]))[0];
    expect(membersPhrase(many, two)).toBe("Brazil and Mexico");
    const most = basesOf(many, new Set(["argentina", "brazil", "chile", "colombia", "mexico", "peru", "uruguay"]))[0];
    expect(membersPhrase(many, most)).toBe("Every country except Cuba and Haiti");
  });

  it("reads a GeoNames city like a metro: its own reach first, then 'in' it", () => {
    const withCity = [...LOCATIONS, place("city_2673730", "Stockholm", "city", "sweden"), place("sweden", "Sweden", "country", "europe")];
    expect(reachesOf(withCity, "city_2673730").map((reach) => reach.label)).toEqual([
      "Stockholm only", "Anywhere in Sweden", "Anywhere in Europe",
    ]);
    expect(wherePhrase(withCity, new Set(["city_2673730", "uk"]))).toBe("in Stockholm or anywhere in the UK");
  });

  it("reads a set of countries that is exactly a union as that union, and one short as the countries", () => {
    const eu = UNIONS.european_union.members;
    const europe: ScopeLocation[] = [
      place("europe", "Europe", "region", null),
      ...[...eu, "uk", "norway"].map((slug) => place(slug, slug, "country", "europe")),
    ];
    const bases = basesOf(europe, new Set(eu));
    expect(bases.map((base) => [base.display, base.kind])).toEqual([["Europe", "group"]]);
    expect(membersPhrase(europe, bases[0])).toBe("European Union");
    expect(wherePhrase(europe, new Set(eu))).toBe("anywhere in the European Union");
    expect(unionOf(eu.slice(1).map((slug) => ({ slug })))).toBeNull();
    expect(unionOf([...eu, "uk"].map((slug) => ({ slug })))).toBeNull();
  });

  it("says a country the way people say it, and leaves a formal name that has no short form", () => {
    expect(placeProse("United Kingdom")).toBe("the UK");
    expect(placeProse("United States")).toBe("the US");
    expect(placeProse("Netherlands")).toBe("the Netherlands");
    expect(placeProse("Singapore")).toBe("Singapore");
    expect(placeProse("Europe")).toBe("Europe");
  });

  /* The Summary's rows: no row may grow past two lines, whoever's answers
     they are. */
  it("names two and counts the rest, and says three or fewer in full", () => {
    expect(namedThenCounted(["A", "B", "C"])).toBe("A, B and C");
    expect(namedThenCounted(["A", "B", "C", "D", "E", "F", "G", "H", "I"])).toBe("A, B and 7 more");
    // "or" keeps joinOr's comma, so one row never mixes two styles.
    expect(namedThenCounted(["A", "B", "C"], "or")).toBe("A, B, or C");
    expect(namedThenCounted(["A", "B", "C", "D"], "or")).toBe("A, B, or 2 more");
    expect(namedThenCounted(["A", "B", "C"], "or", 1)).toBe("A or 2 more");
    expect(namedThenCounted([])).toBe("");
    expect(namedThenCounted(["A"])).toBe("A");
  });

  it("reads the interests back as at most two lines, however many there are", () => {
    const display = (slug: string) => slug.toUpperCase();
    const lines = (verb: "interested" | "avoid", subjects: string[]) => subjects.map((subject) => ({ verb, subject }));
    expect(interestsRows([], display)).toEqual([]);
    // Nine on, nine off.
    const nine = ["a", "b", "c", "d", "e", "f", "g", "h", "i"];
    expect(interestsRows([...lines("interested", nine), ...lines("avoid", nine.map((x) => `${x}x`))], display))
      .toEqual(["A and 8 more", "Not: AX and 8 more"]);
    // Two are still said in full: "and 1 more" says less than the name.
    expect(interestsRows(lines("interested", ["a", "b"]), display)).toEqual(["A and B"]);
    expect(interestsRows(lines("avoid", ["ads"]), display)).toEqual(["Not: ADS"]);
  });
});

describe("modifiers", () => {
  const ALL = ["ai_ml", "cloud", "logistics", "ads", "health"];

  it("writes the set the lines mean, and reads it back as the same lines", () => {
    const lines = withLine(withLine([], { verb: "interested", subject: "ai_ml" }), { verb: "interested", subject: "health" });
    const set = domainsOf(ALL, lines);
    expect(new Set(set)).toEqual(new Set(["ai_ml", "health"]));
    expect(linesFrom(ALL, new Set(set), new Set(excludedOf(ALL, lines)))).toEqual(lines);

    const avoided = withLine([], { verb: "avoid", subject: "logistics" });
    expect(new Set(domainsOf(ALL, avoided))).toEqual(new Set(["ai_ml", "cloud", "ads", "health"]));
    expect(linesFrom(ALL, new Set(domainsOf(ALL, avoided)), new Set(excludedOf(ALL, avoided)))).toEqual(avoided);
  });

  it("one subject holds one line; removing it frees the subject", () => {
    const flipped = withLine([{ verb: "interested", subject: "ai_ml" }], { verb: "avoid", subject: "ai_ml" });
    expect(flipped).toEqual([{ verb: "avoid", subject: "ai_ml" }]);
    expect(withoutLine(flipped, "ai_ml")).toEqual([]);
    // No interests left means everything minus what is avoided, never nothing.
    expect(domainsOf(ALL, withoutLine(flipped, "ai_ml"))).toEqual(ALL);
  });

  it("\"not interested in\" lines write the veto list, and a mix reads back exactly as written", () => {
    // The worlds set alone holds only the interest: the avoid line survives a
    // reload through the veto list.
    const mixed = withLine([{ verb: "interested", subject: "ai_ml" }], { verb: "avoid", subject: "ads" });
    expect(excludedOf(ALL, mixed)).toEqual(["ads"]);
    expect(linesFrom(ALL, new Set(domainsOf(ALL, mixed)), new Set(excludedOf(ALL, mixed)))).toEqual(mixed);

    // Avoids alone: the veto list is the lines, and no interest is invented.
    const avoided = [{ verb: "avoid" as const, subject: "logistics" }, { verb: "avoid" as const, subject: "ads" }];
    expect(linesFrom(ALL, new Set(domainsOf(ALL, avoided)), new Set(excludedOf(ALL, avoided))))
      .toEqual([{ verb: "avoid", subject: "logistics" }, { verb: "avoid", subject: "ads" }]);

    // Avoiding everything is a veto on everything, not "no filter".
    const everything = ALL.map((subject) => ({ verb: "avoid" as const, subject }));
    expect(excludedOf(ALL, everything)).toEqual(ALL);

    // No excluded list: nothing was avoided, so the worlds set is its interests.
    expect(linesFrom(ALL, new Set(["ai_ml", "cloud", "ads", "health"]), new Set())).toEqual(
      ["ai_ml", "cloud", "ads", "health"].map((subject) => ({ verb: "interested", subject })),
    );
    expect(linesFrom(ALL, new Set(ALL), new Set())).toEqual([]);
  });

  it("interests on more than half the subjects come back as interests, and one more tick adds one", () => {
    const SUBJECTS = Array.from({ length: 19 }, (_, i) => `subject_${i}`);
    const picked = SUBJECTS.slice(0, 10).map((subject) => ({ verb: "interested" as const, subject }));
    const saved = { domains: domainsOf(SUBJECTS, picked), excluded: excludedOf(SUBJECTS, picked) };
    expect(saved.excluded).toEqual([]);

    const reloaded = linesFrom(SUBJECTS, new Set(saved.domains), new Set(saved.excluded));
    expect(reloaded).toEqual(picked);

    const ticked = withLine(reloaded, { verb: "interested", subject: "subject_12" });
    expect(new Set(domainsOf(SUBJECTS, ticked))).toEqual(new Set([...saved.domains, "subject_12"]));
    expect(excludedOf(SUBJECTS, ticked)).toEqual([]);
  });
});

describe("the sentence", () => {
  const LEVELS = [
    { slug: "entry", display: "Entry / Junior", order: 0 },
    { slug: "staff", display: "Staff", order: 2 },
    { slug: "director_plus", display: "Director+", order: 6 },
  ];

  it("joins with or, in English", () => {
    expect(joinOr(["a"])).toBe("a");
    expect(joinOr(["a", "b"])).toBe("a or b");
    expect(joinOr(["a", "b", "c"])).toBe("a, b, or c");
  });

  it("reads the kinds of role back, and leaves the narrowing to its own row", () => {
    expect(accountablePhrase(new Map())).toBeNull();
    expect(accountablePhrase(new Map([["management", "any"]]))).toBe("leading a team");
    expect(accountablePhrase(new Map([["management", new Set(ROLE_QUESTIONS.management.rows[0].families)]])))
      .toBe("leading a team");
    expect(accountablePhrase(new Map<string, AnswerRoles>([["management", "any"], ["technical", new Set(["software_engineering"])]])))
      .toBe("leading a team or hands-on");
    const all = new Map<string, AnswerRoles>(ACCOUNTABLE.map((answer) => [answer.slug, "any"]));
    expect(accountablePhrase(all)).toBe("leading a team, owning a product, or 2 more");
  });

  it("reads which roles as the roles picked, named then counted, however many answers narrow", () => {
    const families = (track: TrackSlug, count: number) =>
      new Set(ROLE_QUESTIONS[track].rows.slice(0, count).flatMap((row) => [...row.families]));
    expect(whichRolesPhrase(new Map())).toBeNull();
    // An answer left at any role is the Role row's to say, not this one's.
    expect(whichRolesPhrase(new Map([["management", "any"]]))).toBeNull();
    expect(whichRolesPhrase(new Map<string, AnswerRoles>([["management", "any"], ["technical", families("technical", 1)]])))
      .toBe("software");
    expect(whichRolesPhrase(new Map([["management", families("management", 3)]])))
      .toBe("engineers, designers, or data science & AI");
    // Every answer narrowed: two named, the rest counted.
    const every = new Map<string, AnswerRoles>(TRACK_SLUGS.map((track) => [track, families(track, 2)]));
    expect(whichRolesPhrase(every)).toMatch(/^engineers, designers, or \d+ more$/);
  });

  it("keeps an acronym's capitals when a role is said mid-sentence", () => {
    // One answer narrowed to exactly the row with this label.
    const pick = (label: string) => {
      for (const track of TRACK_SLUGS) {
        const row = ROLE_QUESTIONS[track].rows.find((r) => r.label === label);
        if (row) return new Map<string, AnswerRoles>([[track, new Set(row.families)]]);
      }
      throw new Error(`no role row labelled ${label}`);
    };
    // Lower-casing the whole label would print "infrastructure / sre" and "ml & ai research".
    expect(whichRolesPhrase(pick("Infrastructure / SRE"))).toBe("infrastructure / SRE");
    expect(whichRolesPhrase(pick("ML & AI research"))).toBe("ML & AI research");
    expect(whichRolesPhrase(pick("IT support"))).toBe("IT support");
    expect(whichRolesPhrase(pick("Product / UX design"))).toBe("product / UX design");
  });

  it("reads the level from the two markers, or from the span when no marker is placed", () => {
    expect(levelPhrase(LEVELS, "staff", "director_plus", new Set())).toBe("from Staff to Director+");
    expect(levelPhrase(LEVELS, "director_plus", "staff", new Set())).toBe("from Staff to Director+");
    expect(levelPhrase(LEVELS, "staff", "staff", new Set())).toBe("at Staff");
    expect(levelPhrase(LEVELS, null, null, new Set(["entry", "staff"]))).toBe("from Entry / Junior to Staff");
    expect(levelPhrase(LEVELS, null, null, new Set())).toBeNull();
  });
});


describe("where: a place excepted inside a whole base", () => {
  const us = [
    ...LOCATIONS,
    place("austin", "Austin", "metro", "united_states"),
    place("dc_metro", "Washington, DC", "metro", "united_states"),
  ];
  const whole = new Set(["united_states"]);

  it("unticking a city inside the whole US excepts it and keeps the US", () => {
    const next = withChildPlaces(us, whole, new Set(), "united_states", "new_york");
    // The base stays, so the roles filed at the US itself stay too; spelling
    // the US out as its other metros would drop them.
    expect(next).toEqual({ locations: ["united_states"], excepted: ["new_york"] });
    const excepted = new Set(next.excepted);
    expect(childState(us, whole, "united_states", "new_york", excepted)).toBe("off");
    expect(childState(us, whole, "united_states", "austin", excepted)).toBe("on");
    expect(basesOf(us, new Set(next.locations))).toEqual([{ slug: "united_states", display: "United States", kind: "country" }]);
    expect(exceptPhrase(exceptedIn(us, excepted, "united_states"))).toBe(" except New York");
    expect(wherePhrase(us, whole, excepted)).toBe("anywhere in the US, except New York");
    // The Summary's short form counts places, and still says what is left out.
    const four = new Set(["united_states", "uk", "france", "germany"]);
    expect(wherePhrase(us, four, excepted, true)).toBe("the US, the UK, or 2 more, except New York");
    expect(wherePhrase(us, four, new Set(), true)).toBe("the US, the UK, or 2 more");
    // Three are still a sentence, the short form or not.
    expect(wherePhrase(us, new Set(["united_states", "uk", "france"]), excepted, true))
      .toBe("anywhere in the US, the UK, or France, except New York");
  });

  it("ticking it back removes the exception, and nothing else moves", () => {
    const back = withChildPlaces(us, whole, new Set(["new_york", "austin"]), "united_states", "new_york");
    expect(back).toEqual({ locations: ["united_states"], excepted: ["austin"] });
  });

  it("a place made of chosen members still narrows by members", () => {
    const members = new Set(["silicon_valley", "new_york"]);
    const next = withChildPlaces(us, members, new Set(), "united_states", "new_york");
    expect(next).toEqual({ locations: ["silicon_valley"], excepted: [] });
  });

  it("an exception lives only strictly inside an included place", () => {
    // Removing the US, or narrowing it to New York itself, leaves nothing to except.
    expect(exceptionsUnder(us, new Set(["uk"]), ["new_york"])).toEqual([]);
    expect(exceptionsUnder(us, new Set(["new_york"]), ["new_york"])).toEqual([]);
    // Widening keeps it: North America except New York is still an answer.
    expect(exceptionsUnder(us, new Set(["united_states", "uk"]), ["new_york", "london"])).toEqual(["new_york", "london"]);
  });
});
