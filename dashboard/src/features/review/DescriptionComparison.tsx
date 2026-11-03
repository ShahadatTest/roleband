import { useMemo, useState } from "react";
import type { Job } from "../../api";
import { blockKey, descriptionBlocks, descriptionSections } from "../../patterns/jobs/descriptionPassages";
import { Button } from "../../ui/Button";
import "./description-comparison.css";
import {
  duplicatesComparisonLedgerEarlierPosting,
  duplicatesComparisonLedgerNewerPosting,
  duplicatesDescriptionComparisonChangedPassage,
  duplicatesDescriptionComparisonDescription,
  duplicatesDescriptionComparisonDescription2,
  duplicatesDescriptionComparisonDescriptionComparison,
  duplicatesDescriptionComparisonDescriptions,
  duplicatesDescriptionComparisonDifferences,
  duplicatesDescriptionComparisonNoDifferingPassages,
  duplicatesDescriptionComparisonShowDifferencesOnly,
} from "../../copy/gen/duplicates";
import { ownHeading } from "../../copy/vocab";
import { Content } from "../../ui/Content";

/* Side-by-side description comparison with passage-level change marking.
 * The queue and the history editor both render it.
 * Exact matching lines are the stable core, regardless of section ordering;
 * any remaining line is visibly marked rather than guessed to be equivalent.
 *
 * Compare does not render this component: it reads three roles at once and
 * lays their descriptions out as aligned COLUMNS (features/compare/descriptions.ts)
 * on the same passage model, `patterns/jobs/descriptionPassages`. */

type ComparedDescriptionSection = {
  key: string;
  title: string;
  prior: ComparedDescriptionBlock[];
  job: ComparedDescriptionBlock[];
};

type ComparedDescriptionBlock = {
  text: string;
  changed: boolean;
};

export function DescriptionComparison({
  prior,
  job,
  priorLabel = duplicatesComparisonLedgerEarlierPosting(),
  jobLabel = duplicatesComparisonLedgerNewerPosting(),
}: {
  prior: Job;
  job: Job;
  priorLabel?: string;
  jobLabel?: string;
}) {
  const [differencesOnly, setDifferencesOnly] = useState(false);
  const sections = useMemo(() => compareDescriptions(prior, job), [prior, job]);
  const changedCount = sections.reduce(
    (count, section) => count + section.prior.filter((block) => block.changed).length + section.job.filter((block) => block.changed).length,
    0,
  );

  if (sections.length === 0) return null;

  return (
    <section className="review-descriptions" aria-label={duplicatesDescriptionComparisonDescriptionComparison()}>
      <header className="review-descriptions-head">
        <div>
          <h3>{duplicatesDescriptionComparisonDescriptions()}</h3>
          <p>
            {duplicatesDescriptionComparisonDifferences({ choice: changedCount > 0 ? "differ" : "same", count: changedCount })}
          </p>
        </div>
        <Button
          size="sm"
          aria-pressed={differencesOnly}
          onClick={() => setDifferencesOnly((value) => !value)}
        >
          {duplicatesDescriptionComparisonShowDifferencesOnly({ choice: (differencesOnly) ? "yes" : "no" })}
        </Button>
      </header>

      <div className="review-description-grid">
        <DescriptionColumn label={priorLabel} sections={sections} side="prior" differencesOnly={differencesOnly} />
        <DescriptionColumn label={jobLabel} sections={sections} side="job" differencesOnly={differencesOnly} />
      </div>
    </section>
  );
}

function DescriptionColumn({
  label,
  sections,
  side,
  differencesOnly,
}: {
  label: string;
  sections: ComparedDescriptionSection[];
  side: "prior" | "job";
  differencesOnly: boolean;
}) {
  const visibleSections = sections
    .map((section) => ({ ...section, blocks: section[side].filter((block) => !differencesOnly || block.changed) }))
    .filter((section) => section.blocks.length > 0);

  return (
    <section className="review-description-column" aria-label={duplicatesDescriptionComparisonDescription2({ label: String(label) })}>
      <h4>{label}</h4>
      <div className="review-description-scroll">
        {visibleSections.length === 0 ? (
          <p className="review-description-empty">{duplicatesDescriptionComparisonNoDifferingPassages()}</p>
        ) : (
          visibleSections.map((section) => (
            <section className="review-description-section" key={section.key}>
              <h5>{ownHeading(section.key, section.title) ?? <Content text={section.title} />}</h5>
              {section.blocks.map((block, index) => (
                <p className={block.changed ? "changed" : undefined} key={`${index}-${block.text.slice(0, 24)}`}>
                  {block.changed && <span className="review-description-change">{duplicatesDescriptionComparisonChangedPassage()}</span>}
                  <Content text={block.text} />
                </p>
              ))}
            </section>
          ))
        )}
      </div>
    </section>
  );
}

function compareDescriptions(prior: Job, job: Job): ComparedDescriptionSection[] {
  const priorSections = descriptionSections(prior);
  const jobSections = descriptionSections(job);
  const jobByKey = new Map(jobSections.map((section) => [section.key, section]));
  const priorKeys = new Set(priorSections.map((section) => section.key));
  const ordered = [
    ...priorSections.map((section) => ({ prior: section, job: jobByKey.get(section.key) })),
    ...jobSections.filter((section) => !priorKeys.has(section.key)).map((section) => ({ prior: undefined, job: section })),
  ];

  return ordered.map(({ prior: priorSection, job: jobSection }, index) => {
    const priorBlocks = descriptionBlocks(priorSection?.content);
    const jobBlocks = descriptionBlocks(jobSection?.content);
    const [priorChanged, jobChanged] = changedBlockIndexes(priorBlocks, jobBlocks);
    return {
      key: priorSection?.key ?? jobSection?.key ?? String(index),
      title: priorSection?.title ?? jobSection?.title ?? duplicatesDescriptionComparisonDescription(),
      prior: priorBlocks.map((text, blockIndex) => ({ text, changed: priorChanged.has(blockIndex) })),
      job: jobBlocks.map((text, blockIndex) => ({ text, changed: jobChanged.has(blockIndex) })),
    };
  });
}

function changedBlockIndexes(prior: string[], job: string[]): [Set<number>, Set<number>] {
  const availableJobIndexes = new Map<string, number[]>();
  job.forEach((text, index) => {
    const indexes = availableJobIndexes.get(blockKey(text)) ?? [];
    indexes.push(index);
    availableJobIndexes.set(blockKey(text), indexes);
  });
  const priorSame = new Set<number>();
  const jobSame = new Set<number>();
  prior.forEach((text, index) => {
    const matches = availableJobIndexes.get(blockKey(text));
    const jobIndex = matches?.shift();
    if (jobIndex != null) {
      priorSame.add(index);
      jobSame.add(jobIndex);
    }
  });
  return [
    new Set(prior.map((_, index) => index).filter((index) => !priorSame.has(index))),
    new Set(job.map((_, index) => index).filter((index) => !jobSame.has(index))),
  ];
}
