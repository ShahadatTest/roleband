import roleQuestions from "./roleQuestions.gen.json";
import type { ScopeLocation } from "../../../api";
import { UNIONS } from "../../../unions.gen";
import {
  profileWalkModelAnd,
  profileWalkModelAnywhere,
  profileWalkModelAnywhereIn,
  profileWalkModelAnywhereIn2,
  profileWalkModelEngineerScientistDesignerAnalyst,
  profileWalkModelEverywhere,
  profileWalkModelExcept,
  profileWalkModelExcept2,
  profileWalkModelFromTo,
  profileWalkModelFromTo2,
  profileWalkModelHandsOnAsTheExpert,
  profileWalkModelIn,
  profileWalkModelInterestedIn,
  profileWalkModelLeadingATeam,
  profileWalkModelLeadingATeam2,
  profileWalkModelMore,
  profileWalkModelNoChosenYet,
  profileWalkModelNot,
  profileWalkModelNotInterestedIn,
  profileWalkModelOnly,
  profileWalkModelOnly2,
  profileWalkModelOr,
  profileWalkModelOr3,
  profileWalkModelOwningAProductOrProgram,
  profileWalkModelOwningAProductOrProgram2,
  profileWalkModelPeopleManagersAndDirectorsAny,
  profileWalkModelProductProgramOrProjectManagement,
  profileWalkModelSalesPartnershipsCustomerSuccess,
  profileWalkModelThePlace,
  profileWalkModelWorkingWithCustomers,
  profileWalkModelWorkingWithCustomers2,
  profileSummaryStepAnyRoleThatFits,
  profileSummaryStepNoneYet,
  profileSummaryStepNotSet,
  profileSummaryStepNothingPickedYet,
} from "../../../copy/gen/profile";
import { levelName, placeName } from "../../../copy/vocab";

/* The Walk's vocabulary and arithmetic, with no React in it.
 *
 * Profile › Looking for is a path of five screens over the same five-axis
 * draft the wizard and the board read.
 * Everything the screens need to DECIDE lives here so it can be read and
 * tested without a provider: which answer maps to which track, which role
 * families an answer's rows enable, how a base and a reach become location
 * slugs, how the worlds set reads as a list of modifier lines, and how the
 * draft reads back on the Summary.
 *
 * The four answers to "what do you want to be accountable for" are the four
 * career tracks with the field split removed. The slugs are the catalog's;
 * the words are forward-facing on purpose: a person starting fresh in a new
 * field must be able to answer. */

export type TrackSlug = "management" | "product_program" | "technical" | "business_customer";

export interface AccountableAnswer {
  slug: TrackSlug;
  label: string;
  examples: string;
  /** Lower-case, for the sheet's sentence. */
  phrase: string;
}

export const ACCOUNTABLE: readonly AccountableAnswer[] = [
  {
    slug: "management",
    get label() { return profileWalkModelLeadingATeam(); },
    get examples() { return profileWalkModelPeopleManagersAndDirectorsAny(); },
    get phrase() { return profileWalkModelLeadingATeam2(); },
  },
  {
    slug: "product_program",
    get label() { return profileWalkModelOwningAProductOrProgram(); },
    get examples() { return profileWalkModelProductProgramOrProjectManagement(); },
    get phrase() { return profileWalkModelOwningAProductOrProgram2(); },
  },
  {
    slug: "technical",
    get label() { return profileWalkModelHandsOnAsTheExpert(); },
    get examples() { return profileWalkModelEngineerScientistDesignerAnalyst(); },
    phrase: "hands-on",
  },
  {
    slug: "business_customer",
    get label() { return profileWalkModelWorkingWithCustomers(); },
    get examples() { return profileWalkModelSalesPartnershipsCustomerSuccess(); },
    get phrase() { return profileWalkModelWorkingWithCustomers2(); },
  },
];

export const TRACK_SLUGS = ACCOUNTABLE.map((answer) => answer.slug);

export function accountableFor(slug: string): AccountableAnswer | undefined {
  return ACCOUNTABLE.find((answer) => answer.slug === slug);
}

/** One row of the "which roles" step: a noun the person reads and the role
    families it stands for. A family appears in at most one row per answer. */
export interface RoleRow {
  key: string;
  label: string;
  families: readonly string[];
  examples?: string;
  /** Specialists pick a craft first; the rows of one craft share it. */
  craft?: string;
}

export interface RoleQuestion {
  /** How the sentence continues: "Lead a team" + " of " + rows. */
  joiner: string;
  /** The "any" choice, worded for this answer. */
  any: string;
  crafts?: readonly string[];
  rows: readonly RoleRow[];
}

/* The rows are the backend's (`tracker/taxonomy/role_rows.py`),
   exported as `roleQuestions.gen.json` by `python -m scripts.export_role_questions`.
   The backend holds them against the track classifier: every row can match,
   and every (kind, family) the classifier files is named by a row of that
   kind. "Any" is every role of the kind, named by a row or not. */
export const ROLE_QUESTIONS: Record<TrackSlug, RoleQuestion> = roleQuestions as Record<TrackSlug, RoleQuestion>;

export function isTrackSlug(slug: string): slug is TrackSlug {
  return slug in ROLE_QUESTIONS;
}

/* ---- Answers: which roles of each kind.
 *
 * One answer per kind of role the person picked on step 1: "any" (every role
 * of that kind, including families added later; step 4 shows it with nothing
 * ticked) or the families ticked on step 4. Nothing ticked keeps every role,
 * as an empty World keeps every world: the first tick narrows to that card,
 * each further tick adds one, and unticking the last gives every role back.
 * A posting has exactly one kind, so answers never overlap: a click on one
 * answer cannot change another. Two flat lists shared by every answer would
 * let the gate admit their cross product. */

export type AnswerRoles = "any" | ReadonlySet<string>;
export type Answers = ReadonlyMap<string, AnswerRoles>;

export function withAnswer(answers: Answers, track: string, on: boolean): Map<string, AnswerRoles> {
  const next = new Map(answers);
  if (on) { if (!next.has(track)) next.set(track, "any"); } else next.delete(track);
  return next;
}

/** A row is on when it was ticked: every family it names is picked. Under
    "any" nothing is ticked. */
export function rowOn(roles: AnswerRoles, row: RoleRow): boolean {
  return roles !== "any" && row.families.every((family) => roles.has(family));
}

/** Tick or untick one row of an answer. The first tick narrows "any" to that
    row; unticking the last row gives every role of the kind back. */
export function withRow(answers: Answers, track: TrackSlug, key: string, on: boolean): Map<string, AnswerRoles> {
  const current = answers.get(track);
  const row = ROLE_QUESTIONS[track].rows.find((candidate) => candidate.key === key);
  if (!row || current === undefined) return new Map(answers);
  const families = new Set(current === "any" ? [] : current);
  for (const family of row.families) {
    if (on) families.add(family);
    else families.delete(family);
  }
  const next = new Map(answers);
  next.set(track, families.size === 0 ? "any" : families);
  return next;
}

/** The rows ticked under an answer, in table order. */
export function rowsPicked(track: TrackSlug, roles: AnswerRoles): RoleRow[] {
  if (roles === "any") return [];
  return ROLE_QUESTIONS[track].rows.filter((row) => rowOn(roles, row));
}

/** Answers from their wire form, and back. */
export function answersFrom(wire: readonly { track: string; roles: "any" | string[] }[]): Map<string, AnswerRoles> {
  return new Map(wire.map((answer) => [answer.track, answer.roles === "any" ? "any" : new Set(answer.roles)]));
}

export function answersWire(answers: Answers): { track: string; roles: "any" | string[] }[] {
  return TRACK_SLUGS.filter((track) => answers.has(track)).map((track) => {
    const roles = answers.get(track)!;
    return { track, roles: roles === "any" ? "any" : [...roles].sort() };
  });
}

export function sameAnswers(left: Answers | null, right: Answers | null): boolean {
  if (left === null || right === null) return left === right;
  if (left.size !== right.size) return false;
  for (const [track, roles] of left) {
    const other = right.get(track);
    if (other === undefined) return false;
    if (roles === "any" || other === "any") { if (roles !== other) return false; continue; }
    if (roles.size !== other.size || [...roles].some((family) => !other.has(family))) return false;
  }
  return true;
}

/** Every answer as "any": the Role layer of the funnel, before step 4. */
export function asAny(answers: Answers): Map<string, AnswerRoles> {
  return new Map([...answers.keys()].map((track) => [track, "any"]));
}

/** The two flat lists the answers project to, for readers that still read
    them (the level picker's gates, Welcome). "Any" projects to `allFamilies`. */
export function projectAnswers(answers: Answers, allFamilies: readonly string[]): { tracks: string[]; roles: string[] } {
  const roles = new Set<string>();
  for (const value of answers.values()) for (const family of value === "any" ? allFamilies : value) roles.add(family);
  return { tracks: TRACK_SLUGS.filter((track) => answers.has(track)), roles: allFamilies.filter((family) => roles.has(family)) };
}

/* ---- Where: a base and a reach.
 *
 * The user names a place and says how far they would go. The answer is stored
 * as the catalog's location slugs, one per base: the metro for "just here",
 * the country or the region for "anywhere in", every top-level place for
 * "anywhere". Reading it back, each effective slug (one no selected ancestor
 * implies) is a base row; the base of a country-wide reach reads as the
 * country, because the slug is the truth and the city is not stored. */

export const ANYWHERE = "*";

/** A place a person names as a point: a metro, or a city from the place search.
    Read as "London only" and "in London", never "anywhere in". */
function isTown(kind: string): boolean {
  return kind === "metro" || kind === "city";
}

/** The union (CLDR's grouping, `UNIONS`) whose members are exactly these
    places, if any: Europe narrowed to the 27 reads as "European Union". */
export function unionOf(members: readonly { slug: string }[]): string | null {
  const chosen = new Set(members.map((member) => member.slug));
  for (const union of Object.values(UNIONS)) {
    if (union.members.length === chosen.size && union.members.every((slug) => chosen.has(slug))) {
      return union.display;
    }
  }
  return null;
}

export interface Base {
  slug: string;
  display: string;
  /** "group": a place narrowed to some of the places inside it (Latin
      America, only Brazil and Mexico). `slug` is the place; `members` the
      chosen places inside, in catalog order. */
  kind: ScopeLocation["kind"] | "anywhere" | "group";
  members?: ScopeLocation[];
}

export interface Reach {
  slug: string;
  label: string;
}

type Tree = {
  bySlug: Map<string, ScopeLocation>;
  children: Map<string, ScopeLocation[]>;
  topLevel: ScopeLocation[];
};

export function locationTree(locations: readonly ScopeLocation[]): Tree {
  const bySlug = new Map(locations.map((location) => [location.slug, location]));
  const children = new Map<string, ScopeLocation[]>();
  const topLevel: ScopeLocation[] = [];
  for (const location of locations) {
    if (location.parent && bySlug.has(location.parent)) {
      const bucket = children.get(location.parent);
      if (bucket) bucket.push(location);
      else children.set(location.parent, [location]);
    } else {
      topLevel.push(location);
    }
  }
  return { bySlug, children, topLevel };
}

function ancestors(tree: Tree, slug: string): ScopeLocation[] {
  const chain: ScopeLocation[] = [];
  let current = tree.bySlug.get(slug);
  while (current?.parent && tree.bySlug.has(current.parent)) {
    current = tree.bySlug.get(current.parent)!;
    chain.push(current);
  }
  return chain;
}

function descendants(tree: Tree, slug: string): ScopeLocation[] {
  const kids = tree.children.get(slug) ?? [];
  return kids.flatMap((child) => [child, ...descendants(tree, child.slug)]);
}

function isAnywhere(tree: Tree, selected: Set<string>): boolean {
  return tree.topLevel.length > 0 && tree.topLevel.every((location) => selected.has(location.slug));
}

/** The base rows to show: effective selections only, or one "anywhere".

    Places chosen inside one unselected parent read as ONE row under that
    parent ("Latin America: Brazil and Mexico") when there are two or more of
    them, or while that parent's chooser is `open` (so the row a person is
    editing never turns into another shape under their hands). One chosen
    place alone is its own base, with its reach: Brazil widening to Latin
    America is the same answer as Latin America narrowed to Brazil. */
export function basesOf(
  locations: readonly ScopeLocation[],
  selected: Set<string>,
  open: string | null = null,
): Base[] {
  const tree = locationTree(locations);
  if (isAnywhere(tree, selected)) return [{ slug: ANYWHERE, display: profileWalkModelAnywhere(), kind: "anywhere" }];
  const effective = locations
    .filter((location) => selected.has(location.slug))
    .filter((location) => !ancestors(tree, location.slug).some((ancestor) => selected.has(ancestor.slug)));
  const byParent = new Map<string, ScopeLocation[]>();
  for (const location of effective) {
    if (!location.parent || !tree.bySlug.has(location.parent)) continue;
    const bucket = byParent.get(location.parent);
    if (bucket) bucket.push(location);
    else byParent.set(location.parent, [location]);
  }
  const grouped = new Set(
    [...byParent].filter(([parent, members]) => members.length >= 2 || parent === open).map(([parent]) => parent),
  );
  if (open && !selected.has(open) && tree.bySlug.has(open) && !coveredBy(locations, selected, open)) grouped.add(open);
  const order = new Map(locations.map((location, index) => [location.slug, index]));
  const rows: Array<Base & { at: number }> = [];
  for (const parent of grouped) {
    const place = tree.bySlug.get(parent)!;
    rows.push({
      slug: parent, display: placeName(place), kind: "group",
      members: byParent.get(parent) ?? [], at: order.get(parent) ?? 0,
    });
  }
  for (const location of effective) {
    if (location.parent && grouped.has(location.parent)) continue;
    rows.push({ slug: location.slug, display: placeName(location), kind: location.kind, at: order.get(location.slug) ?? 0 });
  }
  return rows.sort((a, b) => a.at - b.at).map(({ at: _at, ...base }) => base);
}

/* ---- Choosing inside a place ("Choose countries in …").
 *
 * A place with two or more places inside it can be narrowed: the chooser
 * lists them, all ticked while the whole place is on. Unticking one turns
 * the place into its members less that one; ticking the last one back turns
 * it into the whole place again, which also keeps the roles filed under the
 * place itself ("Remote, LATAM"), so "every country" and "the region" never
 * read as two different answers. */

/** The places inside `slug`, in catalog order. */
export function childrenOf(locations: readonly ScopeLocation[], slug: string): ScopeLocation[] {
  return locationTree(locations).children.get(slug) ?? [];
}

/** Whether a base offers "Choose …": it has two or more places inside. */
export function canChoose(locations: readonly ScopeLocation[], slug: string): boolean {
  return childrenOf(locations, slug).length >= 2;
}

/** What the places inside are called: "countries", "cities", else "places". */
export function childNoun(locations: readonly ScopeLocation[], slug: string): string {
  const kids = childrenOf(locations, slug);
  if (kids.length > 0 && kids.every((kid) => kid.kind === "country")) return "countries";
  if (kids.length > 0 && kids.every((kid) => isTown(kid.kind))) return "cities";
  return "places";
}

export type ChildState = "on" | "off" | "mixed";

/** A place inside `parent` as its checkbox shows it. "mixed": the place is
    off but something inside it is on (the Gulf, only the UAE), or on with
    something inside it excepted. An excepted place is off. */
export function childState(
  locations: readonly ScopeLocation[],
  selected: Set<string>,
  parent: string,
  child: string,
  excepted: ReadonlySet<string> = new Set(),
): ChildState {
  const tree = locationTree(locations);
  if (excepted.has(child)) return "off";
  if (selected.has(child) || coveredBy(locations, selected, parent)) {
    return descendants(tree, child).some((below) => excepted.has(below.slug)) ? "mixed" : "on";
  }
  return descendants(tree, child).some((below) => selected.has(below.slug)) ? "mixed" : "off";
}

/** Tick or untick one place inside `parent`. A mixed place ticks to whole. */
export function withChildToggled(
  locations: readonly ScopeLocation[],
  selected: Set<string>,
  parent: string,
  child: string,
): string[] {
  const tree = locationTree(locations);
  const kids = tree.children.get(parent) ?? [];
  const next = new Set(selected);
  const drop = (slug: string) => {
    next.delete(slug);
    for (const below of descendants(tree, slug)) next.delete(below.slug);
  };
  if (childState(locations, selected, parent, child) === "on") {
    const whole = coveredBy(locations, selected, parent);
    if (whole) {
      // The place (or a wider one) was on as a whole: spell it out as its
      // members first, so unticking one drops exactly that one.
      drop(whole.slug);
      let current = tree.bySlug.get(parent);
      const chain: ScopeLocation[] = [];
      while (current && current.slug !== whole.slug) {
        chain.push(current);
        current = current.parent ? tree.bySlug.get(current.parent) : undefined;
      }
      // Every sibling along the way back up stays on.
      for (const level of chain) {
        const up = level.parent ? tree.children.get(level.parent) ?? [] : [];
        for (const sibling of up) if (!chain.includes(sibling)) next.add(sibling.slug);
      }
      for (const kid of kids) next.add(kid.slug);
    }
    drop(child);
  } else {
    drop(child);
    next.add(child);
    if (kids.every((kid) => next.has(kid.slug))) {
      drop(parent);
      next.add(parent);
    }
  }
  return [...next];
}

/* ---- Exceptions inside a whole place.
 *
 * Unticking a place inside a base that is on as a whole ("Anywhere in the
 * US", untick New York) excepts it: the base stays, and so do the roles filed
 * at the base itself (remote, towns outside the metros), which spelling the
 * base out as its other members would drop. Ticking it back removes the
 * exception.
 * An exception lives only strictly inside an included place: removing,
 * narrowing or replacing the base takes its exceptions with it. */

export interface Places {
  locations: string[];
  excepted: string[];
}

/** The exceptions that still mean something: each strictly inside an
    included place, and not itself included. */
export function exceptionsUnder(
  locations: readonly ScopeLocation[],
  selected: ReadonlySet<string>,
  excepted: Iterable<string>,
): string[] {
  const tree = locationTree(locations);
  return [...excepted].filter((slug) =>
    !selected.has(slug) && ancestors(tree, slug).some((ancestor) => selected.has(ancestor.slug)));
}

/** A location edit, with the exceptions it leaves meaningful. */
function withPlaces(locations: readonly ScopeLocation[], next: string[], excepted: Iterable<string>): Places {
  return { locations: next, excepted: exceptionsUnder(locations, new Set(next), excepted) };
}

/** Tick or untick one place inside `parent`, with exceptions: inside a whole
    place an untick excepts, a tick removes the exception (and any inside the
    place). Inside a group of chosen members, the members rule. */
export function withChildPlaces(
  locations: readonly ScopeLocation[],
  selected: Set<string>,
  excepted: ReadonlySet<string>,
  parent: string,
  child: string,
): Places {
  const tree = locationTree(locations);
  const inside = new Set([child, ...descendants(tree, child).map((below) => below.slug)]);
  const rest = [...excepted].filter((slug) => !inside.has(slug));
  if (!coveredBy(locations, selected, parent)) {
    return withPlaces(locations, withChildToggled(locations, selected, parent, child), rest);
  }
  const state = childState(locations, selected, parent, child, excepted);
  const kept = [...selected].filter((slug) => !inside.has(slug));
  if (state === "on") return { locations: kept, excepted: [...rest, child] };
  return { locations: kept, excepted: rest };
}

/** The places excepted inside one base, in catalog order. */
export function exceptedIn(
  locations: readonly ScopeLocation[],
  excepted: ReadonlySet<string>,
  base: string,
): ScopeLocation[] {
  const tree = locationTree(locations);
  return locations.filter((location) =>
    excepted.has(location.slug) && ancestors(tree, location.slug).some((ancestor) => ancestor.slug === base));
}

/** How many names a Summary row says before it counts the rest. */
const SUMMARY_NAMED = 2;

/** " except New York", " except New York and Austin", or "". */
export function exceptPhrase(excepted: readonly ScopeLocation[]): string {
  if (excepted.length === 0) return "";
  const names = excepted.map((place) => placeName(place));
  return (" " + profileWalkModelExcept({ names: String(namedThenCounted(names, "and", 3)) }));
}

/** The chosen places inside a group, in words: "Brazil and Mexico",
    "Brazil, Mexico, Chile and 4 more", or, when most are on, "Every country
    except Cuba". Never a ratio. */
export function membersPhrase(locations: readonly ScopeLocation[], base: Base): string {
  const members = base.members ?? [];
  if (members.length === 0) return profileWalkModelNoChosenYet({ locations: String(childNoun(locations, base.slug)) });
  const union = unionOf(members);
  if (union) return union;
  const kids = childrenOf(locations, base.slug);
  const on = new Set(members.map((member) => member.slug));
  const left = kids.filter((kid) => !on.has(kid.slug));
  /* Cities inside a country never read "every city except": the roles filed
     at the country itself (remote, towns outside the metros) leave with the
     unticked city, a large share of a country's roles. Say what stays.
     A region's countries hold every role between them, so "every country
     except" stays true there. */
  if (childNoun(locations, base.slug) === "cities") {
    const names = members.map((member) => placeName(member));
    return profileWalkModelOnly({ names: String(namedThenCounted(names, "and", 3)) });
  }
  if (left.length > 0 && left.length <= 3 && left.length < members.length) {
    const noun = childNoun(locations, base.slug);
    const every = profileWalkModelEverywhere({ choice: (noun === "countries") ? "v1" : (noun === "cities") ? "v2" : "v3" });
    return profileWalkModelExcept2({ every: String(every), joinAnd: String(joinAnd(left.map((kid) => placeName(kid)))) });
  }
  const names = members.map((member) => placeName(member));
  return namedThenCounted(names, "and", 3);
}

export function joinAnd(parts: readonly string[]): string {
  if (parts.length <= 1) return parts[0] ?? "";
  return profileWalkModelAnd({ join: String(parts.slice(0, -1).join(", ")), parts: String(parts[parts.length - 1]) });
}

/** How far a base can reach: itself, then each ancestor. Never "anywhere":
    that is not a reach of one base but the whole world, and offered inside a
    row it would swallow the other bases while reading as a property of this
    one. It is its own control: `anywhereSlugs`. */
export function reachesOf(locations: readonly ScopeLocation[], slug: string): Reach[] {
  const tree = locationTree(locations);
  const place = tree.bySlug.get(slug);
  if (!place) return [];
  const own = isTown(place.kind)
    ? { slug: place.slug, label: profileWalkModelOnly2({ display: String(placeName(place)) }) }
    : { slug: place.slug, label: profileWalkModelAnywhereIn({ display: String(placeProse(placeName(place))) }) };
  const up = ancestors(tree, slug).map((ancestor) => ({
    slug: ancestor.slug,
    label: profileWalkModelAnywhereIn({ display: String(placeProse(placeName(ancestor))) }),
  }));
  return [own, ...up];
}

/* A place as a sentence says it. The catalog's display names are the formal
   ones ("United Kingdom"); read aloud, a person says "the UK". The short
   forms and the article are a copy decision, kept here so the sentence, the reach labels and the search rows agree. Row
   titles keep the formal name: a title is a label, not prose. */
const SHORT_NAMES: Record<string, string> = {
  "United Kingdom": "UK",
  "United States": "US",
  "United Arab Emirates": "UAE",
};
const WITH_ARTICLE = new Set(["UK", "US", "UAE", "Netherlands", "Philippines", "Bahamas", "European Union"]);

export function placeProse(display: string): string {
  const short = SHORT_NAMES[display] ?? display;
  return WITH_ARTICLE.has(short) ? profileWalkModelThePlace({ place: short }) : short;
}

/** The whole world: every top-level place. Replaces every base. */
export function anywhereSlugs(locations: readonly ScopeLocation[]): string[] {
  return locationTree(locations).topLevel.map((location) => location.slug);
}

/** The selected base that already implies `slug`, if any. */
export function coveredBy(locations: readonly ScopeLocation[], selected: Set<string>, slug: string): ScopeLocation | null {
  const tree = locationTree(locations);
  if (selected.has(slug)) return tree.bySlug.get(slug) ?? null;
  return ancestors(tree, slug).find((ancestor) => selected.has(ancestor.slug)) ?? null;
}

/** Replace one base's slug (and anything beneath the new one) with `reach`. */
export function withReach(
  locations: readonly ScopeLocation[],
  selected: Set<string>,
  base: string,
  reach: string,
): string[] {
  const tree = locationTree(locations);
  if (reach === ANYWHERE) return tree.topLevel.map((location) => location.slug);
  const next = new Set(selected);
  if (base === ANYWHERE) next.clear();
  next.delete(base);
  for (const below of descendants(tree, reach)) next.delete(below.slug);
  next.add(reach);
  return [...next];
}

export function withoutBase(locations: readonly ScopeLocation[], selected: Set<string>, base: string): string[] {
  if (base === ANYWHERE) return [];
  const tree = locationTree(locations);
  const drop = new Set([base, ...descendants(tree, base).map((location) => location.slug)]);
  return [...selected].filter((slug) => !drop.has(slug));
}

/** Add a base. A place already implied by a selected ancestor adds nothing. */
export function withBase(locations: readonly ScopeLocation[], selected: Set<string>, slug: string): string[] {
  const tree = locationTree(locations);
  if (isAnywhere(tree, selected)) return [...selected];
  if (ancestors(tree, slug).some((ancestor) => selected.has(ancestor.slug))) return [...selected];
  const next = new Set(selected);
  for (const below of descendants(tree, slug)) next.delete(below.slug);
  next.add(slug);
  return [...next];
}

export function findPlaces(locations: readonly ScopeLocation[], query: string, cap = 12): ScopeLocation[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return [];
  return locations
    .filter((location) =>
      placeName(location).toLowerCase().includes(needle) || location.display.toLowerCase().includes(needle) || location.slug.replace(/_/g, " ").includes(needle))
    .slice(0, cap);
}

/** The base rows as the sentence says them: "in London", "anywhere in the
    UK". The adverb is said once for every wide base — "anywhere in the UK or
    the US", never "anywhere in … or anywhere in …". */
export function wherePhrase(
  locations: readonly ScopeLocation[],
  selected: Set<string>,
  excepted: ReadonlySet<string> = new Set(),
  short = false,
): string | null {
  const bases = basesOf(locations, selected);
  if (bases.length === 0) return null;
  if (bases.some((base) => base.kind === "anywhere")) return "anywhere";
  // A group says its members: "anywhere in Brazil or Mexico", not the region.
  type Spoken = { display: string; kind: Base["kind"] };
  const places = bases.flatMap((base): Spoken[] => {
    if (base.kind !== "group") return [base];
    const union = unionOf(base.members ?? []);
    if (union) return [{ display: union, kind: "region" }];
    return (base.members ?? []).map((member) => ({ display: placeName(member), kind: member.kind }));
  });
  if (places.length === 0) return null;
  // Exceptions are said once, at the end: "anywhere in the US, except New York".
  const except = exceptPhrase(locations.filter((location) => exceptionsUnder(locations, selected, excepted).includes(location.slug)));
  const tail = except ? `,${except}` : "";
  // The Summary's short form: places named, the rest counted, as every
  // Summary row reads. Cities first, as the full
  // sentence orders them; an exception still says what is left out.
  if (short && places.length > SUMMARY_NAMED + 1) {
    const ordered = [...places.filter((base) => isTown(base.kind)), ...places.filter((base) => !isTown(base.kind))];
    return `${namedThenCounted(ordered.map((base) => (isTown(base.kind) ? base.display : placeProse(base.display))), "or")}${tail}`;
  }
  const cities = places.filter((base) => isTown(base.kind)).map((base) => profileWalkModelIn({ display: String(base.display) }));
  const wide = places.filter((base) => !isTown(base.kind)).map((base) => placeProse(base.display));
  const parts = [...cities];
  if (wide.length > 0) parts.push(profileWalkModelAnywhereIn2({ wide: String(joinOr(wide)) }));
  return `${joinOr(parts)}${tail}`;
}

/* ---- Modifiers: the worlds set as a list of lines.
 *
 * Two verbs. "Interested in X" keeps roles about X (and, because the gate
 * fails open, roles with no subject yet); roles only about other subjects
 * leave. "Not interested in X" turns X off. Both are the one stored set the
 * worlds gate already reads: interests, when there are any, else everything,
 * minus what is avoided. A saved profile reads back as the lines that produce
 * it (`linesFrom`). */

export type Verb = "interested" | "avoid";

/** The two verbs as the person reads them: symmetric, the second the exact
    negative of the first. */
export const VERB_LABELS: Record<Verb, string> = {
  get interested() { return profileWalkModelInterestedIn(); },
  get avoid() { return profileWalkModelNotInterestedIn(); },
};

export interface ModifierLine {
  verb: Verb;
  subject: string;
}

export function domainsOf(all: readonly string[], lines: readonly ModifierLine[]): string[] {
  const interests = lines.filter((line) => line.verb === "interested").map((line) => line.subject);
  const avoided = new Set(lines.filter((line) => line.verb === "avoid").map((line) => line.subject));
  const base = interests.length > 0 ? interests : [...all];
  return base.filter((slug) => !avoided.has(slug));
}

/** The subjects the "not interested in" lines exclude: the veto list the
    gate reads apart from the worlds set, so a role about an excluded subject
    drops whatever else it is about. */
export function excludedOf(all: readonly string[], lines: readonly ModifierLine[]): string[] {
  const avoided = new Set(lines.filter((line) => line.verb === "avoid").map((line) => line.subject));
  return all.filter((slug) => avoided.has(slug));
}

/** The lines a saved profile means. The avoid lines ARE the excluded list,
    since every one is written there, and the interests are whatever the worlds
    set keeps beyond "everything not excluded", so the verbs come back exactly
    as written. With no excluded list nothing was avoided: a worlds set short
    of everything is its interests, however many there are. */
export function linesFrom(all: readonly string[], enabled: Set<string>, excluded: Set<string>): ModifierLine[] {
  if (excluded.size === 0) {
    const on = all.filter((slug) => enabled.has(slug));
    return on.length === all.length ? [] : on.map((subject): ModifierLine => ({ verb: "interested", subject }));
  }
  const rest = all.filter((slug) => !excluded.has(slug));
  const interests = rest.every((slug) => enabled.has(slug)) ? [] : rest.filter((slug) => enabled.has(slug));
  return [
    ...interests.map((subject): ModifierLine => ({ verb: "interested", subject })),
    ...all.filter((slug) => excluded.has(slug)).map((subject): ModifierLine => ({ verb: "avoid", subject })),
  ];
}

export function withLine(lines: readonly ModifierLine[], line: ModifierLine): ModifierLine[] {
  const rest = lines.filter((existing) => existing.subject !== line.subject);
  return [...rest, line];
}

export function withoutLine(lines: readonly ModifierLine[], subject: string): ModifierLine[] {
  return lines.filter((line) => line.subject !== subject);
}

/* ---- The phrases on the sheet. */

export function joinOr(parts: readonly string[]): string {
  if (parts.length <= 1) return parts[0] ?? "";
  if (parts.length === 2) return profileWalkModelOr3({ parts: String(parts[0]), parts2: String(parts[1]) });
  return profileWalkModelOr({ join: String(parts.slice(0, -1).join(", ")), parts: String(parts[parts.length - 1]) });
}

/** The kinds of role answered, without their narrowing: "leading a team or
    hands-on"; four read "leading a team, owning a product, or 2 more". Lower case, in the order of the answers; null until an answer
    exists. The narrowing is its own Summary row (`whichRolesPhrase`): said
    here as well, four narrowed answers would run to five lines. */
export function accountablePhrase(answers: Answers): string | null {
  const phrases = ACCOUNTABLE.filter((answer) => answers.has(answer.slug)).map((answer) => answer.phrase);
  if (phrases.length === 0) return null;
  return namedThenCounted(phrases, "or");
}

/** The Summary's "Which roles" row: the roles picked where an answer
    narrows, in the order of the answers, named then counted ("engineers,
    product management, or 3 more"). An answer left at any role adds nothing:
    the Role row already says it. Null when nothing narrows. Which kind each
    role belongs to is the step's to show; naming it here too would run past
    two lines at the Summary's column width. */
/** Whether Which roles keeps fewer than every role of some picked kind. A
    blank draft (`null`) keeps them all. */
export function rolesNarrowed(answers: Answers | null): boolean {
  return answers !== null && ACCOUNTABLE.some((answer) => {
    const chosen = answers.get(answer.slug);
    return chosen !== undefined && chosen !== "any";
  });
}

export function whichRolesPhrase(answers: Answers): string | null {
  const roles = ACCOUNTABLE.flatMap((answer) => {
    const chosen = answers.get(answer.slug);
    return chosen === undefined || chosen === "any" ? [] : rowsPicked(answer.slug, chosen).map((row) => midSentence(row.label));
  });
  return roles.length === 0 ? null : namedThenCounted([...new Set(roles)], "or");
}

/** A label said mid-sentence: only its first letter drops to lower case, and
    not even that when the first word is an acronym. Lower-casing the whole
    label would print "infrastructure / sre" and "ml & ai research". */
function midSentence(label: string): string {
  const first = label.split(/[\s/&,]/, 1)[0];
  return /^[A-Z0-9]{2,}$/.test(first) ? label : label.charAt(0).toLowerCase() + label.slice(1);
}

/** At most `named` names, then a count: "AI & Machine Learning, Cloud &
    Infrastructure and 7 more". One more than `named` is still said in full,
    because "and 1 more" says less than the name. Every Summary row reads this
    way at any size, so no one's answers can grow the Summary past two lines.
    `word` joins the count: "or" for a list of
    alternatives, with the comma `joinOr` puts before it ("London, Paris, or
    2 more"). */
export function namedThenCounted(names: readonly string[], word: "and" | "or" = "and", named = SUMMARY_NAMED): string {
  if (names.length <= named + 1) return word === "and" ? joinAnd(names) : joinOr(names);
  const said = names.slice(0, named).join(", ");
  const comma = word === "or" && named > 1 ? "," : "";
  return profileWalkModelMore({ said: String(said), comma: String(comma), word: String(word), value: names.length - named });
}

/** The World row on the Summary: what is on, then what is off, one line
    each: ONE subject named, the rest counted, because subject names are long
    ("Media & Entertainment") and two of them would wrap each line in two at
    the Summary's column width. Empty with no lines. */
export function interestsRows(lines: readonly ModifierLine[], display: (slug: string) => string): string[] {
  const names = (verb: Verb) => lines.filter((line) => line.verb === verb).map((line) => display(line.subject));
  const on = names("interested");
  const off = names("avoid");
  return [
    ...(on.length > 0 ? [namedThenCounted(on, "and", 1)] : []),
    ...(off.length > 0 ? [profileWalkModelNot({ off: String(namedThenCounted(off, "and", 1)) })] : []),
  ];
}

export function levelPhrase(
  levels: readonly { slug: string; order: number }[],
  experience: string | null,
  target: string | null,
  bands: Set<string>,
): string | null {
  const ordered = [...levels].sort((a, b) => a.order - b.order);
  const display = (slug: string) => levelName(slug);
  if (experience && target) {
    const lo = ordered.findIndex((level) => level.slug === experience);
    const hi = ordered.findIndex((level) => level.slug === target);
    if (lo >= 0 && hi >= 0) {
      const [first, last] = lo <= hi ? [experience, target] : [target, experience];
      return profileWalkModelFromTo({ choice: (first === last) ? "yes" : "no", first: (first === last) ? String(display(first)) : "", first2: (first === last) ? "" : String(display(first)), last: (first === last) ? "" : String(display(last)) });
    }
  }
  const on = ordered.filter((level) => bands.has(level.slug));
  if (on.length === 0) return null;
  return profileWalkModelFromTo2({ count: on.length, display: (on.length === 1) ? String(levelName(on[0].slug)) : "", display2: (on.length === 1) ? "" : String(levelName(on[0].slug)), display3: (on.length === 1) ? "" : String(levelName(on[on.length - 1].slug)) });
}

/** The five answers as the Summary's "Tuned for" table says them, and as the
    rail's funnel names them before anything is counted: sentence case, with a
    word for an answer not given yet. Interests may take two rows. */
export function tunedFor(
  draft: {
    answers: Answers;
    experience: string | null;
    target: string | null;
    bands: Set<string>;
    levels: readonly { slug: string; order: number }[];
    locations: readonly ScopeLocation[];
    places: Set<string>;
    excepted: ReadonlySet<string>;
  },
  lines: readonly ModifierLine[],
  display: (slug: string) => string,
): { accountable: string; level: string; where: string; roles: string; subjects: string[] } {
  const lead = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);
  const accountable = accountablePhrase(draft.answers);
  const level = levelPhrase(draft.levels, draft.experience, draft.target, draft.bands);
  const where = wherePhrase(draft.locations, draft.places, draft.excepted, true);
  const narrowing = whichRolesPhrase(draft.answers);
  const interests = interestsRows(lines, display);
  return {
    accountable: accountable ? lead(accountable) : profileSummaryStepNothingPickedYet(),
    level: level ? lead(level) : profileSummaryStepNotSet(),
    where: where ? lead(where) : profileSummaryStepNotSet(),
    roles: !accountable ? profileSummaryStepNothingPickedYet() : narrowing ? lead(narrowing) : profileSummaryStepAnyRoleThatFits(),
    subjects: interests.length === 0 ? [profileSummaryStepNoneYet()] : interests,
  };
}
