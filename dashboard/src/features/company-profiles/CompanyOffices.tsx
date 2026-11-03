import { compare as copyCompare } from "../../copy/format";
import { SearchField } from "../../ui/SearchField";
import { useMemo, useState } from "react";
import { CompanyLocation } from "../../api";
import { LOC_LABEL, flagEmoji } from "../../format";
import { Button, FilterSelect, Icon } from "../../ui";
import "./CompanyOffices.css";
import {
  profilesCompanyOfficesCities,
  profilesCompanyOfficesCountry,
  profilesCompanyOfficesHq,
  profilesCompanyOfficesLocationNotMapped,
  profilesCompanyOfficesNoOfficeMatchesThatSearch,
  profilesCompanyOfficesOfficesIn,
  profilesCompanyOfficesOpen,
  profilesCompanyOfficesSearchCities,
  profilesCompanyOfficesSearchCities2,
  profilesCompanyOfficesShowFewer,
  profilesCompanyOfficesText,
} from "../../copy/gen/profiles";
import { Msg } from "../../ui/Msg";

// Offices & open roles, grouped by country.
//
// A large employer lists hundreds of cities, most of them in one country, so
// country dividers alone do not make the list readable. The panel groups by
// country AND caps each section at TOP_N with a "show the rest" disclosure,
// the same secondary-population idiom the Settings screens use.
//
// Grouping is per city, and a city belongs to exactly one country, so summing
// section sizes is safe here. Summing `open_count` across cities is NOT the
// company's open-role count: a posting listing three cities counts in all three
// (`unnest(location_cities)`). Sections therefore report a city count and leave
// the per-city numbers to speak for themselves.

const TOP_N = 6;

/** Cities whose country the taxonomy could not resolve. Never dropped: `de` is
    deliberately excluded from US state tokens and Canadian province abbrevs are
    not admitted, so this bucket holds real offices, not junk. */
const UNMAPPED = "__unmapped__";

interface CountrySection {
  country: string;
  label: string;
  flag: string;
  cities: CompanyLocation[];
  openTotal: number;
}

/** Countries busiest-first by open roles, then by city count, then by name.
    Unmapped always sinks to the bottom — it is a data gap, not a market. */
export function groupByCountry(locations: CompanyLocation[]): CountrySection[] {
  const byCountry = new Map<string, CompanyLocation[]>();
  for (const loc of locations) {
    const key = loc.country ?? UNMAPPED;
    const bucket = byCountry.get(key);
    if (bucket) bucket.push(loc);
    else byCountry.set(key, [loc]);
  }
  const sections: CountrySection[] = [];
  for (const [country, cities] of byCountry) {
    sections.push({
      country,
      label: country === UNMAPPED ? profilesCompanyOfficesLocationNotMapped() : LOC_LABEL[country] ?? country,
      flag: flagEmoji(country === UNMAPPED ? null : country),
      // HQ first, then the backend's busiest-first order.
      cities: [...cities].sort((a, b) => Number(b.is_hq) - Number(a.is_hq)),
      openTotal: cities.reduce((n, c) => n + c.open_count, 0),
    });
  }
  return sections.sort((a, b) => {
    if (a.country === UNMAPPED) return 1;
    if (b.country === UNMAPPED) return -1;
    return (
      b.openTotal - a.openTotal ||
      b.cities.length - a.cities.length ||
      copyCompare(a.label, b.label)
    );
  });
}

export function CompanyOffices({ locations }: { locations: CompanyLocation[] }) {
  const [query, setQuery] = useState("");
  const [countries, setCountries] = useState<string[]>([]);
  // Which sections the user expanded past TOP_N. Keyed by country so a filter
  // change does not silently re-collapse a section they opened.
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const allSections = useMemo(() => groupByCountry(locations), [locations]);

  const options = useMemo(
    () =>
      allSections.map((s) => ({
        value: s.country,
        label: s.label,
        count: s.cities.length,
      })),
    [allSections],
  );

  const q = query.trim().toLowerCase();
  const sections = useMemo(() => {
    const picked = new Set(countries);
    return allSections
      .filter((s) => picked.size === 0 || picked.has(s.country))
      .map((s) => (q ? { ...s, cities: s.cities.filter((c) => c.city.toLowerCase().includes(q)) } : s))
      // A section matching nothing is removed, never shown empty.
      .filter((s) => s.cities.length > 0);
  }, [allSections, countries, q]);

  const shownCities = sections.reduce((n, s) => n + s.cities.length, 0);
  const narrowed = shownCities !== locations.length;

  return (
    <div className="offices">
      <div className="offices-toolbar">
        <SearchField
          size="sm"
          className="offices-search"
          label={profilesCompanyOfficesSearchCities()}
          placeholder={profilesCompanyOfficesSearchCities2()}
          value={query}
          onChange={setQuery}
        />
        <FilterSelect
          label={profilesCompanyOfficesCountry()}
          options={options}
          selected={countries}
          onChange={setCountries}
          searchable={options.length > 8}
          /* Same three slots the primitive renders by default, plus the flag —
             the option must keep its check mark, so this reproduces the
             primitive's own classes rather than replacing them. */
          renderOption={(o, on) => (
            <>
              <span className="ui-filterselect-mark" aria-hidden="true">
                {on ? <Icon name="check" size={12} /> : null}
              </span>
              <span className="ui-filterselect-label">
                <span className="offices-opt-flag" aria-hidden="true">
                  {flagEmoji(o.value)}
                </span>
                {o.label}
              </span>
              <span className="ui-filterselect-count">{o.count}</span>
            </>
          )}
        />
        <span className="offices-tally">
          {profilesCompanyOfficesText({ choice: (narrowed) ? "yes" : "no", shownCities: (narrowed) ? shownCities : "", length: (narrowed) ? locations.length : "", length2: (narrowed) ? "" : locations.length, value: (narrowed) ? "" : profilesCompanyOfficesCities({ count: locations.length }) })}
        </span>
      </div>

      {sections.length === 0 ? (
        <div className="empty-hint">{profilesCompanyOfficesNoOfficeMatchesThatSearch()}</div>
      ) : (
        sections.map((s) => {
          // An active search already narrowed the section — showing a "show
          // more" behind a query the user typed just hides their own results.
          const open = expanded.has(s.country) || q.length > 0;
          const visible = open ? s.cities : s.cities.slice(0, TOP_N);
          const hidden = s.cities.length - visible.length;
          return (
            <section className="offices-country" key={s.country}>
              <h4 className="offices-country-head">
                <span className="offices-flag" aria-hidden="true">
                  {s.flag}
                </span>
                <span className="offices-country-name">{s.label}</span>
                <span className="offices-country-meta">
                  {s.cities.length} {profilesCompanyOfficesCities({ count: s.cities.length })}
                </span>
              </h4>
              <ul className="office-list" aria-label={profilesCompanyOfficesOfficesIn({ label: String(s.label) })}>
                {visible.map((loc) => (
                  <li key={loc.city}>
                    <span className="office-city">
                      {loc.city}
                      {loc.is_hq && <span className="office-hq-tag">{profilesCompanyOfficesHq()}</span>}
                    </span>
                    <span className="office-count"><Msg of={profilesCompanyOfficesOpen} elems={{ open_count: loc.open_count }} /></span>
                  </li>
                ))}
              </ul>
              {/* Only offered when there is something to hide or reveal — a
                  search that already narrowed the section past TOP_N leaves
                  nothing to disclose. */}
              {(hidden > 0 || (open && !q && s.cities.length > TOP_N)) && (
                <Button
                  variant="link"
                  className="ui-btn-quiet"
                  aria-expanded={hidden === 0}
                  onClick={() =>
                    setExpanded((prev) => {
                      const next = new Set(prev);
                      if (!next.delete(s.country)) next.add(s.country);
                      return next;
                    })
                  }
                >
                  {profilesCompanyOfficesShowFewer({ choice: (hidden > 0) ? "yes" : "no", hidden: (hidden > 0) ? hidden : "", label: (hidden > 0) ? String(s.label) : "" })}
                </Button>
              )}
            </section>
          );
        })
      )}
    </div>
  );
}
