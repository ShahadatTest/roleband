# Copy: the text people read

Every string a person can read in RoleBand is either a message in one catalog
(`dashboard/src/copy/`) or text someone else wrote, shown as written. Messages are
written in a subset of [Fluent](https://projectfluent.org/), compiled into
TypeScript functions, checked against the product's language rules, and
translated per message. Identifiers, API field names and URL paths are not copy.

---

## 1. The product language

### Who we write for

The reader is someone looking for their next role, at any level, and not technical
about this product: they never need to know what a scraper or a sync is. They
already have words for what it does (*role*, *posting*, *saved*, *applied*,
*level*, *not for me*). RoleBand uses their words and never makes them learn ours.

### The seven rules

1. **One thing, one word. One word, one thing.** A concept has one noun, one verb
   and one adjective, fixed across the product. A screen never renames it because
   a sentence reads better locally.
2. **Hierarchy words are not synonyms.** *Role* (the job), *posting* (the
   employer's document for it), *radar* (every role that concerns you) and
   *company* (who is hiring) are four different things and can share a sentence.
   Variety comes from naming the right level, never from swapping words at one
   level.
3. **The frame names it; the parts don't.** The page title, section heading or
   card names the object once. Controls inside it are bare verbs (*Save*,
   *Compare*, *Not for me*), because the noun is already on screen.
4. **The second mention is a pointer, not a noun:** *this role*, *it*, *both*.
   Never *this position* or *this opportunity*.
5. **Two of the same thing are told apart by their own facts, never by a label.**
   Compare's columns are headed by company and title; Duplicates shows *Earlier
   posting* and *Newer posting* with their dates. Never *Role A / Role B*.
6. **Say what happened, not how.** RoleBand reports outcomes: *Apple closed a role
   you saved*, *Scanned 12 minutes ago*. Implementation words never reach the
   screen.
7. **Nobody speaks.** Inside the app the subject of a sentence is the person,
   the thing, or nothing: *You start with well-known companies*, *Stripe is
   scanned when you choose Scan now*, *Couldn't add that company*. The app does
   not narrate itself, so neither *RoleBand* nor *we* is the subject. The name
   appears only as a name (the brand, *Open RoleBand*, the RoleBand folder),
   outside the app's own window (the menu bar app, macOS notifications, the
   installer, *RoleBand isn't answering*), where the reader may not know who is
   talking, and where a sentence must say who acts and nothing else is true
   (consent, and how a careers site sees the visitor: *It visits them openly, as
   RoleBand*). *We* is the people behind the project and appears only where they
   ask for something (*Help us improve*). Data that ships with the app is
   **built-in data**, set against a plugin's.

The metaphor is **radar**. It gives the product one place-word that is not the
object (*on your radar* is not *a role*), one verb for what RoleBand does
(*scan*), and one plain phrase for what a person's settings mean: **what your
radar looks for**.

### Words to know

`dashboard/src/copy/en/glossary.yaml` is the checked source of these rules
(`copy:check` reads it); this table is the handful you will meet first.

| Say | Never say | Notes |
|---|---|---|
| **role** | position, opening, listing, job, opportunity, req | One open job at one company |
| **posting** | job post, listing, ad, requisition | The employer's document; a role can have several. **company** is who is hiring |
| **Radar** | Opportunities | The main board and the metaphor. *Opportunity* appears only in the brand line |
| **Total compensation**; *TC*, *Est. TC* in a column, row or chip | pay, total pay, comp, package | Base salary, bonus and equity for a year. *TC* never stands in a heading or a sentence, and always carries its full words for hover and screen readers |
| **Base salary**; *Base*, *Est. base* in a column, row or chip | base pay | |
| **Equity** | stock (for a grant) | *Stock* means the share price |
| **Posted range** | pay band, published band, disclosed band, stated pay | What an employer writes in a posting, named with its basis where known (*posted base range*). An employer *posts a range*; *Pay transparency* stays, as the legal term |
| **Comp band** | estimated pay, pay by level | A company's compensation at one level. A comp band is never a range, and a posted range is never a band |
| **Compensation** | pay | The topic as a whole: the Insights tab, a panel heading |
| **Minimum base** | pay floor | The yearly base salary a person sets as their lowest |
| **level** | seniority, band, career stage, tier | *Band* is a comp band only; the Strong to Weak fit groups are *fit grades* |
| **Career track**, **Discipline**, **World** | role kind, work style, role family, job family, position type | The settings for what your radar looks for |
| **Save** / **Not for me** / **Restore** | favorite, bookmark, dismiss, hide, reject | *Dismiss* is for notifications only |
| **Follow** (a company) | track, enable, activate | *Followed companies*, *Following* |
| **Scan** | sync, refresh, fetch, scrape, check | *Scan now*, *Scanned 3h ago*. *Check* means verification |
| **Best fit** (ranking) | best match, relevance, score, matching | *Match* means a search or filter hit, nothing else. The model behind Best fit is the *ranking model* |
| **More like this** | similar positions, related roles | *Related roles* is a Duplicates verdict |
| **Duplicates**: *Same role*, *Related roles*, *Different roles* | twin openings, same opening | |
| **coverage** | | The one word for whether RoleBand can read a company's careers page |
| **New** (a role) | today, just posted | Listed in the last 2 days: copy says *in the last 2 days*. *Closed* still says today |

Words for how RoleBand works are banned from screen: scrape, connector, adapter,
drift, lineage, inventory, catalog, persona, scope, sync, epoch, facet, hydrate,
endpoint, semantic, vector, embedding, payload, position, opening, pursuit, and
their inflections. The glossary also lists phrases that must not return (*role
family*, *best match*, *tracked role* and others), each term's Never list, and
the few files and phrases where an internal word is honest (the diagnostics
panel, a skill employers name such as *Vector Databases*).

### Mechanics

- No em-dash anywhere (U+2014). Use a comma, a full stop, a colon or parentheses.
- An ellipsis is one character (`…`), never three dots.
- Errors use contractions: *Couldn't*, *Don't*, *Doesn't*.
- Sentence case for labels, buttons and headings. Proper nouns listed in the
  glossary (`proper_nouns`) are exempt.

Every message declares a **kind**, and each kind has rules:

| Kind | Rules |
|---|---|
| `label` | sentence case, at most 4 words, no full stop |
| `button` | sentence case, at most 3 words, no full stop |
| `heading` | sentence case, no full stop |
| `link`, `aria`, `name` | no full stop (`name` is a taxonomy proper name: no case rule) |
| `sentence`, `empty`, `consent` | ends with a full stop |
| `error` | ends with a full stop, and its last sentence is one of the glossary's `next_steps` ("Try again.", "Check the link and try again." ...), or the comment says `next=none` |
| `toast`, `tooltip`, `notification`, `status` | full stop optional |

---

## 2. Where text lives

| Path | What it holds |
|---|---|
| `dashboard/src/copy/en/*.ftl` | The English catalog, one file per surface (`radar.ftl`, `role.ftl`, `settings.ftl`, `errors.ftl`, `notifications.ftl` ...) |
| `dashboard/src/copy/en/terms.ftl` | The nouns as Fluent terms (`-role`, `-posting`, `-company`), so the word lives once |
| `dashboard/src/copy/en/shared.ftl`, `common.ftl` | Words several screens share: `shared.ftl` for lazy screens only, `common.ftl` for words the app shell says |
| `dashboard/src/copy/en/vocab.ftl` | Names for every slug the API sends (see section 5) |
| `dashboard/src/copy/<locale>/` | A translation: the same message ids, its own `terms.ftl` and `glossary.yaml`, and `translated-from.json` |
| `dashboard/src/copy/locales.json` | The locale manifest: codes, names, direction, status, fallback chain, region list, and `englishOnly` message ids |
| `dashboard/src/copy/pinned.en.json` | Consent wording, pinned verbatim |
| `dashboard/src/copy/gen/` | Generated TypeScript. Git-ignored, never edited or committed |
| `dashboard/scripts/gen-copy.mjs`, `copy-check.mjs`, `copy/` | The compiler, the linter, the shared catalog model and the review deck |
| `dashboard/src/copy/runtime.ts`, `activate.ts`, `CopyBoundary.tsx` | Active language and region, loading, live switching |

---

## 3. Adding or changing a message

### Write it in the catalog

New user-facing text is always a message, never a literal in a component. Pick
the surface's `.ftl` file under `dashboard/src/copy/en/` and add the message with
a comment that declares its kind:

```ftl
# kind=button
radar-show-all = Show all

# kind=status note="A count of roles: 219 roles"
shared-count-role = { $count ->
    [one] { $count } { -role(num: "one") }
   *[other] { $count } { -role(num: "other") }
}
```

The comment carries metadata as `key=value` pairs:

| Key | Meaning |
|---|---|
| `kind` | Required. One of the kinds in section 1 |
| `note` | Context for a translator or reviewer, when the intent is not obvious |
| `next=none` | An error that has no next step to offer |
| `same-as=<id>` | Two messages in one file with the same kind and text that must stay separate (otherwise `copy:check` asks you to merge them) |
| `wording=as-is` | The wording has not been reviewed against the rules. `copy:check` reports its wording problems instead of blocking, and blocks if the text is not in `dashboard/src/test/copy-as-found.json`. New messages never carry it; rewording one drops the marker |

Keep ids stable. The same words in different contexts do not have to share a
message, but one surface never repeats a shared word: use `shared.ftl` or
`common.ftl`.

A file whose resource comment starts `### eager` is imported by the shell, so
every message in it ships in the startup chunk. Put a message there only if the
shell says it. A file marked `### keyed` (`vocab.ftl`) also exports a lookup by
key, for messages chosen by data.

**The Fluent subset.** Text, `{ $variables }`, selects on a plural category or a
string, terms with literal arguments (`{ -role(num: "one") }`), term attributes as
selectors, and message attributes. Anything else fails the build with the file and
line. Metadata goes in the comment, never in attributes. A message whose selects
expand past 4,096 combinations fails too: split it.

### Call the generated function

`gen:copy` turns each message into a function named after its id, exported from
a module named after its file: `radar-show-all` in `radar.ftl` is
`radarShowAll()` from `copy/gen/radar`. A message with variables takes them as an
object (`sharedCountRole({ count })`), and a numeric variable is formatted for the
reader's region. A selector's argument is always data.

`npm install`, `dev`, `build`, `lint`, `test:unit` and `test:ux` regenerate
`src/copy/gen/` first, and the Vite plugin (`scripts/copy/vite-plugin.mjs`) does
on edit. A bare `npx tsc` in a fresh checkout needs `npm run gen:copy` first.

A sentence with a link or emphasis inside stays one message, rendered with
`<Msg of={message} args={...} elems={{ link: <a ...>...</a> }} />`, so a
translation places the element where its grammar needs it. Never split a
sentence across JSX around `{expr}`.

### Resolve text at render

A language switch remounts the UI (section 6), so text must be computed during
render, never kept:

- No message call in module scope, React state, refs, context values above
  `CopyBoundary`, or caches. Keep keys, slugs or the message function instead.
- A module-level table uses getters, so each read calls the message:
  `get label() { return shellNavRadar(); }`.
- A toast stores its message function and parameters, not the text.

### Tests name the message, not the words

A test asserts text with `msg("radar-show-all", args)` from
`dashboard/src/test/msg.ts`, with a literal key (ESLint enforces it). Fixture data
(company names, titles, cities) stays literal. A copy edit then does not break
tests, but a behaviour change still does.

---

## 4. Text RoleBand did not write

**Third-party text** (a role's title, a company's name, a city, an employer's
section heading) renders through `<Content text={...} />` from
`dashboard/src/ui/Content.tsx`. It marks the span `translate="no"`,
`data-copy="content"` and `dir="auto"`, so it is never translated, a Latin name
cannot reorder a right-to-left sentence, and the pseudo-locale scan knows it is
not missing copy. `Content` takes a string, never children, and is the only place
`translate=` may be written (ESLint). As an accessible name, the same mark is
`data-copy="content"` (or `labelIsContent` on `ui/Switch`).

**Engineering text** shown behind the diagnostics toggle (run notes, raw
counters) renders through `Diagnostic` in the same file: English, untranslated,
outside the language rules.

**Numbers, money, dates, durations, lists and sorting** go through
`dashboard/src/copy/format.ts` (`number`, `money`, `date`, `duration`, `list`,
`compare`, `parseNumber` and others). Numbers and currency follow
the reader's region; words and collation follow the language; dates and lists
use both. Never call `toLocaleString`, `new Intl.*` or `localeCompare` in a
component; `copy:check` counts those habits per folder and the count only falls.

---

## 5. What the backend sends

The backend sends codes, slugs and third-party content. It does not send English
for a person to read, except the few records and banners below.

### API errors are codes

A router raises

```python
raise api_error(404, ErrorCode.JOB_NOT_FOUND, "job not found")
```

from `backend/tracker/api/errors.py`, never `HTTPException`. The response detail
is `{"code": "job-not-found", "params": {...}, "message": "job not found"}`:
`message` is English for logs and MCP clients, and `params` carries slugs, never
display names. `backend/tests/test_api_error_codes.py` fails on any
`HTTPException` built elsewhere under `tracker/api`.

To add an error:

1. Add a kebab-case member to `ErrorCode`.
2. Regenerate the API types (`.venv/bin/python -m scripts.export_openapi` in
   `backend/`, then `npm run gen:api` in `dashboard/`).
3. Add `error-<code>` to `dashboard/src/copy/en/errors.ftl` (`kind=error`).
4. Add the code to `BY_CODE` in `dashboard/src/api/errorText.ts`. It is typed as
   a record over every code, so `tsc -b` fails until you do.

A screen says a failure with `errorText(caught, fallback)`, never `.message`. A
failure that explains nothing (a crash, a malformed request, an unexplained
server error) shows the screen's own `fallback` sentence, or the generic line.

### Product words travel as slugs

Taxonomy values (worlds, tracks, role groups, sectors, skills, sources) reach the
dashboard as slugs. `dashboard/src/copy/vocab.ts` names them from `vocab.ftl`
(`domainName`, `trackName`, `roleName`, `sectorName`, `skillName`,
`sourceName`), by the key `vocab-<kind>-<slug>`. A new slug ships its message in
the same change: `backend/tests/test_vocab_catalog.py` reads every slug table and
fails on one with no message.

### Every API string field declares a text class

A response field that carries text declares what kind it is:

```python
title: str = Field(json_schema_extra=text("content"))
```

with `text` from `backend/tracker/api/schemas/text_class.py`; it reaches
`openapi.json` as `x-text`. The classes: `code` (a code or slug the dashboard
turns into words), `content` (third-party text, shown through `Content`),
`record` (stored as agreed or as it happened, such as a consent), `diagnostic`,
and `identifier` (an id, URL or path).

`backend/tests/test_api_text_classes.py` fails on any string field with a
word-like name (`title`, `label`, `reason`, `name` ...) that declares none. The
count is zero and stays there.

### Notifications are said twice

A notification row stores English `title` and `body` (the fallback for older
rows, what feed search matches, what diagnostics shows) and, beside them,
`meta.say`: the same sentences as catalog keys with parameters. The dashboard
renders `meta.say` in the reader's language through `notificationText`
(`dashboard/src/api/notificationText.ts`), the only place it reads notification
text, and falls back to the stored English for a row without a usable `say`.

The English is not written twice by hand: `npm run gen:copy` compiles the
`notif-` and `banner-` messages into
`backend/tracker/notifications/catalog_gen.py` (committed), and producers build
descriptors with `say(key, **params)` from `backend/tracker/notifications/say.py`.
A parameter is third-party content, a number, a calendar day (`day(date)`), or a
nested `say` for a phrase the product words itself.

To add a sentence:

1. Add the `notif-` message to `dashboard/src/copy/en/notifications.ftl`.
2. Add its key and parameter names to `backend/tests/fixtures/notification_keys.json`.
   Keys are a contract with stored rows: never remove one or reuse it for another
   meaning; a rewording keeps its key.
3. Run `npm run gen:copy`, which regenerates `catalog_gen.py` and fails if the
   parameters differ from the registry.
4. Add a sample to `backend/scripts/export_notification_samples.py` and run
   `.venv/bin/python -m scripts.export_notification_samples` from `backend/`.
   It writes `dashboard/src/api/notification-samples.json`, which
   `notificationText.test.ts` renders and compares with the stored English.

`backend/tests/test_notification_say.py` fails on a stale samples file, an
unregistered key, or a registered key with no sample.

**Operating-system banners** use the `banner-` messages in English only, so
reporting a database failure never needs a database read for the language.

**Backend prose outside the catalog** (in notification and banner producers) is
held to the same banned words and mechanics by `backend/tests/test_copy_glossary.py`,
against `backend/tests/fixtures/copy_glossary.gen.json`, the glossary copy
`gen:copy` writes. Known problems are named in a baseline that only shrinks.

---

## 6. Languages

### Language and region

Language and region are two settings. Language picks the catalog; region picks
how numbers, dates and lists are written (`1,219` or `1.219`, `12 Apr` or
`Apr 12`). People choose both in Settings › Language and region. The account's
choice lives in the settings store (`GET`/`PUT /api/settings/locale`) and is
mirrored in the browser (`localStorage` key `roleband.locale`) so the first paint
is already in the right language. With nothing stored, the browser's languages
are matched against the manifest. Language tags are validated on both sides; the
backend's grammar is `backend/tracker/platform/language_tags.py`.

English is compiled inline: each message function wraps its English with the
active table, so the table wins and English is the per-message fallback. Every
other locale is one lazy table, loaded only when chosen. A switch (`activate`)
loads the table, sets `<html lang dir>`, and changes the key of `CopyBoundary`,
which sits inside the data providers and remounts everything below them. The URL,
providers and server state survive; component-local state (a half-typed search)
does not. That remount is why text must be resolved at render (section 3).

### Locale status

| Status | Build and checks | At runtime | In the picker |
|---|---|---|---|
| `complete` | A missing message fails `gen:copy`; stale, untracked and kind problems block `copy:check` | Never falls back | Listed |
| `beta` | A missing message is reported, not blocking. Stale and untracked messages are reported by `copy:check` and fail `npm run test:unit`, so a change to what an English message says lands with its translations. Structural problems block | Falls back per message along its `fallback` chain, then to English | Listed |
| `pseudo` | Generated from English | `en-XA` (accented, padded, bracketed) and `keys` (each message shows its id) | Listed only on a device with `localStorage` `roleband.copy-check` set to `1` |

English is `complete`; Spanish (`es`) and Simplified Chinese (`zh-Hans`) are
`beta`. A fallback message keeps the plural grammar of the language it is written
in, while digits follow the reader's region.

### Adding or updating a translation

A translation is the same message id in `dashboard/src/copy/<locale>/<file>.ftl`,
with no metadata comment (it inherits the English message's kind). It must keep
the English message's contract: no variable English does not pass, every
displayed count and action, and the same terms (a synonym for `-role` fails).
It may drop a selector that only exists for English grammar, and it carries
every plural category its language needs (Spanish states `many` wherever a
message states its own count: "1.000.000 de puestos").

`<locale>/translated-from.json` records, per message, a fingerprint of the
English it is a translation of: the English pattern, every term and attribute it
reaches, and its kind. Reflowing the English or editing its comment changes
nothing; changing what it says, or a term it uses, makes the translation
**stale**, and `npm run test:unit` fails until it is re-translated and recorded:

```sh
# re-translate, then record each message you re-translated:
npm run copy:check -- --translated es radar-show-all shared-count-role
# record every new translation (stale ones stay stale unless named):
npm run copy:check -- --translated es
```

A translation that breaks its contract can be held in
`dashboard/src/copy/translation-quarantine.json` with its exact pattern: the
runtime shows the English message until it is repaired, and the repair removes
the entry in the same change. A `complete` locale cannot hold quarantines.

**Editorial review** is separate from translation tracking. After a person reads a
translation against the rules, record it by id:

```sh
npm run copy:deck -- --reviewed es radar-show-all
```

That writes `<locale>/reviewed-from.json` with hashes of the English, the
translation and the rules; any of them changing makes the review stale.
Never mark messages reviewed in bulk.

### Adding a language

1. Add a row to `dashboard/src/copy/locales.json` with `status: "beta"`, its
   direction and its fallback chain. Add any regions to `regions`.
2. Add `dashboard/src/copy/<locale>/` with its `terms.ftl` and a `glossary.yaml`
   in that language (banned words, mechanics, form of address under `register`,
   its `next_steps`).
3. Declare the locale table's raw and gzip budget in
   `dashboard/copy-bundle-baseline.json`; the build refuses a language without one.
4. If the script is not Latin, Cyrillic, Greek or Vietnamese, add a font package.
5. No component branches on language.

Before a locale becomes `complete`: no blocking or stale diagnostics, a native
speaker's review, layouts checked at narrow and desktop widths, real glyphs in
the font, and the bundle gate (`en-XA` proves neither fonts nor layout for
another script).

### Consent wording is pinned

Consent wording (the warning before following a company whose site limits
automated collection and usage sharing) is `kind=consent` and
pinned verbatim in `dashboard/src/copy/pinned.en.json`. `copy:check` blocks if a
pinned message changes or a consent message is not pinned. They change only by a
deliberate, reviewed decision, never as a side effect of copy work.

The native launcher's automatic-check toggle label is also pinned and kept in
English. Its preferences record the exact label and time when a person changes
the choice; leaving the default-off toggle untouched creates no agreement record.

Consent is never machine translated. Consent ids are in `englishOnly` in
`locales.json`, and `gen:copy` fails if any locale translates one. The dialog
captures the exact text it rendered and its language, and the API stores both
with the record (for a followed company, `tracked_company.consent_text` and
`consent_locale`), so a later language switch never rewrites the agreement.

---

## 7. Commands and what fails when

Run from `dashboard/`:

| Command | Does |
|---|---|
| `npm run gen:copy` | Compile the catalog into `src/copy/gen/`, and write the committed backend files (`catalog_gen.py`, `copy_glossary.gen.json`). `-- --check` writes nothing and exits 1 if anything is stale |
| `npm run copy:check` | Lint every locale's catalog and the remaining literals; exit 1 on a blocking problem |
| `npm run copy:check -- --translated <locale> [id ...]` | Record translations (section 6) |
| `npm run copy:check -- --freeze` | Lower the literal baseline after a change reduced it; refuses to raise a count or freeze a blocking catalog |
| `npm run copy:deck` | Export the review deck to `node_modules/.cache/copy-review/`; with the dev server running, browse it at `http://127.0.0.1:5173/__copy-review/` |
| `npm run copy:deck -- --since <ref>` | Also write the messages changed after a git ref, with their dependents |
| `npm run copy:deck -- --reviewed <locale> <id ...>` | Record an editorial review |

What fails, and where:

| Check | Fails on |
|---|---|
| `gen:copy` (every npm hook, the dev server, the build) | Unparseable FTL; Fluent outside the subset; a duplicate id or term; a translation using a variable English does not pass, or breaking its contract unquarantined; a translation of an `englishOnly` message; a `complete` locale missing a message; a notification key with no message or different parameters; too many select combinations |
| `copy:check` and `src/test/copy-check.test.ts` (in `test:unit`) | English: any rule in section 1, a duplicate message, a changed pin, an unpinned consent. Translations: their glossary, term parity, contract; in a `complete` locale also stale, untracked, plural and kind problems. Literals: a new problem, or a per-folder count in `src/test/copy-check-baseline.json` rising (the counts below) |
| `src/copy/compiler.test.ts` | Generated files stale against the catalogs (including the backend's committed twins), or generated files committed |
| `npm run lint` | `msg()` with a non-literal key; `translate=` outside `ui/Content` |
| `npm run build` | `tsc -b` (an error code with no `BY_CODE` entry); a locale table over its `copy-bundle-baseline.json` budget, or a locale with none (`scripts/check-bundle-size.mjs`) |
| `npm run test:ux` | Unbracketed text in the `en-XA` pseudo locale: `tests/ux/copy-locale.spec.ts` switches live on every route, `tests/ux/copy-screens.spec.ts` boots each screen state into it. Plain text there is copy missing from the catalog or third-party text not marked with `Content`. A new screen state joins `copy-screens` |
| Backend `pytest` | `test_api_error_codes.py`, `test_api_text_classes.py`, `test_vocab_catalog.py`, `test_notification_say.py`, `test_copy_glossary.py` (section 5) |

`copy:check` prints advisory output (beta translations, `wording=as-is`
problems) as `report` lines, which never fail; failures print as `BLOCK`, `NEW`
(literal problem) or `RATCHET` (count rise).

The literal scan (`scripts/copy/extract.mjs`) reads every source file with the
TypeScript compiler and counts, per folder:

| Count | Counts | Never counts |
|---|---|---|
| `literal-copy` | A string a reader sees: JSX text, a string with a space or a capital, words beside a value (`${n} companies`), one word handed to a display prop (`label="clusters"`), a word a ternary hands to JSX (`{on ? "on" : "off"}`), a hyphenated phrase held as an object value (`tag: "employee-selected mix"`), the two words of a hand-built plural (`count(n, "question", "questions")`), a word placed in a `<Msg>` slot | A comparison (`x === "open"`), an object key, a class list under a class holder, a code attribute (`className`, `data-*`), code shown as code (`<Kbd>`, `<code>`), anything marked `/* not copy */` |
| `module-scope-copy` | Literal copy evaluated at module scope, which a language switch cannot reach | |
| `split-sentence` | Punctuation written in JSX beside a message (`<Msg …/>)`, `{message()}.`): a sentence closed in code | Punctuation beside a plain value, a separator such as `·` |
| `message-spacer` | A bare space handed to a message's placeholder (`elems={{ value: " " }}`) | A space in any other object; the space between a sentence and the control after it is layout, written as `{" "}` |
| `recased-copy` | `.toLowerCase()` or `.toUpperCase()` on a message call or a label (`bandLabel`, `fact.label`, `BAND_LABEL[x]`): case is the language's | Recasing for a comparison or a search (`.includes(...)`, `===`) |
| `plural-ternary`, `locale-call`, `locale-compare`, `error-message-shown` | `=== 1 ?`, `toLocaleString` or `new Intl.*`, `localeCompare`, a shown `err.message` (text patterns) | |
