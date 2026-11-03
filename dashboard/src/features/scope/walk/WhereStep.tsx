import { useEffect, useRef, useState } from "react";
import { Button } from "../../../ui/Button";
import { CardRow } from "../../../ui/Card";
import { SearchField } from "../../../ui/SearchField";
import { Segmented } from "../../../ui/Segmented";
import { api, type PlaceResult, type ScopeLocation, type UnionResult } from "../../../api";
import { companyName } from "../../../format";
import { NewMark } from "../NewMark";
import { useScopeDraft } from "../useScopeDraft";
import {
  ANYWHERE, anywhereSlugs, basesOf, canChoose, childNoun, childState, childrenOf, coveredBy, exceptPhrase, exceptedIn,
  exceptionsUnder, findPlaces, joinAnd, joinOr, locationTree, membersPhrase, placeProse, reachesOf, withBase, withChildPlaces,
  withReach, withoutBase,
} from "./walkModel";
import { unscannedPlaces } from "./walkProgress";
import {
  profileProgressRailCountNow,
  profileScopeSectionRemove,
  profileWhereStepAdd,
  profileWhereStepAdd2,
  profileWhereStepAddAnotherPlace,
  profileWhereStepAddAnotherPlace2,
  profileWhereStepAddBack,
  profileWhereStepAllMemberCountries,
  profileWhereStepAndMore,
  profileWhereStepAnyCountryAnyCity,
  profileWhereStepChoose,
  profileWhereStepChooseIn,
  profileWhereStepCareersSitesCantBeSearched,
  profileWhereStepExceptedAddItBack,
  profileWhereStepFilter,
  profileWhereStepFilterIn,
  profileWhereStepGoWorldwide,
  profileWhereStepHavenTBeenScannedFor,
  profileWhereStepHowFarFrom,
  profileWhereStepIn,
  profileWhereStepInChooseToNarrowTo,
  profileWhereStepIncludeAll,
  profileWhereStepIncludeAllOf,
  profileWhereStepNothingCalledIn,
  profileWhereStepNothingCalledTryACity,
  profileWhereStepPlaces,
  profileWhereStepRemove,
  profileWhereStepReplacesThePlacesYouVe,
  profileWhereStepYourBases,
} from "../../../copy/gen/profile";
import { Msg } from "../../../ui/Msg";
import { placeName } from "../../../copy/vocab";

/** Past this many places inside, the chooser gets its own filter. */
const CHOOSER_FILTER_AT = 12;
/** How long typing pauses before the place search is asked. */
const SEARCH_DEBOUNCE_MS = 150;

type Found = { query: string; places: PlaceResult[]; unions: UnionResult[] };
/** A search row: the place, where it is in words, and the other name it was
    found by ("Bangalore" for Bengaluru). */
type Row = { node: ScopeLocation; context: string; alias: string | null };

/* Step 3: where, as a base and a reach. The user names a place and says how
   far they would go; each base is one register row — the place, the reach it
   currently means in words, and the reach as a segmented control of the
   places it can widen to — and a second base covers the US-and-UK case. No
   region list: a region is reached by typing it, or by widening a base to it.
   The search leads the step and the bases read back under it, as every
   other add-then-list surface in the app does. The whole world is one
   button, "Go worldwide", on the search's row at the far side, never a
   reach inside a base, where it would swallow the other bases. It shares
   the search's row so a second base fits the stage-1 frame. Anywhere keeps
   the search: a place named after it replaces it, so a click on Go
   worldwide is undone by naming the place meant. The coverage note stays
   one sentence: a source that cannot be asked about a place is a standing
   property of that source, not a fault of this answer.

   A place with places inside it can be narrowed ("Choose countries in
   Latin America"): the whole place is the default, the chooser lists what
   is inside, and unticking one excepts it: the row reads "Anywhere in the
   US except New York", and roles filed at the US itself stay. A place made
   of chosen members ("Latin America: Brazil and Mexico") narrows by members
   instead. While it is open the other bases, the search and Go worldwide
   step aside: the step holds one task at a time. The chooser may grow the card, so Continue moves down, never up.

   The search asks the server, which knows every standard place:
   countries by their CLDR names and old ones ("Turkey" finds Türkiye),
   regions by their UN M49 names, the European Union, and the cities of its
   place index. The catalog's own places answer instantly while
   it is asked, and alone if it cannot be reached. */
export function WhereStep() {
  const { catalog, selectedLocations, selectedExcepted, replacePlaces, learnPlaces, refreshing, refreshInventory } = useScopeDraft();
  const [query, setQuery] = useState("");
  const [found, setFound] = useState<Found | null>(null);
  const [choosing, setChoosing] = useState<string | null>(null);
  const [inside, setInside] = useState("");
  const chooserRef = useRef<HTMLElement>(null);
  const returnTo = useRef<string | null>(null);

  useEffect(() => {
    if (choosing) {
      chooserRef.current?.querySelector<HTMLInputElement>("input")?.focus();
    } else if (returnTo.current) {
      document.getElementById(`walk-choose-${returnTo.current}`)?.focus();
      returnTo.current = null;
    }
  }, [choosing]);

  useEffect(() => {
    const needle = query.trim();
    if (needle.length < 2) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      api.searchPlaces(needle, 10, controller.signal)
        .then((result) => setFound({ query: needle, places: result.places, unions: result.unions }))
        .catch(() => {});
    }, SEARCH_DEBOUNCE_MS);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [query]);

  if (!catalog) return null;

  const listed = catalog.locations ?? [];
  const bases = basesOf(listed, selectedLocations, choosing);
  const chooserBase = choosing ? bases.find((base) => base.slug === choosing) ?? null : null;
  const openChooser = (slug: string) => {
    setInside("");
    setChoosing(slug);
  };
  const closeChooser = () => {
    returnTo.current = choosing;
    setChoosing(null);
  };
  const anywhere = bases.some((base) => base.slug === ANYWHERE);
  const catalogTree = locationTree(listed);
  const remote = found && found.query === query.trim() ? found : null;
  /* A place the catalog does not list (a city) becomes a node here, with the
     coverage of the nearest place above it that the catalog does list. */
  const nodeFor = (place: PlaceResult): ScopeLocation => {
    const known = catalogTree.bySlug.get(place.slug);
    if (known) return known;
    let above = place.parent ? catalogTree.bySlug.get(place.parent) : undefined;
    while (above && above.uncovered_by === undefined && above.parent) above = catalogTree.bySlug.get(above.parent);
    return {
      slug: place.slug, display: place.display, kind: place.kind, parent: place.parent,
      count: 0, selected: false, default_enabled: false, prominent: true, new: false,
      uncovered_by: above?.uncovered_by ?? [],
    };
  };
  const remoteRows: Row[] = (remote?.places ?? []).map((place) => ({
    node: nodeFor(place), context: place.context, alias: place.matched_by,
  }));
  const locations = [
    ...listed,
    ...remoteRows.map((row) => row.node).filter((node) => !catalogTree.bySlug.has(node.slug)),
  ];
  const localRows: Row[] = findPlaces(listed, query).map((node) => ({ node, context: "", alias: null }));
  const rows: Row[] = remote
    ? [...remoteRows, ...localRows.filter((row) => !remoteRows.some((r) => r.node.slug === row.node.slug))]
    : localRows;
  const unions = remote?.unions ?? [];
  const tree = locationTree(locations);
  /* Every edit here writes the places and the exceptions together, keeping
     only the exceptions still inside an included place. */
  const replaceLocations = (next: string[]) =>
    replacePlaces(next, exceptionsUnder(locations, new Set(next), selectedExcepted));
  const display = (slug: string) => { const node = tree.bySlug.get(slug); return node ? placeName(node) : slug; };
  const lineage = (slug: string) => {
    const names: string[] = [];
    let current = tree.bySlug.get(slug);
    while (current?.parent && tree.bySlug.has(current.parent)) {
      current = tree.bySlug.get(current.parent)!;
      names.push(placeName(current));
    }
    return names.join(" · ");
  };

  const coverageGaps = new Map<string, string[]>();
  const addGap = (company: string, market: string) => {
    const markets = coverageGaps.get(company);
    if (markets) markets.push(market);
    else coverageGaps.set(company, [market]);
  };
  for (const base of bases) {
    if (base.kind !== "group") {
      for (const company of tree.bySlug.get(base.slug)?.uncovered_by ?? []) addGap(company, base.display);
      continue;
    }
    // A narrowed place is named as the place when the gap covers most of
    // what was kept: one sentence, never a list of 32 countries.
    const members = base.members ?? [];
    const gapsIn = new Map<string, string[]>();
    for (const member of members) {
      for (const company of tree.bySlug.get(member.slug)?.uncovered_by ?? []) {
        gapsIn.set(company, [...(gapsIn.get(company) ?? []), placeName(member)]);
      }
    }
    for (const [company, names] of gapsIn) {
      if (names.length > 3) addGap(company, base.display);
      else for (const name of names) addGap(company, name);
    }
  }
  // Companies that miss the same places share one sentence.
  const gapSentences = new Map<string, { companies: string[]; places: string[] }>();
  for (const [company, markets] of coverageGaps) {
    const key = markets.join("\n");
    const name = String(companyName(company));
    const sentence = gapSentences.get(key);
    if (sentence) sentence.companies.push(name);
    else gapSentences.set(key, { companies: [name], places: markets });
  }

  /* A verb on the button, a state on the row it produces ("Anywhere · Any
     country, any city."). It replaces the bases, so with any named it says so. */
  const goAnywhere = (
    <Button
      variant="ghost"
      size={bases.length === 0 ? "lg" : "md"}
      className="walk-worldwide"
      title={bases.length === 0 ? undefined : profileWhereStepReplacesThePlacesYouVe()}
      onClick={() => {
        // Anywhere replaces every base, and the exceptions made inside them.
        replacePlaces(anywhereSlugs(locations), []);
        setQuery("");
      }}
    >
      {profileWhereStepGoWorldwide()}
    </Button>
  );

  const placeRow = ({ node: place, context, alias }: Row) => {
    // Under anywhere every place is covered, and picking one means "this
    // instead": it replaces anywhere rather than narrowing one region of it.
    const covering = anywhere ? null : coveredBy(locations, selectedLocations, place.slug);
    const where = context || lineage(place.slug);
    // Namesakes ("Portland") are told apart by where they are.
    const name = place.kind === "city" && where ? `${placeName(place)}, ${where}` : placeName(place);
    const detail = covering
      ? [
        place.kind === "city" ? where.split(",")[0] : "",
        profileWhereStepInChooseToNarrowTo({ choice: (covering.slug === place.slug) ? "yes" : "no", display: (covering.slug === place.slug) ? "" : String(placeProse(placeName(covering))) }),
      ].filter(Boolean).join(" · ")
      : [alias ? `“${alias}”` : "", where].filter(Boolean).join(" · ");
    const added = covering?.slug === place.slug;
    // A place excepted inside a base comes back by being named again.
    if (selectedExcepted.has(place.slug)) {
      return (
        <li key={place.slug}>
          <Button
            variant="ghost"
            className="walk-place"
            aria-label={profileWhereStepAddBack({ name: String(name) })}
            onClick={() => {
              replacePlaces([...selectedLocations], [...selectedExcepted].filter((slug) => slug !== place.slug));
              setQuery("");
            }}
          >
            <span className="walk-place-name">{placeName(place)}</span>
            <span className="walk-place-lineage">{[where, profileWhereStepExceptedAddItBack()].filter(Boolean).join(" · ")}</span>
          </Button>
        </li>
      );
    }
    return (
      <li key={place.slug}>
        <Button
          variant="ghost"
          className="walk-place"
          disabled={added}
          aria-label={profileWhereStepAdd({ choice: (covering && !added) ? "yes" : "no", display: (covering && !added) ? String(placeProse(placeName(covering))) : "", name: (covering && !added) ? String(name) : "", name2: (covering && !added) ? "" : String(name) })}
          onClick={() => {
            if (!catalogTree.bySlug.has(place.slug)) learnPlaces([place]);
            // A place a base already covers narrows that base to it: the
            // person picked it, so it becomes the answer.
            replaceLocations(anywhere ? withBase(locations, new Set(), place.slug)
              : covering ? withReach(locations, selectedLocations, covering.slug, place.slug)
              : withBase(locations, selectedLocations, place.slug));
            setQuery("");
          }}
        >
          <span className="walk-place-name">{placeName(place)} <NewMark on={Boolean(place.new)} /></span>
          <span className="walk-place-lineage">{detail}</span>
        </Button>
      </li>
    );
  };

  const unionRow = (union: UnionResult) => {
    const members = union.members.filter((slug) => catalogTree.bySlug.has(slug));
    const covered = !anywhere && members.every((slug) => coveredBy(locations, selectedLocations, slug));
    return (
      <li key={union.slug}>
        <Button
          variant="ghost"
          className="walk-place"
          disabled={covered}
          aria-label={profileWhereStepAdd2({ display: String(union.display) })}
          onClick={() => {
            let next = anywhere ? new Set<string>() : new Set(selectedLocations);
            for (const slug of members) next = new Set(withBase(locations, next, slug));
            replaceLocations([...next]);
            setQuery("");
          }}
        >
          <span className="walk-place-name">{union.display}</span>
          <span className="walk-place-lineage">{profileWhereStepAllMemberCountries({ choice: (covered) ? "yes" : "no", length: (covered) ? "" : members.length })}</span>
        </Button>
      </li>
    );
  };

  return (
    <>
      {!chooserBase && (
        <div className="walk-add-row">
          <div className="walk-add-base">
            <SearchField
              size={bases.length === 0 ? "lg" : "md"}
              label={profileWhereStepAddAnotherPlace({ choice: (bases.length === 0) ? "v1" : (anywhere) ? "v2" : "v3" })}
              placeholder={profileWhereStepAddAnotherPlace2({ choice: (bases.length === 0) ? "v1" : (anywhere) ? "v2" : "v3" })}
              value={query}
              onChange={setQuery}
            />
            {query.trim() && (
              <ul className="walk-places" aria-label={profileWhereStepPlaces()}>
                {rows.filter((row) => row.node.kind !== "city").map(placeRow)}
                {/* A union after the countries and regions, before any town. */}
                {unions.map(unionRow)}
                {rows.filter((row) => row.node.kind === "city").map(placeRow)}
                {rows.length === 0 && unions.length === 0 && (
                  <li className="walk-empty"><Msg of={profileWhereStepNothingCalledTryACity} elems={{ query: query.trim() }} /></li>
                )}
              </ul>
            )}
          </div>
          {!anywhere && goAnywhere}
        </div>
      )}

      {bases.length > 0 && (
        <ul className="walk-register walk-bases" aria-label={profileWhereStepYourBases()}>
          {bases.filter((base) => !chooserBase || base.slug === chooserBase.slug).map((base) => {
            const group = base.kind === "group";
            const reaches = base.kind === "anywhere" || group ? [] : reachesOf(locations, base.slug);
            const reach = reaches.find((option) => option.slug === base.slug);
            const choosable = base.kind !== "anywhere" && canChoose(locations, base.slug);
            const noun = choosable ? childNoun(locations, base.slug) : "";
            const open = choosing === base.slug;
            const excepted = base.kind === "anywhere" ? [] : exceptedIn(locations, selectedExcepted, base.slug);
            return (
              <li key={base.slug}>
                <CardRow
                  title={base.display}
                  description={
                    base.kind === "anywhere" ? profileWhereStepAnyCountryAnyCity()
                      : group ? membersPhrase(locations, base) : `${reach?.label ?? base.display}${exceptPhrase(excepted)}`
                  }
                  trailing={
                    <>
                      {excepted.length > 0 && (
                        <Button
                          variant="link"
                          aria-label={profileWhereStepIncludeAllOf({ display: String(base.display) })}
                          onClick={() => replacePlaces(
                            [...selectedLocations],
                            [...selectedExcepted].filter((slug) => !excepted.some((place) => place.slug === slug)),
                          )}
                        >
                          {profileWhereStepIncludeAll()}
                        </Button>
                      )}
                      {group && (base.members?.length ?? 0) > 0 && (
                        <Button
                          variant="link"
                          aria-label={profileWhereStepIncludeAllOf({ display: String(base.display) })}
                          onClick={() => replaceLocations(withBase(locations, selectedLocations, base.slug))}
                        >
                          {profileWhereStepIncludeAll()}
                        </Button>
                      )}
                      {choosable && (
                        <Button
                          id={`walk-choose-${base.slug}`}
                          variant="link"
                          className="ui-btn-quiet"
                          aria-expanded={open}
                          aria-label={profileWhereStepChooseIn({ choice: (open) ? "yes" : "no", noun: (open) ? String(noun) : "", display: (open) ? String(base.display) : "", noun2: (open) ? "" : String(noun), display2: (open) ? "" : String(base.display) })}
                          onClick={() => (open ? closeChooser() : openChooser(base.slug))}
                        >
                          {profileWhereStepChoose({ choice: (open) ? "yes" : "no", noun: (open) ? "" : String(noun) })}
                        </Button>
                      )}
                      {reaches.length > 1 && (
                        <Segmented
                          label={profileWhereStepHowFarFrom({ display: String(base.display) })}
                          value={base.slug}
                          onChange={(slug) => replaceLocations(withReach(locations, selectedLocations, base.slug, slug))}
                          options={reaches.map((option) => ({ value: option.slug, label: display(option.slug) }))}
                        />
                      )}
                      <Button
                        variant="link"
                        className="ui-btn-quiet"
                        aria-label={profileWhereStepRemove({ display: String(base.display) })}
                        onClick={() => {
                          if (open) setChoosing(null);
                          replaceLocations(withoutBase(locations, selectedLocations, base.slug));
                        }}
                      >
                        {profileScopeSectionRemove()}
                      </Button>
                    </>
                  }
                />
              </li>
            );
          })}
        </ul>
      )}

      {chooserBase && (() => {
        const kids = childrenOf(locations, chooserBase.slug);
        const noun = childNoun(locations, chooserBase.slug);
        const needle = inside.trim().toLowerCase();
        const shown = needle ? kids.filter((kid) => placeName(kid).toLowerCase().includes(needle)) : kids;
        return (
          <section
            ref={chooserRef}
            className="walk-chooser"
            aria-label={profileWhereStepIn({ noun: String(noun[0].toUpperCase()), slice: String(noun.slice(1)), display: String(chooserBase.display) })}
          >
            {kids.length > CHOOSER_FILTER_AT && (
              <SearchField
                size="sm"
                className="walk-filter"
                label={profileWhereStepFilterIn({ noun: String(noun), display: String(chooserBase.display) })}
                placeholder={profileWhereStepFilter({ noun: String(noun) })}
                value={inside}
                onChange={setInside}
              />
            )}
            <ul className="walk-chooser-list">
              {shown.map((kid) => {
                const state = childState(locations, selectedLocations, chooserBase.slug, kid.slug, selectedExcepted);
                return (
                  <li key={kid.slug}>
                    <label className="loc-pick">
                      <input
                        type="checkbox"
                        checked={state === "on"}
                        ref={(input) => {
                          if (input) input.indeterminate = state === "mixed";
                        }}
                        onChange={() => {
                          const next = withChildPlaces(locations, selectedLocations, selectedExcepted, chooserBase.slug, kid.slug);
                          replacePlaces(next.locations, next.excepted);
                        }}
                      />
                      <span className="loc-pick-name">{placeName(kid)} <NewMark on={Boolean(kid.new)} /></span>
                    </label>
                  </li>
                );
              })}
              {shown.length === 0 && <li className="walk-empty"><Msg of={profileWhereStepNothingCalledIn} elems={{ inside: inside.trim(), display: chooserBase.display }} /></li>}
            </ul>
          </section>
        );
      })()}

      {/* A source that lists only the places it is asked for, never asked
          about one of these yet: its roles there are not counted.
          Count now asks for them, saved or not. */}
      {(() => {
        const unscanned = unscannedPlaces(catalog, selectedLocations);
        if (unscanned.companies.length === 0) return null;
        const few = (names: string[]) => names.length <= 3 ? joinAnd(names) : profileWhereStepAndMore({ join: String(names.slice(0, 3).join(", ")), value: names.length - 3 });
        return (
          <p className="walk-note" role="note">
            <Msg of={profileWhereStepHavenTBeenScannedFor} args={{ count: unscanned.companies.length }} elems={{ companies: few(unscanned.companies), few: few(unscanned.places.map(placeProse)) }} />{" "}
            <Button variant="link" className="ui-btn-quiet" onClick={refreshInventory} disabled={refreshing}>
              {profileProgressRailCountNow({ choice: (refreshing) ? "yes" : "no" })}
            </Button>
          </p>
        );
      })()}
      {gapSentences.size > 0 && (
        <p className="walk-note" role="note">
          {[...gapSentences.values()]
            .map(({ companies, places }) =>
              profileWhereStepCareersSitesCantBeSearched({
                count: companies.length,
                companies: String(joinAnd(companies)),
                places: String(joinOr(places.map(placeProse))),
              }))
            .join(" ")}
        </p>
      )}
    </>
  );
}
