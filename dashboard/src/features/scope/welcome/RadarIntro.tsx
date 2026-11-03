import type { ReactNode } from "react";
import {
  welcomeIntroBegin,
  welcomeIntroBody,
  welcomeIntroKicker,
  welcomeIntroReach,
  welcomeIntroTitle,
  welcomeIntroTune,
} from "../../../copy/gen/welcome";
import { api } from "../../../api";
import { number as copyNumber } from "../../../copy/format";
import { roundCount } from "../../../counts";
import { useAsyncResource } from "../../../hooks/useAsyncResource";
import { Button } from "../../../ui/Button";
import { useEscapeLayer } from "../../../ui/escapeLayer";
import { PhaseFade, Reveal } from "../motion/primitives";
import { Globe } from "./Globe";

/* RadarIntro: the first thing a fresh install sees. Instead of a form, the
   product narrative plays: a planet turns while a scan crosses it and the
   cities RoleBand reads light as it passes. The single CTA (or Escape) moves
   into the tuning walk; nothing autoplays past the user.

   One fact under the copy: how many companies are within reach (the company
   directory, rounded down for "N+"). Not "on the radar": a new install
   follows only its starting list, and the rest are one choice away on the
   companies step. A directory that cannot be read, or is already followed,
   leaves the line out rather than guessing.

   A `question` (the usage-sharing one) is asked in the same scene: the planet
   dims and keeps turning, and the question takes the words' place. */

export default function RadarIntro({ onBegin, question = null }: { onBegin: () => void; question?: ReactNode }) {
  // The scene is the page, so its Escape is a `page` layer: the palette opened
  // over it takes the press first.
  useEscapeLayer(true, onBegin, "page");
  const directory = useAsyncResource(() => api.companyDirectoryStatus(), []);
  const reach = directory.data && !directory.data.following && directory.data.size > 0 ? roundCount(directory.data.size) : 0;

  return (
    <section
      className={question ? "welcome-intro welcome-intro--asking" : "welcome-intro"}
      aria-labelledby={question ? undefined : "welcome-intro-title"}
    >
      <Globe />
      <PhaseFade phaseKey={question ? "question" : "words"} className="welcome-intro-copy">
        {question ?? (
          <div className="welcome-intro-words">
            <Reveal delay={0.1}>
              <div className="eyebrow">{welcomeIntroKicker()}</div>
            </Reveal>
            <Reveal delay={0.22}>
              <h1 id="welcome-intro-title">{welcomeIntroTitle()}</h1>
            </Reveal>
            <Reveal delay={0.34}>
              {/* The promise on one line, the cost on the next: one paragraph. */}
              <p>
                <span className="welcome-intro-line">{welcomeIntroBody()}</span>{" "}
                <span className="welcome-intro-line">{welcomeIntroTune()}</span>
              </p>
            </Reveal>
            {reach > 0 && (
              <Reveal delay={0.46}>
                <div className="welcome-intro-stats">{welcomeIntroReach({ atLeast: copyNumber(reach) })}</div>
              </Reveal>
            )}
            <Reveal delay={0.58}>
              <Button variant="primary" size="lg" className="welcome-intro-cta" onClick={onBegin}>
                {welcomeIntroBegin()}
              </Button>
            </Reveal>
          </div>
        )}
      </PhaseFade>
    </section>
  );
}
