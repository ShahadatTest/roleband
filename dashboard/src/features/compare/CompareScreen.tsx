import { CSSProperties, ReactNode, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import type { Job } from "../../api";
import { Cover } from "../../patterns/Cover";
import { CompanyChip } from "../../patterns/companies/CompanyChip";
import { StarButton } from "../../patterns/jobs/JobControls";
import { JobLinkRow } from "../../patterns/jobs/JobLinkRow";
import { Badge, Button, EmptyState, Icon, ResourceLoadState } from "../../ui";
import { ATTRIBUTES, Attr, AttrView, attributeDiffers } from "./attributes";
import { groupLedger } from "../../patterns/ledger";
import { DescriptionColumn, columnDescriptions, nothingShared, nothingToRead } from "./descriptions";
import { useCompareController } from "./useCompareController";
import "./compare.css";
import {
  compareScreenBack,
  compareScreenBackAria,
  compareScreenClear,
  compareScreenCompare,
  compareScreenComparing,
  compareScreenComparison,
  compareScreenDescriptions,
  compareScreenFields,
  compareScreenLoadFailed,
  compareScreenLoading,
  compareScreenNoDescriptionForThisRole,
  compareScreenNotForMe,
  compareScreenNotForMeHideThis,
  compareScreenOnYourOrInUse,
  compareScreenPickAtLeastTwo,
  compareScreenRadar,
  compareScreenRemoveFromComparison,
  compareScreenRemove,
  compareScreenSame,
  compareScreenSaved,
  compareScreenSharedPassagesHidden,
  compareScreenShowOrHide,
  compareScreenDescriptionView,
  compareScreenShowOrHideMatchingFields,
  compareScreenPassagesLegend,
  compareScreenAddAnother,
  compareScreenPicking,
} from "../../copy/gen/compare";
import { Msg } from "../../ui/Msg";
import { ownHeading, sectionTitle } from "../../copy/vocab";
import { Content } from "../../ui/Content";
import { Abbr } from "../../ui/Abbr";

/* The comparison cover (docs/ui.md "Cover"). Not a
 * place: it opens over the list the roles were picked on and Back returns
 * there. `asOverlay` and `onBack` come from the route, which knows which slot
 * it is rendering in; the unit tests render the page shell.
 *
 * ONE grid, three roles wide: the column heads (identity + verbs), the ledger
 * (the facts, with agreement compressed), then the descriptions as aligned
 * columns under the same heads. One grid so that one sticky head row serves
 * everything below it — the reader deep in a description still sees whose
 * column they are in, and the verbs stay within reach. */
export function CompareScreen({
  asOverlay = false,
  onBack = () => {},
}: {
  asOverlay?: boolean;
  onBack?: () => void;
}) {
  const { ids, hydrated, full, jobs, payCover, loading, error, retry, removeOne, clearAll, save, dismiss, openJob } =
    useCompareController();

  // The frame line: what this is and where it stands. "full" is the reason
  // every other row's toggle is disabled, so it is said where the roles are.
  const frame = !hydrated
    ? null
    : ids.length < 2
      ? compareScreenPicking({ picked: ids.length, needed: ids.length === 0 ? "pair" : "another" })
      : compareScreenComparing({ count: jobs.length || ids.length, capacity: full ? "full" : "open" });

  const bar = (
    <>
      <Button onClick={onBack} aria-label={compareScreenBackAria()}>
        <Icon name="arrowLeft" size={15} /> {compareScreenBack()}
      </Button>
      {frame && <span className="cmp-frame" role="status">{frame}</span>}
      <div className="cover-bar-spacer" />
      {/* Below the cap, the way to a third role: back to the list the cover
          was opened over, where the selection is still held. */}
      {ids.length >= 2 && !full && (
        <Button variant="ghost" onClick={onBack}>
          <Icon name="plus" size={14} /> {compareScreenAddAnother()}
        </Button>
      )}
      {ids.length >= 2 && (
        <Button variant="link" onClick={clearAll}>
          {compareScreenClear()}
        </Button>
      )}
    </>
  );

  const shell = (children: ReactNode) => (
    <Cover label={compareScreenComparison()} asOverlay={asOverlay} onBack={onBack} bar={bar} className="compare-cover">
      {/* The cover's one heading, for the document outline; the bar's frame
          line is a status, and the column heads are the visible identity. */}
      <h1 className="sr-only">{compareScreenCompare()}</h1>
      <div className="cmp-body">{children}</div>
    </Cover>
  );

  // Reaching Compare directly, the selection has not been read yet. Showing the
  // "pick at least two" empty state here would tell someone arriving with
  // three roles that they have none, for as long as the read takes.
  if (!hydrated) return shell(<ResourceLoadState error={null} loading={compareScreenLoading()} />);

  if (ids.length < 2) {
    return shell(
      <EmptyState title={compareScreenPickAtLeastTwo()}>
        <Msg
          of={compareScreenOnYourOrInUse}
          elems={{
            radar: <Link to="/">{compareScreenRadar()}</Link>,
            saved: <Link to="/favorites">{compareScreenSaved()}</Link>,
            icon: <Icon name="columns" size={13} />,
          }}
        />
      </EmptyState>,
    );
  }

  if (loading || error) return shell(<ResourceLoadState error={error} loading={compareScreenLoading()} failed={compareScreenLoadFailed()} onRetry={retry} />);

  return shell(
    <div
      className="compare-grid"
      style={{ "--cmp-columns": jobs.length } as CSSProperties}
    >
      {/* Head row: one column per role — identity, and the verbs the row has
          (Save, Not for me) plus the way out of the comparison. Sticky, so
          the reader deep in a description keeps both. */}
      <div className="cmp-corner" />
      {jobs.map((j) => (
        <div className="cmp-head" key={j.id}>
          <CompanyChip slug={j.company} />
          <JobLinkRow className="cmp-head-title" jobId={j.id} company={j.company} onOpen={openJob}>
            {j.title}
          </JobLinkRow>
          <div className="cmp-head-verbs">
            <StarButton on={j.is_favorite} onToggle={() => save(j)} size={16} />
            <Button
              variant="icon"
              size="sm"
              onClick={() => dismiss(j)}
              aria-label={compareScreenNotForMe({ title: String(j.title) })}
              title={compareScreenNotForMeHideThis()}
            >
              <Icon name="eyeOff" size={14} />
            </Button>
            <span className="cmp-head-spacer" />
            <Button
              variant="icon"
              size="sm"
              onClick={() => removeOne(j)}
              aria-label={compareScreenRemoveFromComparison({ title: String(j.title) })}
              title={compareScreenRemove()}
            >
              <Icon name="close" size={14} />
            </Button>
          </div>
        </div>
      ))}

      <Ledger jobs={jobs} view={{ cover: payCover }} />
      <Descriptions jobs={jobs} />
    </div>,
  );
}

/* ---- the facts ------------------------------------------------------------ */

/** A cell across every role column. Literal, because the cap is three and
 *  the dead-rules gate reads class names, not templates. */
const span = (n: number) => (n === 2 ? "cmp-span-2" : "cmp-span-3");

/** Rows where the roles agree are compressed: one Same cell across the
 *  columns instead of the value printed N times, and a run of agreeing rows
 *  becomes one line with a count (patterns/ledger, the rule Duplicates
 *  folds by too). What is left at full size is exactly what differs. */
function Ledger({ jobs, view }: { jobs: Job[]; view: AttrView }) {
  const groups = useMemo(() => groupLedger(ATTRIBUTES, jobs), [jobs]);
  return (
    <>
      {groups.map((group) =>
        group.kind === "row" ? (
          <LedgerRow key={group.row.key} attr={group.row} jobs={jobs} view={view} />
        ) : (
          <LedgerRun key={group.rows.map((a) => a.key).join("-")} attrs={group.rows} jobs={jobs} view={view} />
        ),
      )}
    </>
  );
}

function LedgerRow({ attr, jobs, view, detail = false }: { attr: Attr; jobs: Job[]; view: AttrView; detail?: boolean }) {
  const differs = attributeDiffers(attr, jobs);
  return (
    <div className={`cmp-row${differs ? " cmp-row--diff" : ""}${detail ? " cmp-row--detail" : ""}`}>
      <div className="cmp-label">{attr.fullLabel ? <Abbr short={attr.label} full={attr.fullLabel} /> : attr.label}</div>
      {differs ? (
        jobs.map((j) => (
          <div className="cmp-cell" key={j.id}>
            {attr.render(j, view)}
          </div>
        ))
      ) : (
        <div className={`cmp-cell cmp-same ${span(jobs.length)}`}>
          <div className="cmp-span-body">
            <Badge size="sm">{compareScreenSame()}</Badge>
            {attr.render(jobs[0], view)}
          </div>
        </div>
      )}
    </div>
  );
}

function LedgerRun({ attrs, jobs, view }: { attrs: Attr[]; jobs: Job[]; view: AttrView }) {
  const [open, setOpen] = useState(false);
  const first = attrs[0].label;
  const last = attrs[attrs.length - 1].label;
  return (
    <>
      <div className="cmp-row cmp-row--run">
        <div className="cmp-label">
          <strong>{attrs.length}</strong>{compareScreenFields()}
        </div>
        <div className={`cmp-cell cmp-same ${span(jobs.length)}`}>
          <div className="cmp-span-body">
            <Badge size="sm">{compareScreenSame()}</Badge>
            <span className="cmp-run-range">
              {first} – {last}
            </span>
            <span className="cmp-head-spacer" />
            <Button
              variant="link"
              aria-expanded={open}
              aria-label={compareScreenShowOrHideMatchingFields({ fields: open ? "open" : "folded", count: attrs.length })}
              onClick={() => setOpen((value) => !value)}
            >
              {compareScreenShowOrHide({ fields: open ? "open" : "folded" })} <Icon name={open ? "chevronUp" : "chevronDown"} size={13} />
            </Button>
          </div>
        </div>
      </div>
      {open && attrs.map((attr) => <LedgerRow key={attr.key} attr={attr} jobs={jobs} view={view} detail />)}
    </>
  );
}

/* ---- the descriptions, as columns ------------------------------------------ */

function Descriptions({ jobs }: { jobs: Job[] }) {
  const columns = useMemo(() => columnDescriptions(jobs), [jobs]);
  // Differences first: the reader built this comparison to see what differs,
  // so what every posting says alike is folded behind one line per section.
  const [differencesOnly, setDifferencesOnly] = useState(true);

  if (nothingToRead(columns)) return null;
  // Three employers rarely say anything alike verbatim. When NO passage is
  // shared, marking every passage as different says nothing, and a filter to
  // the differences is the whole text — so neither is offered.
  const comparable = !nothingShared(columns);

  return (
    <>
      <div className="cmp-row cmp-row--divider">
        <div className="cmp-label">{compareScreenDescriptions()}</div>
        <div className={`cmp-cell cmp-divider ${span(jobs.length)}`}>
          <div className="cmp-span-body">
            <span className="cmp-legend">
              {compareScreenPassagesLegend({ passages: comparable ? "shared" : "none" })}
            </span>
            <span className="cmp-head-spacer" />
            {comparable && (
              <Button size="sm" aria-pressed={differencesOnly} onClick={() => setDifferencesOnly((value) => !value)}>
                {compareScreenDescriptionView({ view: differencesOnly ? "differences" : "full" })}
              </Button>
            )}
          </div>
        </div>
      </div>
      {/* ONE row: each column is its posting in its own order, so the row is
          as tall as the tallest posting and no taller. */}
      <div className="cmp-row">
        <div className="cmp-label" />
        {columns.map((column, i) => (
          <ProseColumn
            key={jobs[i].id}
            column={column}
            differencesOnly={comparable && differencesOnly}
            marked={comparable}
          />
        ))}
      </div>
    </>
  );
}

function ProseColumn({
  column,
  differencesOnly,
  marked,
}: {
  column: DescriptionColumn;
  differencesOnly: boolean;
  marked: boolean;
}) {
  if (column.sections.every((section) => section.passages.length === 0)) {
    return (
      <div className="cmp-cell cmp-prose">
        <p className="cmp-prose-note">{compareScreenNoDescriptionForThisRole()}</p>
      </div>
    );
  }
  return (
    <div className="cmp-cell cmp-prose">
      {column.sections.map((section) => {
        const shown = differencesOnly ? section.passages.filter((passage) => passage.unique) : section.passages;
        const hidden = differencesOnly ? section.shared : 0;
        return (
          <section className="cmp-section" key={section.key} aria-label={sectionTitle(section.key, section.title)}>
            <h2 className="cmp-section-title">{ownHeading(section.key, section.title) ?? <Content text={section.title} />}</h2>
            {shown.map((passage, index) => (
              <p
                className={marked && passage.unique ? "cmp-passage cmp-passage--unique" : "cmp-passage"}
                key={`${index}-${passage.text.slice(0, 24)}`}
              >
                {passage.text}
              </p>
            ))}
            {hidden > 0 && (
              <p className="cmp-prose-note">
                <Msg of={compareScreenSharedPassagesHidden} args={{ count: hidden }} elems={{ hidden: hidden }} />
              </p>
            )}
          </section>
        );
      })}
    </div>
  );
}
