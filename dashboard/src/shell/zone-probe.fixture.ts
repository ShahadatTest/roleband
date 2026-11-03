/* Positive control for the F6 -> F5 boundary (`src/test/shell-zone.test.ts`).

   The shell composes routes; it must never import one. Same arrangement as its
   sibling in `ui/`: excluded from `npm run lint`, linted by the test. */
import "../routes/BoardRoute";
