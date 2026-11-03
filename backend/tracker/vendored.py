"""Provenance registry for code copied from upstream projects.

RoleBand installs no scraper engine (Scrapling is not a backend dependency),
and the only upstream code here is *vendored* — a RoleBand
snapshot reimplemented on our own engine, updated by ordinary reviewed change
and never by dependency automation. That policy is right, and it has one failure
mode: a snapshot nobody can tell is stale. Upstream fixes silently never arrive,
and nothing in the build notices.

So each vendored artifact records where it came from, pinned to an immutable ref
and the **sha256 of the exact upstream blob** at that ref.
`scripts.check_vendored_upstream` re-fetches and compares; the hash is what makes
"has upstream moved?" a decidable question instead of a memory.

The pin is on the artifact, not on the release, deliberately. Upstream ships
releases that do not touch the file we copied, and a checker that fired on
every tag would be noise, which is how a check stops being read.

Registered here rather than in a docstring because prose provenance rots
unverified. A hash does not.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["VENDORED", "VendoredArtifact", "by_name"]


@dataclass(frozen=True)
class VendoredArtifact:
    """One RoleBand file derived from an upstream source.

    ``sha256`` is the digest of the raw upstream blob at ``ref`` — not of our
    file, which is a reimplementation and will never match.
    """

    #: Stable identifier used in reports and as the registry key.
    name: str
    #: Repo-relative path of OUR file.
    local_path: str
    #: Upstream GitHub repository, ``owner/repo``.
    github_repo: str
    #: Immutable upstream ref (a tag, never a branch — a branch would make the
    #: recorded hash meaningless the moment upstream commits).
    ref: str
    #: Path of the upstream file inside that repo.
    upstream_path: str
    #: sha256 of the upstream blob at ``ref``.
    sha256: str
    #: Upstream licence; the notice belongs in the local file's docstring too.
    licence: str
    #: What we actually took, for a reviewer diffing a candidate update.
    symbols: tuple[str, ...]
    note: str = ""
    #: A source archive or rolling dump outside GitHub: its exact download URL.
    source_url: str = ""
    #: The source is a rolling dump republished in place (GeoNames rebuilds
    #: its exports daily and keeps no versions). ``ref`` is then the snapshot
    #: DATE (``YYYY.MM.DD``) and ``sha256`` the hash of what was fetched that
    #: day: still the exact bytes our file was generated from, but no URL can
    #: serve them again, so the checker can only say "upstream has moved since",
    #: never "the pin is broken".
    rolling: bool = False

    @property
    def raw_url(self) -> str:
        """Where the pinned blob is fetched from."""
        if self.source_url:
            return self.source_url
        return self.raw_url_at(self.ref)

    def raw_url_at(self, ref: str) -> str:
        """The same upstream file at a different ref (a candidate release)."""
        return (
            f"https://raw.githubusercontent.com/{self.github_repo}/"
            f"{ref}/{self.upstream_path}"
        )


_SOURCES: tuple[VendoredArtifact, ...] = (
    VendoredArtifact(
        name="extract-sanitizer",
        local_path="backend/tracker/connectors/extract/sanitize.py",
        github_repo="D4Vinci/Scrapling",
        ref="v0.4.11",
        # `_sanitize_for_ai`/`_HIDDEN_XPATH` are members of `Convertor` in
        # `core/shell.py`; `scrapling/core/ai.py` is the MCP server, not the
        # origin.
        upstream_path="scrapling/core/shell.py",
        sha256="9efd8c49e5b4bf7132f59fb450ea26db8ef4b27ada37df95ae1e1761fd8231d0",
        licence="BSD-3-Clause",
        symbols=("Convertor._sanitize_for_ai", "_HIDDEN_XPATH"),
        note=(
            "Behavior ported onto selectolax, not imported: Scrapling's [ai] extra is "
            "never installed and no Scrapling type is referenced. Our hidden-element "
            "rules extend upstream's, so a diff is expected to be a superset."
        ),
    ),
    VendoredArtifact(
        name="country-table",
        local_path="backend/tracker/taxonomy/countries.py",
        github_repo="mledoze/countries",
        ref="v4.1.1",
        upstream_path="dist/countries.json",
        sha256="9e9e9d25d0d1b2a448090af20bb6e7cce61f6a23755177cb5645760ef3fffdcd",
        licence="ODbL-1.0",
        symbols=("name.common", "cca2", "cca3", "region", "subregion", "latlng", "unMember"),
        note=(
            "DATA, not code, and generated rather than copied: "
            "`scripts.gen_country_table` reads this blob and emits our own table. "
            "Nothing at runtime fetches or parses it. Region assignment is OURS and "
            "deliberately diverges from UN M49 where the job market does (Mexico is "
            "Latin America, Cyprus is Europe, the six GCC states get their own group). "
            "The backend and the dashboard both read the generated output, never a "
            "hand-maintained copy, so the two cannot fall behind each other."
        ),
    ),
)


#: Place names and codes follow the standards the rest of the world's software
#: uses: ISO 3166-1 codes and Unicode CLDR English names for
#: countries and unions (what iOS, Android, Chrome and ICU display), UN M49
#: codes on our regions, and GeoNames for cities.
_CLDR_REF = "48.2.2"
_GEONAMES_SNAPSHOT = "2026.09.24"

VENDORED: tuple[VendoredArtifact, ...] = (
    *_SOURCES,
    VendoredArtifact(
        name="postgres-pg-trgm",
        local_path="backend/tracker/platform/pgcontrib/manifest.json",
        github_repo="",
        ref="16.14",
        upstream_path="postgresql-16.14.tar.gz",
        sha256="ca18d43510bbb09a271383e1aa705b05b76bc8e9400f9857178ba8ec54cf461a",
        licence="PostgreSQL",
        symbols=("contrib/pg_trgm", "COPYRIGHT"),
        source_url="https://ftp.postgresql.org/pub/source/v16.14/postgresql-16.14.tar.gz",
        note="Compiled against the pinned database wheel for each supported platform; bundle and file hashes are recorded in the manifest.",
    ),
    VendoredArtifact(
        name="cldr-territory-names",
        local_path="backend/tracker/taxonomy/countries.py",
        github_repo="unicode-org/cldr-json",
        ref=_CLDR_REF,
        upstream_path="cldr-json/cldr-localenames-full/main/en/territories.json",
        sha256="158c1d575308f7e46912edbeda435c8fe2ef5dad280798231f3a432e406b1807",
        licence="Unicode-3.0",
        symbols=("territories[alpha2]", "territories[alpha2-alt-short]", "territories[EU]"),
        note=(
            "DATA. The English display name of every country and union, as CLDR "
            "defines it. `scripts.gen_country_table` takes the standard form, and the "
            "short form only where the standard carries a qualifier in brackets or "
            "'SAR China' (Hong Kong, Macao, Myanmar). The previous name stays a match "
            "alias, so a posting that says 'Turkey' still resolves."
        ),
    ),
    VendoredArtifact(
        name="cldr-territory-containment",
        local_path="backend/tracker/taxonomy/countries.py",
        github_repo="unicode-org/cldr-json",
        ref=_CLDR_REF,
        upstream_path="cldr-json/cldr-core/supplemental/territoryContainment.json",
        sha256="9f7d2eed5278ebb7c302b7536e391708b237945c314d09a206c632c2fab45ee2",
        licence="Unicode-3.0",
        symbols=("territoryContainment[EU]._contains",),
        note="DATA. The member states of the European Union, as CLDR groups them (`UNIONS`).",
    ),
    VendoredArtifact(
        name="geonames-cities15000",
        local_path="backend/tracker/taxonomy/cities.tsv",
        github_repo="",
        ref=_GEONAMES_SNAPSHOT,
        upstream_path="cities15000.zip",
        sha256="3fccd5fce541f51291502e3392a6e759957b338fc44acff0da85bd17d26fa817",
        licence="CC-BY-4.0",
        symbols=("geonameid", "name", "asciiname", "alternatenames", "country code",
                 "admin1 code", "population", "latitude", "longitude", "feature code"),
        note=(
            "DATA, generated by `scripts.gen_city_table`: every populated place of "
            "15,000 people or more, the standard GeoNames extract. Districts (PPLX) and "
            "historical, abandoned or destroyed places are left out; alternate names "
            "keep only proper-cased Latin-script forms, which is where the English "
            "exonyms a posting uses live ('Bangalore' for Bengaluru)."
        ),
        source_url="https://download.geonames.org/export/dump/cities15000.zip",
        rolling=True,
    ),
    VendoredArtifact(
        name="geonames-admin1",
        local_path="backend/tracker/taxonomy/cities.tsv",
        github_repo="",
        ref=_GEONAMES_SNAPSHOT,
        upstream_path="admin1CodesASCII.txt",
        sha256="1da92a6323a5fec3176f3f743bf4cf4040fd56a876da55e46fbca23c863aa60a",
        licence="CC-BY-4.0",
        symbols=("code", "asciiname"),
        note="DATA. First-level division names (states, provinces) that tell Portland, Oregon from Portland, Maine.",
        source_url="https://download.geonames.org/export/dump/admin1CodesASCII.txt",
        rolling=True,
    ),
)


def by_name(name: str) -> VendoredArtifact:
    for artifact in VENDORED:
        if artifact.name == name:
            return artifact
    raise KeyError(f"no vendored artifact named {name!r}")
