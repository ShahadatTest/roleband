Two modules that import each other on purpose.

`import/no-cycle` is enforced with no allowlist, and a graph rule that quietly
stops resolving reports exactly what a clean tree reports: nothing. This pair is
the positive control — `../import-cycles.test.ts` lints it and requires the
error. Excluded from `npm run lint` in `eslint.config.js`; do not "fix" it.
