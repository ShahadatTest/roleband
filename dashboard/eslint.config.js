// F-layer dependency rules (docs/architecture.md).
// Scope: layer enforcement only — general lint stays with tsc/vitest.
// F0 tokens -> F1 ui/ -> F2 services (api, context, hooks, routing, format)
// -> F3 patterns/ -> F4 features/ -> F5 routes/ -> F6 shell.
// F6 is App.tsx, main.tsx and src/shell/ — the chrome App composes. Every zone
// below is an error with no allowlist.
import importPlugin from 'eslint-plugin-import'
import jsxA11y from 'eslint-plugin-jsx-a11y'
import reactHooks from 'eslint-plugin-react-hooks'
import tsParser from '@typescript-eslint/parser'

const zones = [
  // F2 services never reach up into presentation tiers. `src/api` is the typed
  // client, a directory split by domain.
  ...['./src/api', './src/hooks', './src/routing', './src/context', './src/diagnostics'].map((from) => ({
    target: from,
    from: ['./src/routes', './src/ui', './src/patterns', './src/features'],
    message: 'F2 services must not import presentation-layer modules.',
  })),
  // F1 primitives depend only on tokens + services, never on higher tiers.
  {
    target: './src/ui',
    from: ['./src/patterns', './src/features', './src/routes'],
    message: 'ui/ primitives must not import patterns, features, or routes.',
  },
  // F3 patterns sit below features and routes.
  {
    target: './src/patterns',
    from: ['./src/features', './src/routes'],
    message: 'patterns/ must not import features or routes.',
  },
  // F4 features sit below routes.
  {
    target: './src/features',
    from: ['./src/routes'],
    message: 'Feature-tier modules must not import routes.',
  },
  /* F6. One zone rather than a line per tier, because it is one rule: the
     shell is the top, so NOTHING below it may import it. Stated as a list of
     targets, a tier left out is silently exempt, which is why `design` and
     `api` are named too. */
  {
    target: [
      './src/ui', './src/patterns', './src/features', './src/routes',
      './src/hooks', './src/routing', './src/context', './src/design', './src/api', './src/diagnostics',
    ],
    from: ['./src/shell'],
    message:
      'The shell is F6 — the chrome App.tsx composes. Nothing below it may import it; what a screen and the chrome share is a pattern, a primitive or a context.',
  },
  {
    // The other half, and the one a reader gets wrong: the shell COMPOSES
    // routes (App.tsx does), so chrome reaching a route looks reasonable. It
    // is not — the rail and the palette read `navigation.ts` metadata, which
    // is why a label costs nothing to render (`route-registry.test.ts`).
    target: './src/shell',
    from: ['./src/routes', './src/routeRegistry.tsx'],
    message:
      'Shell chrome must not import a route or the route registry. Navigation metadata is src/navigation.ts; App.tsx is where routes are composed.',
  },
]

/* The tier zones above say nothing about one feature reaching into another.
 * The per-feature zones below do: each is an ERROR, with an exact exception
 * list (LEGACY_EDGES) rather than a baseline count, so new code is bound
 * immediately. */
/* EXACT, and gated against disk by `src/test/layer-edges.test.ts`, because a
 * hand list drifts: it can name a deleted directory and miss a new feature. A
 * zone whose target directory does not exist matches nothing and reports
 * nothing, and a feature the list omits is unguarded with no gate saying so.
 *
 * Deriving this from disk here is what one wants and does not work: eslint
 * would read it fine, but `layer-edges.test.ts` imports this config through
 * vite, where `import.meta.url` is not a file: URL, and `readdirSync` throws at
 * import time. Vitest reports that as a suite with NO tests rather than as a
 * failure, so the gate would vanish silently. The test owns the disk read. */
export const FEATURES = [
  'companies', 'company-profiles', 'compare', 'intelligence', 'job-detail',
  'notifications', 'opportunities', 'review', 'saved', 'scope', 'settings',
  'statistics', 'sync',
]

const boundaryZones = [
  // One zone per feature: a feature may not reach into a SIBLING's internals.
  ...FEATURES.map((feature) => ({
    target: `./src/features/${feature}`,
    from: FEATURES.filter((other) => other !== feature).map((other) => `./src/features/${other}`),
    message:
      'Cross-feature import. What two features share is a pattern (patterns/) or a material (design/), not one feature reaching into another.',
  })),
]

/* Every cross-tier edge that exists today, by importer and what it reaches.
 * EXACT, and it may only shrink; it is **zero**. An edge is paid off by moving
 * code to the tier it belongs in, not by an exception: `shell/SyncButton.tsx`
 * -> `features/sync/SyncScopePopover` is F6 -> F4 and legal, so it needs no
 * row.
 *
 * `src/test/layer-edges.test.ts` asserts the count and prunes any row that has
 * stopped being true, so a silently added edge fails and a paid-off one cannot
 * linger as decoration. The list stays here, empty, because that is what the
 * gate freezes: adding a row is a decision, not a formality.
 *
 * Note what the pruning check reads: the IMPORTER's source, not the imported
 * module. The gate answers "does this file still import that", which is the
 * right question and is not the same as "does that module still live there":
 * a moved module keeps its row true until the importer's specifier changes. */
export const LEGACY_EDGES = []

export default [
  /* `src/test/cycle-fixture/` is a deliberate import cycle — the positive
     control for `import/no-cycle`, linted explicitly by
     `src/test/import-cycles.test.ts` with ignores disabled. It is excluded
     here because the whole point is that it violates the rule. */
  /* `*.fixture.ts` are the zone probes (`src/test/shell-zone.test.ts`): two
     modules that commit a boundary violation on purpose, linted explicitly by
     that test with ignores disabled. */
  { ignores: ['dist/**', 'node_modules/**', 'playwright-report/**', 'test-results/**', 'src/test/cycle-fixture/**', 'src/**/*.fixture.ts'] },
  {
    files: ['tests/ux/**/*.spec.ts'],
    languageOptions: { parser: tsParser, sourceType: 'module' },
    linterOptions: { noInlineConfig: true },
    rules: {
      'no-restricted-imports': ['error', { paths: [{
        name: '@playwright/test',
        importNames: ['test'],
        message: 'Import test from ./fixtures so unexpected API requests fail automatically.',
      }] }],
    },
  },
  {
    files: ['src/**/*.{ts,tsx}'],
    languageOptions: {
      parser: tsParser,
      ecmaVersion: 'latest',
      sourceType: 'module',
    },
    linterOptions: {
      // Inline directives in the codebase target rules this scoped config
      // does not load (react-hooks, jsx-a11y); layer rules are never
      // disabled inline, so ignore inline config entirely.
      noInlineConfig: true,
    },
    /* Without a resolver, `import/no-restricted-paths` cannot resolve an
       EXTENSIONLESS specifier — and every import in this codebase is
       extensionless, so every zone above would silently pass everything:
       `import "../features/saved/SavedScreen"` in a ui/ primitive reports "No
       issues found", while the same line with an explicit `.tsx` errors. */
    settings: {
      /* The resolver answers "what file is this specifier?". It is NOT enough
         for the graph rules, which must also PARSE that file to see what it
         imports in turn — and under flat config eslint-plugin-import cannot
         infer a parser for a dependency it was not handed directly. Without
         this line `import/no-cycle` below is inert: configured, reported by
         `npm run lint`, and enforcing nothing: a two-file cycle in `src/`
         lints clean with the resolver alone, and errors with this key present
         (`src/test/import-cycles.test.ts`). */
      'import/parsers': { '@typescript-eslint/parser': ['.ts', '.tsx'] },
      'import/resolver': {
        typescript: { project: './tsconfig.json' },
      },
    },
    plugins: {
      import: importPlugin,
      'jsx-a11y': jsxA11y,
      'react-hooks': reactHooks,
    },
    rules: {
      ...jsxA11y.configs.recommended.rules,
      'import/no-restricted-paths': ['error', { zones: [...zones, ...boundaryZones] }],
      'import/no-duplicates': 'error',
      /* An error with no allowlist. A module that is both a domain model and
         the composition root rendering it makes a child importing a type
         import its own parent; the model goes in a module of its own
         (`intelligence/OriginBadge`, `sync-progress/model`).
         `src/test/import-cycles.test.ts` holds the positive control: a rule
         this one silently stops enforcing looks exactly like a rule that
         passes. */
      'import/no-cycle': ['error', { maxDepth: Infinity }],
      // The compiler-oriented rules in react-hooks' current "recommended"
      // preset assume a React Compiler adoption this React 18 app has not
      // made. Enforce the two runtime hook contracts now; compiler adoption
      // gets its own measured change instead of entering through lint config.
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'error',
    },
  },
  {
    // EXACT debt, not a baseline.
    // Every file here carries a non-semantic click target the a11y preset
    // rightly refuses; the rules stay `error` for every other file, so no
    // new one can land. Three kinds of entry: whole-row targets, a hover card
    // and its test harness, and a hand-rolled backdrop.
    // Remove a file from this list in the change that fixes it; never add one.
    files: [
      // Whole-row targets the control system legitimises (docs/ui.md
      // "Controls"): the row IS the control, and each already carries its own
      // keyboard handling. They owe a keyboard-contract TEST, not a rewrite.
      'src/patterns/jobs/JobCard.tsx',
      'src/patterns/jobs/JobList.tsx',
      'src/features/job-detail/LineageStack.tsx',
      // A hover card is pointer-only by nature: it appears on hover of a real
      // <button> that already carries the keyboard path to the same place, so
      // the card's own click duplicates an accessible control rather than
      // hiding one. Its test harness wraps a chip in a click-counting div.
      'src/patterns/companies/CompanyChip.tsx',
      'src/patterns/companies/CompanyChip.test.tsx',
      // Hand-rolled overlay backdrop (mousedown-outside closes). It belongs in
      // ui/Overlay, which owns that contract; moving it is a behaviour change.
      'src/features/scope/ScopeGuide.tsx',
    ],
    rules: {
      'jsx-a11y/click-events-have-key-events': 'off',
      'jsx-a11y/no-static-element-interactions': 'off',
      'jsx-a11y/no-noninteractive-element-interactions': 'off',
      'jsx-a11y/no-noninteractive-tabindex': 'off',
    },
  },
  {
    // A table its CSS lays out as grids states its roles: an engine that sees a
    // display change on a table part (WebKit) drops the implicit ones. The
    // preset reads those restated roles as redundant or, for a cell, as
    // making an interactive element non-interactive; for this pattern they
    // are neither.
    files: ['src/features/review/ComparisonLedger.tsx'],
    rules: {
      'jsx-a11y/no-redundant-roles': ['error', { thead: ['rowgroup'], tbody: ['rowgroup'] }],
      'jsx-a11y/no-interactive-element-to-noninteractive-role': ['error', { td: ['cell'] }],
    },
  },
  {
    // Deliberate custom widgets WITH keyboard contracts, each with a named
    // remaining gap — an allowlist for a reason the preset cannot see, not
    // for debt.
    //   ChronographDial: the dial stage cancels mousedown so a drag on a
    //     marker cannot start a text selection; it is not a click target. The
    //     allowance sits on the file that holds the handler: an allowance on a
    //     file the code LEFT is an exemption for nothing.
    //   FilterSelect: the popover owns arrow/Enter/Escape on its container
    //     and focuses its search on open by design. Its real gap:
    //     aria-activedescendant sits on the listbox while focus is in the
    //     search field — the combobox pattern wants it on the input, which
    //     needs SearchField to forward the prop.
    //   TabBar: roving tabindex — the TABS are focusable, the tablist itself
    //     need not be; the rule cannot see the pattern.
    files: ['src/features/settings/ChronographDial.tsx'],
    rules: { 'jsx-a11y/no-static-element-interactions': 'off' },
  },
  {
    files: ['src/ui/FilterSelect.tsx'],
    rules: {
      'jsx-a11y/no-static-element-interactions': 'off',
      'jsx-a11y/no-autofocus': 'off',
      'jsx-a11y/aria-activedescendant-has-tabindex': 'off',
    },
  },
  {
    files: ['src/ui/TabBar.tsx'],
    rules: { 'jsx-a11y/interactive-supports-focus': 'off' },
  },
  /* The copy system's two source rules (docs/copy.md).
     1. A test names the message it expects with a LITERAL key: `msg("radar-count")`.
        A key computed from the component's own state-to-message mapping
        agrees with the component whatever it does.
     2. `translate="no"` is written only by `ui/Content`, which takes a string,
        so nothing marks a subtree of copy as third-party content and hides it
        from the pseudo-locale check. */
  {
    files: ['src/**/*.{ts,tsx}', 'tests/ux/**/*.spec.ts'],
    rules: {
      'no-restricted-syntax': ['error',
        {
          selector: 'CallExpression[callee.name="msg"][arguments.0.type!="Literal"]',
          message: 'msg() takes a literal message key, so the test states which message it expects (docs/copy.md).',
        },
        {
          selector: 'JSXAttribute[name.name="translate"]',
          message: 'Render third-party text with ui/Content, which is the only place translate="no" is written.',
        },
      ],
    },
  },
  {
    files: ['src/ui/Content.tsx'],
    rules: { 'no-restricted-syntax': 'off' },
  },
]
