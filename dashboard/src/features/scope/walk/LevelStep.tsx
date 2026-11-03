import { StageDimmer } from "../StageDimmer";

/* Step 2: the level rail, with the grading decoder as a collapsed
   disclosure. The step carries no aim sentence: "interested in" on step 5
   says it in structured form. In first-run setup the rail is the whole
   question: roles that state no level pass by default, and Profile is where
   that is changed. Setup owns the window, so the link out to every
   company's levels waits for Profile too. */
export function LevelStep({ setup = false }: { setup?: boolean }) {
  return <StageDimmer unstatedChoice={!setup} everyCompany={!setup} />;
}
