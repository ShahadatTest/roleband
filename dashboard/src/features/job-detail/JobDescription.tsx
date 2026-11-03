import type { JobDescriptionSection } from "../../api";
import {
  roleJobDescriptionNoDescriptionCaptured,
} from "../../copy/gen/role";
import { ownHeading } from "../../copy/vocab";
import { Content } from "../../ui/Content";

const LIST_SECTIONS = new Set(["minimum_qualifications", "preferred_qualifications"]);

export function JobDescription({
  sections,
  fallback,
}: {
  sections?: JobDescriptionSection[];
  fallback?: string | null;
}) {
  if (!sections?.length) {
    return <div className="jd jd-fallback">{fallback ? <Content text={fallback} /> : roleJobDescriptionNoDescriptionCaptured()}</div>;
  }

  return (
    <div className="jd-sections">
      {sections.map((section, index) => (
        <section className={`jd-section jd-section-${section.key}`} key={`${section.key}-${index}`}>
          <h2>{ownHeading(section.key, section.title) ?? <Content text={section.title} />}</h2>
          {LIST_SECTIONS.has(section.key) ? (
            <ul>
              {section.content
                .split(/\n+/)
                .map((line) => line.trim())
                .filter(Boolean)
                .map((line, lineIndex) => <li key={lineIndex}><Content text={line} /></li>)}
            </ul>
          ) : (
            section.content
              .split(/\n\s*\n/)
              .map((paragraph) => paragraph.trim())
              .filter(Boolean)
              .map((paragraph, paragraphIndex) => (
                <p key={paragraphIndex}>
                  {paragraph.split("\n").map((line, lineIndex) => (
                    <span key={lineIndex}>
                      {lineIndex > 0 && <br />}
                      <Content text={line} />
                    </span>
                  ))}
                </p>
              ))
          )}
        </section>
      ))}
    </div>
  );
}
