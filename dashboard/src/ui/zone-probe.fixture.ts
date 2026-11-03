/* Positive control for the F1 -> F6 boundary (`src/test/shell-zone.test.ts`).

   A primitive reaching UP into the shell is the violation the ui zone exists to
   stop. This file commits it on purpose, which is why it is excluded from
   `npm run lint` in eslint.config.js and linted explicitly by that test.

   Side-effect import: the fixture has to CARRY the edge, and a bound name it
   never uses would fail `noUnusedLocals` in the build. */
import "../shell/NavRail";
