# UI system

How the dashboard looks and behaves. Read it before you add a screen, a
control, a stylesheet or a piece of chrome text. Almost every rule is enforced
by a test named beside it, and a failing gate says what to use instead.
Wording is a separate system: [copy.md](copy.md).

## Native launcher updates

The About tab's Updates group opens with a status row: the check result as its title
(checking, up to date, a version ready, couldn't check, or not checked yet), the last
successful check time under it, and Check now beside it in every state. The
automatic-check and notices switches follow. The manual action works with automatic
checks off and leaves that choice unchanged. Show an up-to-date result only
after a successful check; an unchecked state must not imply success.

The login page and preferences use the same automatic-check toggle, initially off. The
toggle remains visible after a change; no separate question or pair of choice
buttons is needed. A routine update setting does not need a paragraph, privacy
disclosure, provider name or network details,
including in an expandable section. Those facts belong in [SECURITY.md](../SECURITY.md).
Add supporting text only when it helps the person choose an action or resolve
the current state. Keep unrelated setup controls outside the update group.

Turning on notices with automatic checks in About asks macOS for desktop
notification permission. Setup never asks for it. Automatic checks announce a newer release
once per version when permission already exists; manual checks show the result
in the app. A notification opens the available release notes. Denied permission
keeps the in-app banner working and offers notification settings.

An offer and every step of an update (download, check, failure, and the result
on the next open) share one banner above the tabs, on every tab including About;
it never moves into a tab. A newer offer replaces the last update's result in it.
Update is the only press: a verified update restarts
the app at once, even during a scan. The one exception is a release whose signed
metadata carries a "Before you update" notice: its offer says Read first and its date,
and opens the notes with the notice above them and Update below. The notice comes
only from the signed metadata; a heading of the same words in the release notes,
which are not signed, is shown as ordinary notes. The progress line carries the download's
progress; hovering it shows the megabytes, so the title keeps the room for the
version. A failure offers Retry. A download that is not the signed release, including an
image of another size than the signed one, is a failed check, never a server
that did not answer. The exception to Retry is a version signed with an Apple
Developer ID the installed app does not accept yet: its banner says the version
is signed differently and offers the release page instead, because only a
download by hand can install it.

The menu bar shows the product mark in every state, as a template image. A state
other than at rest (starting or scanning, paused, an engine hold, no engine) adds its
symbol as a badge in the mark's lower right corner; the accessibility label and
tooltip say the state in words. The panel header is the gold mark alone, without
the product name. When the menu-bar item cannot be seen (off screen, or behind the
camera housing of a notched display), the panel opens as a window instead of a
popover.

The Scan tab draws the scan picture while the engine is healthy and has a scan
to show: the companies in flight with their clocks, or the last scan's facts, the
tank of roles found, and one schedule line. A scan goes on after its last company
is read, and the picture names that step with the Radar's words: Adding the last
roles, then Finishing up, with the companies read, the roles recorded and the
scan's clock in place of a percent that has reached 100. A hold, an engine update or an engine
without scan data keeps the status card, which says why. Companies needing
attention are the Radar's to show: the panel neither lists nor marks them. Stopping
lasts only while the stop request is in flight, because the engine ends the run
inside that request. With Reduce Motion the dots stay still; clocks and counts
still change.

Scans run on their own, so the roles they find are what the panel is for. Open
Radar is the Scan tab's one gold action; Scan now or Stop scan and Pause sit
below it, quiet, side by side. A stopped engine is the exception: restarting it
takes the gold place, and Open Radar waits for an engine that answers. The
footer holds Quit alone. A last scan with new roles makes its new-roles count a
link that opens the Radar on New (`/?lens=new`); with none, the count is plain.

First open uses Welcome, Get ready, At login and Ready. Placement guidance is a
separate window before setup when the app is outside Applications. Get ready
shows actual database, model and service progress, including downloaded bytes,
verification, offline waiting and actionable failures. Continue becomes available
when the database and service are usable, even while the model waits offline.
Nothing runs before Continue on Welcome: the engine, and with it the first scan,
starts when the person continues in a copy inside Applications, and at every open
after that. Closing an earlier page saves the step and
leaves preparation running. Until setup completes, the menu-bar item opens the
panel with a Finish setup card that resumes that step; while the engine still
waits for Welcome, the card is all the Scan tab shows. Quit stops owned
preparation.

At login proposes opening at login, initially on. Registration happens only on
an explicit switch change or Continue on that page. Closing setup and background
completion do not change login items. A copy that has never registered reads as
off, not unavailable: macOS reports it as not found until the first registration.
Show the actual approval state and an inline System Settings action when approval
is needed. Automatic
update checks start off and share the same explicit choice as Settings.

Ready is a concise completion page with Open Radar as the primary action and
Not now as the quiet secondary action. Omit repeated checklists, optional settings,
restart and navigation controls. Open Radar verifies the current connection again,
saves valid setup and hands off to the browser. A browser failure keeps setup
complete and offers another attempt in the same window. Not now or closing a
valid Ready page completes setup without opening the browser. Completion does
not reopen the status panel over the browser.

## Launcher installation guide

The disk image puts Start here before the app-to-Applications drag. The guide
opens in a browser before native setup can run, with Copy, Open, Allow first
open and Set up stages. Use a visible language menu, real macOS examples labeled
as examples, keyboard navigation and readable light/dark layouts. A no-warning
route skips approval instructions. Missing approval controls and different
warnings have contextual recovery, with manual Settings navigation alongside the
convenience link. Keep approval in Apple's UI.

Follow the native setup's action placement: Back stays on the left; forward and
primary actions align right, with secondary choices immediately before them.
Keyboard order follows visual order. Narrow screens stack actions at full width.

Progress is confirmed by the person following the guide. Never imply that an
HTML page detected a copy, granted approval or launched the app. Keep all assets
local and usable offline; show every stage when JavaScript is unavailable. The
guide never changes a security setting or removes quarantine.

## Where the code lives

The dashboard's layers and their import rules are in
[architecture.md](architecture.md#dashboard).

Five stylesheets load on every route, imported by `src/main.tsx`:
`design/tokens.css`, `design/overlays.css`, `design/surfaces.css`,
`design/dataviz.css` and `src/shell.css`. A keyframe or utility class that a
lazily loaded screen relies on must live in one of them or in that screen's own
chunk. Every other stylesheet is co-located with the component that imports it.

## Tokens and themes

### One vocabulary

`design/tokens.css` declares the whole vocabulary once, at `:root`, so every
route and portalled overlay inherits it. Stylesheets consume `--app-*` and
nothing else: no second namespace, no aliases, no token declared elsewhere.
`src/test/ratchet.test.ts` fails a set of extinct names (`--bg`, `--text`,
`--accent` and family), because a `var()` on an undefined name silently paints
as `unset`.

| Family | Tokens (`--app-` prefix omitted) |
|---|---|
| Grounds | `canvas`, `surface`, `surface-raised` / `-subtle` / `-sunken` / `-glass` / `-hover`, `selected` |
| Lines and text | `border`, `border-strong`; `text`, `text-muted`, `text-faint` (all AA) |
| Decor | `decor`: glyph strokes, dots, hairline chrome. Never text |
| Action | `action` (the gold) and `action-ink` / `-soft` / `-line` / `-text` / `-ring` / `-glow` |
| States | `chosen-*`, `on-*` (see [Two states](#two-states)) |
| Status and data | `positive*`, `warning*`, `danger*`, `information`; `data-1` .. `data-4` for charts |
| Other | `bar`, `mark`, `ambient-*`, `shadow`, `shadow-pop`, plus the type, geometry and motion scales below |

Motion uses `--app-ease` for hover and pop, `--app-ease-travel` for things that
glide, and `--app-duration-fast` / `-medium` / `-slow` (120 / 180 / 260ms).

### Light and dark

`:root` is the light theme. Dark values live in `:root[data-theme="dark"]` and
again in `@media (prefers-color-scheme: dark)` for a root with no theme set.
The app sets `data-theme` on `<html>` from the viewer's choice, saved in
`localStorage` (a choice for this device, as the language and the Insights
view are; settings live on the backend). First-run setup is the exception: it
is always dark, without saving
that over the viewer's choice (`shownTheme` in `shell/theme.ts`, and
`public/theme-boot.js` before first paint). Every colour token needs a value
in both blocks, and each block also sets `color-scheme`, the one signal the
browser has for drawing native UI (a select's popup, scrollbars) in the page's
theme rather than the OS's.

Never paint a literal colour in a declaration: it ignores the theme.
`design/literal-colours.test.ts` lets the per-sheet count of literals only fall
(palette definitions are not counted).

The nav rail is dark in both themes, painted from its own `--rail-*` set in
`shell.css`.

### Materials

A material is a body attribute a few screens share:
`design/materials/<name>-material.css`, selected by
`body[data-material="<name>"]`, set through `hooks/useBodyAttribute`. The one
material, register, is worn by Settings > Companies, Settings > Intelligence
and Company profiles. A material carries layout only and restates no
`--app-*` token (`design/tokens.test.ts`); a screen that should look different
needs a primitive or token change. `tests/ux/material-parity.spec.ts` measures
the register screens against another screen in both themes.

### The contrast gate

`design/tokens.test.ts` checks each palette (light, dark, each material in
both) on three grounds: canvas, surface over canvas, raised surface.

- Every text token (`text`, `text-muted`, `text-faint`, `action-text`,
  `positive`, `warning`, `danger`, `information`) holds 4.5:1 on every ground.
- `action-ink` holds 4.5:1 on `action`, and `danger-ink` on `danger`.
- `decor` holds 3:1 on every ground (the WCAG minimum for graphical objects)
  and stays quieter than `text-faint`.
- `decor` paints `color` or `fill` only on selectors listed in
  `DECOR_GLYPH_SELECTORS` (glyphs); an unused row also fails.
- The rail's own palette holds 4.5:1 on its grounds.

If a colour fails, fix the colour, never the threshold. Quiet text uses
`text-faint`; `decor` is for dots, chevrons and strokes.
`tests/ux/a11y.spec.ts` runs axe on every route in both themes.

### Type

The ramp is whole pixels, declared once in `tokens.css`. Never write a literal
`font-size`; pick a role.

| Role | px | Carries |
|---|---|---|
| `display` | 30 | An instrument's hero numeral. Never a heading |
| `page` | 22 | Every screen's `h1` |
| `screen` | 18 | Card or zone heading (`h2`) |
| `stat` | 22 | Standalone numerals |
| `title` | 16 | `h3`, sector heading, tile title |
| `name` | 15 | A row's primary string (a company name) |
| `body` | 14 | Descriptions, controls, tab bar, prose |
| `meta` | 13 | Secondary facts. The floor for anything that states a fact |
| `label` | 12 | Uppercase mono labels, column heads. The floor for chrome |
| `viz` | 11 | Instrument text with a text alternative only |
| `micro` | 11 | A secondary fact on a dense instrument row, in muted or fainter ink, never prose |
| `whisper` | 9 | A recognition label: uppercase, at the recipe `--app-type-whisper-weight` / `--app-type-whisper-track`. Never sentence case |

Rules that go with it:

- A row has one primary string at `name`; facts about it are `meta`, not
  `body`.
- `page` stays at least 1.2 times `screen` and no larger than 24px. A heading
  states its own `line-height` (about 1.15 to 1.3) instead of inheriting the
  body's 1.5 (`design/geometry.test.ts`).
- Only a selector named as a figure may give an `h1` the `display` size.
- When text will not fit, drop it or make room. Never shrink below a floor.
- A size change ships with the matching control heights, padding and weights.
- A register of hundreds of rows uses the upper steps (`name` over `meta`); a
  surface with a handful of choices uses the lower ones. Neither invents a size
  between steps.

Sans weight is four roles: `--app-weight-body` 400 (prose), `-ui` 500
(controls), `-name` 600 (names, titles, `h1`-`h3`), `-strong` 700 (emphasis and
uppercase micro-labels). `design/sans-weights.test.ts` freezes the remaining
literal weights and lets the set only shrink. `design/font-weights.test.ts`
checks that every mono weight a rule asks for is a face the app loads.

### Geometry scales

| Scale | Steps | Carries |
|---|---|---|
| `space-1` .. `space-6` | 5, 10, 14, 20, 28, 40 | Every distance: gaps, padding, gutters |
| `control-sm` / `-md` / `-lg` with `-pad` | 28 / 10, 36 / 14, 44 / 18 | A control's height and its horizontal inset, as a pair |
| `radius-sm` / `-md` / `-lg` / `-xl` | 7, 9, 14, 18 | Chips, controls, cards, overlays |
| `icon-sm` / `-md` / `-lg` | 14, 16, 18 | An icon beside `meta`, `body`, `name` text |

- A control's height and inset come from the same step.
- `design/geometry.test.ts` rejects bare px from 4 to 48 in padding, margin,
  gap and radius, and off-scale control heights, in the sheets it enrols (the
  register screens, `ui/Card.css`, `ui/CompanyIcon.css`). Follow it everywhere.
- A card's inset says how much room it has: `space-5` for a card spanning its
  column, `space-4` for a card in a multi-column grid or any card below 640px,
  `space-3` for a block nested in a card. No fourth value
  (`design/card-inset.test.ts`).
- One surface per zone. Zones inside a card separate by hairline, never by
  nesting another bordered card.

### The page wash

`body` paints two ambient gradients from `--app-ambient-image`. Anything that
imitates the page ground (a sticky column header, a frozen toolbar band) paints
`var(--app-canvas)` plus `var(--app-ambient-image)` with
`background-attachment: fixed`, so it resolves to the same pixels as the page
and does not read as a plate. A raised or inset surface stays flat. A panel that
frames content is opaque, so the wash does not shine through it.
`tests/ux/settings-shell.spec.ts` checks the computed result. The welcome's
planet stands on the plain ground: `html[data-ground="plain"]` drops the wash,
set by `public/theme-boot.js` before the first paint on "/" and the welcome and
cleared by `App.tsx` once anything else shows.

## The primitive tier

New UI builds on `src/ui/`. Do not hand-roll an overlay, a badge or pill, a
loading or skeleton state, a button or a clickable `div`. If no primitive fits,
extend the primitive (a new variant with its full state set) rather than
writing a screen-local version.

| Job | Use |
|---|---|
| Any button | `Button` (see [Controls](#controls)) |
| Floating surface | `Overlay` and its shells `Popover`, `Dialog`, `Sheet` |
| Escape handling outside an overlay | `useEscapeLayer` (`ui/escapeLayer.ts`) |
| Status label or count | `Badge` (tone, variant, size); a job row's read-only label is `shape="tag"` |
| Fetch states | `AsyncBoundary`, `ResourceLoadState` (shows only after 200 ms, so a short load never flashes), `Spinner`, `ProgressBar` |
| Empty result | `EmptyState` (`narrowedBy` explains which filters emptied it) |
| On/off setting | `Switch` |
| Pick one of a few modes | `Segmented` |
| Pick from a list | `Select` (native) or `FilterSelect` (searchable facet picker) |
| Toggle a filter | `FilterChip` |
| Filter register | `FacetGroup`, `FilterGroup`, `FilterRegister`, `FilterDrawer` from `ui/FilterRail` |
| Search box | `SearchField` |
| Views of one screen | `TabBar` |
| Feedback and undo | `Toast` (`ToastProvider`, `useToast`) |
| Card anatomy | `Card`, `CardRow`, `CardMessage` |
| Glyph, company mark, key hint, help mark | `Icon`, `CompanyIcon`, `Kbd`, `InfoTip` |
| Short form of a name in a column, row or chip (*Est. TC*) | `Abbr` (full words on hover and for screen readers) |
| Third-party text; chart | `Content`; `EChart` |

A primitive that needs CSS ships it beside itself as `ui/<Name>.css` with a
`ui-` class prefix. A control used by two screens belongs in `src/ui/`.

Every screen follows the same contract: co-located CSS consuming `--app-*`
only, type from the ramp, the route root marked `data-design-system="app"`
(shared surface classes in `design/surfaces.css`, `overlays.css` and
`dataviz.css` are scoped to it), and every `Dialog`, `Popover` or `Sheet`
passing `className="app-overlay"`. `design/settings-doorway.test.ts` finds
every overlay under `features/` and `shell/` and fails one without the class.

### The ratchet

`src/test/ratchet.test.ts` counts hand-rolled UI outside `src/ui/` against
`src/test/ratchet-baseline.json`. A count may go down, never up; a change that
lowers one lowers the baseline too.

| Marker | Counts | Use instead |
|---|---|---|
| `overlay-escape` | `key === "Escape"` handlers | `Overlay` or `useEscapeLayer` |
| `overlay-scrim` | a class containing `scrim` or `backdrop` | `Overlay`'s scrim |
| `loading-spinner`, `loading-skeleton` | `className="loading"`, `skel*` | `AsyncBoundary` |
| `badge-pill` | `chip`, `pill`, `tier`, `badge-*` classes | `Badge` |
| `hand-rolled-button` | a raw `<button` | `Button` |
| `click-target` | `onClick` on a `div`, `span`, `li` and similar | A real button or link |

The raw buttons that remain are known shapes (whole-row targets, palette
options, the dial's drag handle, the sync button). A new exception is paid for
by converting an existing one, never by raising the number.

## Controls

Every clickable thing is `ui/Button` or one of the named selection controls
above. There is no other button class.

### Button

| Variant | Use for |
|---|---|
| `primary` | The one action this surface exists for. At most one visible |
| `ghost` | The default: openers, Cancel, diagnostics, row actions |
| `icon` | Icon-only square. Requires `aria-label` |
| `link` | A verb inside running text. Takes no size |
| `danger` | Destructive and not undoable |

Sizes come from the control scale: `sm` 28, `md` 36 (default), `lg` 44.
Modifier classes on top of a variant:

- `ui-btn-strong` on a ghost: full ink on a strong hairline, for the dense
  register screens.
- `ui-btn-quiet` on a link: an aside that must not outrank the content beside
  it ("Show 23 more").
- `ui-btn-tile` (with `ui-btn-tile-copy`, `-title`, `-description`): a
  full-width two-line opener. No nested controls inside it.
- `ui-beacon` belongs to `patterns/jobs/MarginBeacon` only: the compare and
  dismiss pills in a job list's margin.

`Button` defaults to `type="button"`; a form's submit passes `type="submit"`.

**Primary means scarce, not "commits state".** One primary per surface, and it
is what the surface is for (View & apply on Job detail). Many screens have
none: a list you scan has no single action. A verb repeated on every row is
never primary; it is a `link` or `ghost`. A dialog's primary is its purpose.
`tests/ux/job-detail.spec.ts` and `tests/ux/profile.spec.ts` count the visible
primaries in a browser.

**Never a button that navigates, never an anchor that acts.** An anchor that
should look like a button wears the classes (`ui-btn ui-btn-primary ui-btn-md`).
A compact link to a role is `patterns/jobs/JobLinkRow`. A link that leaves
RoleBand is `ui/ExternalLink` (new tab, an `external` glyph after its words),
never a bare `<a target="_blank">`.

### Control rules

- A variant owns its whole state set: `:hover`, `:active`, `:disabled`,
  `:focus-visible`.
- No stylesheet outside `src/ui/` paints colour on a `ui-` primitive's states
  (`:hover`, `:active`, `:focus*`, `:disabled`, `[aria-*]`). A different look
  is a new variant (`design/primitive-states.test.ts`).
- Never redefine a shared class from a feature sheet.
- Hover must not imitate a semantic state. Move the fill on hover; leave the
  border to meaning.
- Clickable means focusable: no `<div onClick>`.
- **A clickable card is a container with one control inside**: a `<div>` card,
  one button on its title, and that button's `::after` stretched over the card.
  Other controls in it stay siblings, so nothing nests. Test the whole-card
  click with `page.mouse`; Playwright refuses a locator click on a covered
  element.
- **A whole-row target** (a notification row, a review option) is a bare
  `<button>` carrying layout and no button chrome. It still owns hover,
  focus and disabled, and its ring is drawn inside.
- `src/test/control-inventory.test.ts` lists every class outside `src/ui/`
  that declares `cursor: pointer` and paints a box. A new name fails, and so
  does a listed name that styles nothing.

### Two states

Every on, selected or current look is one of two, each from one token set.

| State | Means | Paint |
|---|---|---|
| Chosen | One option among others, or the current item of a set (tab, chip, segment, option card, nav item, a row picked for Compare) | Gold: `--app-chosen-wash` behind, `-line` around, name in `-text`, mark in `-mark` |
| On | A thing's own on/off state, set by a switch | Ink: `--app-on-fill`, `--app-on-wash`. Never gold |

- Paint keys on the element's own state: `aria-pressed`, `aria-selected`,
  `aria-checked`, `aria-current`, `:checked`, or a parent's
  `:has(> input:checked)`. Decoration inside an `aria-hidden` group uses
  `data-chosen`. Never a class such as `.on`, `.is-on`, `.active`,
  `.selected` or `.is-current`, in CSS or in a conditional `className`.
- Use `aria-pressed` for a mode and `aria-expanded` for a disclosure. Open is
  not chosen.
- The name changes colour; the description under it stays muted. Never change
  weight to show state (it reflows the row).
- A list option marks its choice with a tick and the gold name, no wash. A
  flush row with no edge shows chosen as an inset bar in `--app-chosen-mark`.
- Three named exceptions change only the hue: a pressed `danger` button, the
  nav rail (its own dark gold), and the "not interested" list (danger hue).

`design/state-grammar.test.ts` and `tests/ux/state-grammar.spec.ts` enforce
this.

### Toasts and the way back

A destructive action takes effect at once and offers Undo in a toast:
`toast({ text, action, tone, duration, key })`. Status toasts time out, errors
stay, and leaving the screen dismisses its toasts. Keep `danger` and any
confirmation step for actions that cannot be undone.

## Text selection

A control's label is not prose and does not belong in a reader's clipboard.
Selection follows what an element is, never its class name. One rule block in
`src/shell.css` makes these unselectable:

- Controls by role: `button`, `summary`, `select`, `label`, `[role="button"]`,
  `[role="tab"]`, `[role="option"]`, `[role="switch"]`.
- Declared decoration: `[aria-hidden="true"]`, `.sr-only`.
- Shared chrome classes: `.ui-btn`, `.stat-chip`, `.skip-link`, `.rail-item`,
  `.ui-badge`, `.chip`, `.eyebrow`.

`a[href]` is deliberately absent: a link in running text stays copyable.

What a screen adds:

- `data-selection="chrome"` on a region that is entirely chrome (a toolbar, a
  legend), so a drag starting in its padding selects nothing. Never on a
  region that also holds content: in Chromium a drag anchored there selects
  nothing at all. A mixed region marks its chrome children.
- `data-selection="content"` on the element itself, for content inside a
  control (a job title inside a row link).
- `dragSurface` from `src/ui` on a dragged element (the schedule dial). It
  cancels `mousedown` so a drag starting there selects nothing; a focusable
  drag surface focuses itself in its own handler.

Must stay selectable: job titles, descriptions, requirement prose, company
names, locations, requisition ids, apply URLs, every pay figure, dates, error
text, diagnostics, field values and explanatory note sentences. A heading over
a control (a filter group's name) is a label, not content.

Declare `user-select` only in `shell.css`, always with its `-webkit-` pair (the
build has no autoprefixer). `design/selection.test.ts` checks the source;
`tests/ux/selection.spec.ts` drags a real pointer across chrome and also proves
titles, descriptions, pay figures and field values stay copyable.

## Layout and breakpoints

### The app shell

The nav rail is `--app-nav-width` (72px), or `--app-nav-width-expanded`
(204px) when expanded. Below 860px it becomes a bottom dock that scrolls
horizontally. Each rail tab renders `patterns/PageHeader` with its rail label
as the `h1` (`patterns/page-header.test.ts`, `tests/ux/page-header.spec.ts`).
Under the header, a list screen's count and its Reset all live in
`patterns/ResultsSummary`; Reset all clears every filter and lens, never the
search query.

A screen whose filters stand beside its list uses `patterns/RailShell` above
`RAIL_QUERY` and `patterns/FilterSurface` (a popover, or a sheet below
`SHEET_QUERY`) under it.

### Sticky bands

A dense list freezes what it is used with (search, filters, column heads) and
lets the page title and tab bar scroll away. Each sticky tier's `top` is the
sum of the bands above it, as a custom property or a measured value, never a
literal. A frozen band pays for its air in padding, not margin, and paints the
page ground ([The page wash](#the-page-wash)). No `overflow` on an ancestor of
a sticky element.

### Breakpoints

Prefer intrinsic layout (`column-width`, grid `minmax()`), then a container
query. Most layout questions are about a component's own width, and the
viewport is a poor proxy because the chrome around it changes width at the
shell's breakpoints. The job row uses `@container`, and `board-shell.test.ts`
keeps it that way.

Viewport widths are a closed set. `design/breakpoints.test.ts` scans every
`@media (max-width | min-width)` in CSS and every `(max-width: Npx)` string in
TypeScript and fails on a value that is not in its `FROZEN` map. A value whose
last consumer goes must leave the map in the same change. `@container` widths
are not gated.

| px | Owner |
|---|---|
| 1500 (min) | Job detail's wide reading measure |
| 1360 (min) / 1359 | The filter rail gets its own column (`RAIL_QUERY` in `ui/FilterRail.tsx`, and `rail-shell.css`) |
| 1240 | Profile walk's rail folds under the step; third top-bar stat hides |
| 1180 | Companies register bar column |
| 1120 | Page gutter step |
| 1100 | Intelligence field stack; the margin beacon docks to the viewport edge |
| 1080 | Schedule clock editor stack |
| 980 | Companies sector index; review decision bar |
| 900 | Company profiles shell |
| 860 | Rail becomes a bottom dock, toolbars unfreeze, filters become a sheet (`SHEET_QUERY` in `patterns/FilterSurface.tsx`) |
| 760 | Companies rows, review ledger, statistics head |
| 700 | Scope category toggle |
| 640 | Card inset contract (`ui/Card.css`), panels, Intelligence sheet |
| 540 | Phone chrome: top-bar labels hide; settings head, statistics, board sort |
| 520 | Companies row becomes a card stack |

A viewport threshold that TypeScript needs is a named exported constant read
through `hooks/useMediaQuery`, not an inline literal. CSS cannot use `var()` in
a media query, so a constant plus a test is the only way to name one.

Changing a breakpoint value moves where a layout reflows, and no test reads
layout. Check the screen in a browser at widths on both sides of any value you
touch, and at a phone width whenever you change a card.

## Focus and keyboard

### One focus ring

Wherever the keyboard lands, one ring says so:
`outline: var(--app-ring-width) solid var(--app-action)`, 2px, from the global
rule in `shell.css`. It clears 3:1 on every ground. A stylesheet may change only
where the ring is drawn:

| Variant | When |
|---|---|
| Outside, `--app-ring-offset` | The default: buttons, chips, fields, switches |
| Inside, `calc(-1 * var(--app-ring-offset))` | The control is flush with its container, or the container clips: tabs, list rows, index entries |
| On a carrier (`:focus-within`, `:has(:focus-visible)`) | The focused element is hidden or is only part of the visible control: `.ui-search`, the filter rail's search row |
| As an SVG stroke at `--app-ring-width` | A mark inside a chart or map |
| In `--rail-accent` | Anything inside the dark nav rail |

- Never a tint, halo, glow, bar or another hue for focus.
- Text fields ring on click as well as on Tab. A native select rings for the
  keyboard only (`ui/Select` marks pointer focus with `data-pointer`).
- `outline: none` only beside a named carrier, or on an element that only
  script focuses.
- In a combobox, focus stays in the field and the active option
  (`aria-activedescendant` or `aria-selected`) wears the ring inside, over the
  hover fill. The command palette's field draws no ring of its own: focus
  never leaves it, the palette always has an active option, and two rings
  would leave the eye to choose.

`design/focus-ring.test.ts` checks every focus rule and suppression;
`tests/ux/focus-ring.spec.ts` tabs through screens in both themes.

### Overlays and Escape

`ui/Overlay` owns portal, `role` and `aria-modal`, focus capture, Tab trap,
focus restore, scrim click and scroll lock. Escape goes to the topmost layer
only: each surface registers with `ui/escapeLayer`, and one window listener
hands the press to the top one. Never add your own Escape listener.

Layers stack in three ranks (`ui/Overlay.css`): cover 60, toast host 110,
dialogs, sheets, popovers and the palette 120. A layer above a cover that
carries a control sets `data-above-cover` to join the cover's Tab ring.

### Keys

- `TabBar` is an ARIA tablist with a roving tabindex: Left, Right, Home and End
  move the selection.
- `⌘K` / `Ctrl-K` opens the command palette anywhere; `/` focuses search; `?`
  opens the shortcuts sheet (`shell/KeyboardShortcuts.tsx`).
- On a job list, `j` / `k` (or the arrow keys) move between rows, Enter opens
  the role, `s` saves and `c` adds to Compare.
- Duplicate review answers `d`, `t` and `n` with a verdict.
- A single-letter key ignores presses with a modifier and presses inside a
  text field. Review's verdict keys also step aside while a modal is open,
  because a stray press there would record a decision.
- A new key is added to the shortcuts sheet in the same change.
- A skip link to `#main-content` is the first stop on every page.

### Motion

Animate `transform`, `opacity` and `box-shadow`, never layout. `shell.css`
collapses durations under `prefers-reduced-motion: reduce`; a sheet with its
own animation adds its own reduced-motion block. The welcome screen's motion
primitives (`features/scope/motion/primitives.tsx`) honour it via
`MotionStage`.

## Icons

There are two icon sets, split by job, and the product's own mark.

- **UI glyphs:** `ui/Icon` with an `IconName`, backed by `lucide-react`. Names
  are RoleBand's own; to add a glyph, add a row to the `ICONS` map in
  `ui/Icon.tsx`.
- **Company marks:** `ui/CompanyIcon`, backed by Simple Icons: catalog marks
  bundled, the rest in lazy shards. `ui/brandIcons*.gen.ts` and
  `ui/brandIconShards/` are generated by `npm run gen:brand-icons`; never edit
  them. Use `hasBrandIcon` to decide whether a mark exists.
- **The product mark:** `ui/BrandMark`, one colour (`currentColor`), on the
  rail tile and the mobile header. The master drawing, the app icon, the
  menu-bar glyph and the favicons (`public/favicon-*.png`) are drawn from one
  geometry. The favicons are white, so the mark shows on a dark tab strip;
  `images/logo.svg` is the mark on its tile.

Never inline an `<svg>` glyph, a Unicode character or a CSS `content:` glyph
as an icon. Chart and map SVG is data, not an icon. A company's brand colour
is an emphasis state, not its resting look, and any official hex goes through
`brandInk()` before it is painted (some are near-black and disappear on a dark
card). `src/companies.json` is the only per-company literal in the dashboard.

## Screen shells

### Tab screens

A rail tab is a place with standing content: a list, a queue with a backlog,
or settings. It renders `PageHeader`, then its toolbar, then its content.
Settings (`routes/SettingsRoute.tsx`) and Profile mount
`ui/SettingsDesignSystemRoot` and build their sections from `ui/Card`; the
shared component styles are `design/settings.css`. Every section
heading is a real `h2` or `h3`.

### First-run setup

A fresh install runs the welcome intro and then Profile's own walk in setup
mode (`routing/setupMode.ts`). There is no other copy of the steps, so a change
to Profile's steps changes setup with it.
While it runs, setup has the window to itself: the rail and the top bar are not
drawn (`App.tsx`, while setup mode is not off), and the palette and global keys
do not open. The walk draws its own header, an eyebrow with the step ("Setup,
step 2 of 7") over "Set up your radar", with a gold line under the steps for how
far along it is, and stands as one centred column, at most 1320px, a little
below the top (`walk.css`, `.walk--setup`). Setup's way out is a quiet link in
that header, and its one primary is the last step's Start. Setup asks for the
level alone: roles that state no level keep their default, and Profile offers
that choice. Before anything has been read (`holdsNoRoles`), the walk shows no
counts: the funnel names the answers, and the level rungs and the Summary show
none. A launch at "/" draws nothing until the install says whether it is set up
(`App.tsx`), so a fresh install meets the welcome without the board flashing
first; while the welcome is read, the shell fetches Profile's screen
(`preloadProfile`) and the welcome primes the walk's catalog
(`primeScopeCatalog`), so setup opens on its first question.

Setup mode is on only for an install with no profile and no saved scope; the URL
flag never turns it on alone. The walk starts blank and runs straight through:
the three answers that decide, the two that sharpen, then the Summary, with no
Save on its rail. The two that sharpen are marked Optional, in setup and in
Profile alike; while one still keeps everything, a quieter Skip sits beside
Continue, which keeps its place on every step. The Summary holds the pay floor:
setting it writes nothing, and Start writes it after the scope, so a failed scope
save leaves no floor. The last step names the companies the install follows (a
fresh install follows the whole curated list, `company_store.ensure_builtins`)
and asks which to scan, through the same bulk follows and confirmations as
Settings > Followed companies; its Start is the one commit. That step belongs to
the Companies feature and `routes/ProfileRoute.tsx` composes it, so neither
feature imports the other. Each step is a history entry: Back steps through
setup and from its first step to the welcome, never out of the app, and a reload
opens the step it left. The answers, the held floor and the companies choice stay
in the tab (`features/scope/setupStash.ts`, sessionStorage) until a save takes
them; nothing reaches the server before Start. Set up later leaves without saving
and keeps them; until a save configures the install, the empty board and Profile
offer Finish setting up, and the next launch offers setup again.

The first pass ends when every followed company has been read once (`ever_read`
of `required` in `/api/status`). Until then an empty board shows the radar mark
and the scan's state (about to start; running, with the companies read and when
to look again; on hold and why; or stopped, with Scan now), and the list is read
again as companies are read. A list during the pass says how far it has got.
After it, an empty board tells its own filters apart from what the person is
looking for, and the last page of a list says where to change either; while the
person follows only some companies, following more comes before changing the
Profile.

The welcome intro is a scene: a planet on a canvas (`welcome/Globe.tsx`) turns
under a gold scan line while the cities RoleBand reads light as it passes, and
the reader can drag it. The line first shows already whole, top to bottom
along the planet's western edge (`scanEntry`), never growing in from the top.
Its geometry and drag are pure modules (`globeView.ts`, `globeDrag.ts`); its
cities are generated (`introCities.gen.ts`). It is decoration (`aria-hidden`), holds one frame under
reduced motion, and takes its colours from the tokens. The usage-sharing
question is asked in the same scene: the planet dims and keeps turning, and the
question takes the place of the intro's words (`ConsentPane`, `look="scene"`).
Only its look differs from the one-time dialog: the words, and so the record,
are the same, and its two answers stay one look and one size.

### Dense register

Settings > Companies is the pattern for a large set that must be read and
scanned. One column, fixed tracks, rows on a minimum height. Three sticky tiers
(toolbar, column head, section heads) with derived offsets. Sections are
sticky headings, never boxes, and nothing is hidden behind a disclosure. A
side index of sections navigates without filtering. A narrow width drops
columns in order of redundancy, but never the status dot; a label it hides is
clipped visually rather than set to `display: none`, so screen readers keep it.

### Cover

`patterns/Cover` is the shell for studying one thing, or a few, over the list
it opens from. Job detail and Compare use it.

- Opened from a list with `navigate(to, { state: { backgroundLocation } })`,
  the list stays mounted underneath with its scroll and filters, and the cover
  is a modal `ui/Overlay` with no scrim. Back and Escape pop history.
  `coverBackground()` in `routing/paths.ts` computes the background. Covers do
  not stack, except a role opened from Compare.
- Reached by URL, the same body is the page's one `main` landmark.
- The bar: Back, a frame line (`role="status"`), a spacer, secondary verbs, at
  most one primary. It wraps instead of using a breakpoint.

**Job detail** (`features/job-detail/`) keeps a reading measure
(`.jd-container`); its primary is View & apply, an anchor wearing the primary
classes. **Compare** (`features/compare/`) runs full width with up to three
roles (`COMPARE_CAP` in `context/JobWorkspace.tsx`): sticky column heads with
the role and its verbs (save, not for me, remove), a field ledger from
`attributes.tsx`, and one description column per role. It is not a rail entry;
it opens from the margin beacon, Job detail, the top-bar chip and the palette.

### Duplicate review

Duplicates (`features/review/`) is a rail tab because it is a queue with a
backlog. A sticky toolbar switches between Queue, Matched automatically and
Decided, which lists every verdict newest first. Each case shows
a field ledger where identical fields collapse (`ComparisonLedger.tsx`), two
description columns with unique passages marked (`DescriptionComparison.tsx`),
and a fixed decision console (`DecisionConsole.tsx`) answering `d`, `t` and
`n`. A verdict advances to the next pair and offers Undo in a toast.

### Insights views

Insights (`features/statistics/`) opens in its basic view: the Overview,
Hiring, Compensation and Skills tabs, each with the panels a weekly reader
needs (the window's motion and top skills, who hires and where, the median pay
and its middle half by level, company and discipline). The Advanced view switch
in the page header adds the other six tabs and every other panel; a tab passes
`advanced` down to the panels the basic view leaves out.

Turning the advanced view on asks in a dialog until the person says yes; the
answer is kept on this device (`insightsView.ts`), so turning it off and on
again asks nothing. A link to an advanced tab opens it in the basic view with a
line offering the rest, and the tab leaves the bar once the person moves on. A
panel that holds a tab's only figures in some case (the base estimates when no
role has a total) shows in both views. A figure that tells no reader anything
is removed, not moved to the advanced view.

## Which tests enforce what

Unit gates (`npm run test:unit`) are under `dashboard/src/`; UX specs
(`npm run test:ux`) are under `dashboard/tests/ux/`.

| Rule | Gate |
|---|---|
| Contrast, type ramp, decor on glyphs only, display rank, whisper recipe, materials restate no token | `design/tokens.test.ts` |
| Control heights, rhythm px, heading line-height | `design/geometry.test.ts` |
| Card inset steps | `design/card-inset.test.ts` |
| Sans weight roles; loaded mono weights | `design/sans-weights.test.ts`, `design/font-weights.test.ts` |
| Literal colours only fall | `design/literal-colours.test.ts` |
| Hand-rolled UI markers, extinct tokens, click targets | `test/ratchet.test.ts` + `ratchet-baseline.json` |
| Button classes outside `src/ui/` | `test/control-inventory.test.ts` + `control-inventory-baseline.json` |
| Primitive states not repainted | `design/primitive-states.test.ts` |
| Chosen and on states | `design/state-grammar.test.ts`, `state-grammar.spec.ts` |
| Focus ring | `design/focus-ring.test.ts`, `focus-ring.spec.ts`, `combobox-cursor.spec.ts` |
| Text selection | `design/selection.test.ts`, `selection.spec.ts` |
| Viewport breakpoint set | `design/breakpoints.test.ts` |
| Overlays pass `app-overlay`; primitives paint their own chrome | `design/settings-doorway.test.ts` |
| Every class selector is rendered somewhere | `design/dead-rules.test.ts` |
| A selector lives in one sheet; keyframes defined once and reachable | `design/one-definition.test.ts` |
| Filter register type grammar | `design/filter-grammar.test.ts` |
| Every tab wears `PageHeader` | `patterns/page-header.test.ts`, `page-header.spec.ts` |
| Rail boundary named once | `patterns/rail-shell.test.ts` |
| Sticky offsets derived, container queries kept | `features/companies/register.test.ts`, `features/opportunities/board-shell.test.ts` |
| Register screens match the rest | `material-parity.spec.ts` |
| Axe in both themes | `a11y.spec.ts` |
| Visible primaries counted | `job-detail.spec.ts`, `profile.spec.ts` |
| First-run setup | `routing/setupMode.test.tsx`, `features/scope/walk/Walk.test.tsx`, `features/companies/SetupCompanies.test.tsx`, `welcome.spec.ts` |
| The board during and after the first scan | `board-first-scan.spec.ts` |

Baselines move only downward. When a gate fails, change the code.
