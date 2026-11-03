import { useToast } from "../../ui/Toast";
import { useEffect, useRef, useState } from "react";
import { useBodyAttribute } from "../../hooks/useBodyAttribute";
import { useMeasuredCssSize } from "../../hooks/useMeasuredCssSize";
// Plex is the app typeface and is bundled once in main.tsx; the
// self-hosted-not-CDN rationale lives there with the imports.
import { AsyncBoundary } from "../../ui";
import { DIRECTORY_SLUG, useCompanies } from "./CompaniesData";
import { AddCompanyDialog, AddMoreCompanies } from "./AddMoreCompanies";
import { CompaniesIndex } from "./CompaniesIndex";
import { DirectoryNote, SectorSection } from "./CompanyRegisterRows";
import { FollowConfirmDialog } from "./CuratedList";
import { AttentionStrip, LedgerToolbar, RegisterEmpty } from "./RegisterChrome";
import "../../design/materials/register-material.css";
import "./CompaniesSection.css";
import {
  companiesSectionCompanies,
  companiesSectionCompany,
  companiesSectionCoverage,
  companiesSectionLoadFailed,
  companiesSectionLoadingCompanies,
  companiesSectionOpen,
  companiesSectionRefreshFailed,
} from "../../copy/gen/companies";

/* Companies is a ledger: one column, read top to bottom, indexed by sector.
 *
 * Every company is one row, so finding one is a one-dimensional scan and the
 * catalog can be read at rest, with nothing behind a disclosure. Sectors are
 * sticky headings you scroll past rather than boxes you open, and the sector
 * index navigates instead of summarising. Volume bars make "who is hiring"
 * legible without reading a single number.
 *
 * The screen wears the register MATERIAL of the app design system
 * (register-material.css over src/design/tokens.css). The material attribute
 * is set on `body` while mounted so the Add-by-URL Dialog — a portal outside
 * this tree — wears it too.
 *
 * This file is the composition root. The register's rows and sector sections
 * live in CompanyRegisterRows.tsx; the attention strip, toolbar and empty
 * state in RegisterChrome.tsx; the two ways to add companies in
 * AddMoreCompanies.tsx.
 */

/* One failure, one toast, keyed by its subject.
 *
 * A component per failure rather than one effect over the list, because the
 * effect's cleanup DISMISSES: run it over the whole list and a second row
 * failing tears the first row's toast off screen and re-raises it, which
 * re-announces it to a screen reader for an event that did not happen. Mounted
 * under the subject's key and depending only on strings, this re-runs when its
 * own message changes and at no other time. */
function WriteFailureToast({ subject, text }: { subject: string; text: string }) {
  const { toast, dismiss } = useToast();
  useEffect(() => {
    const id = toast({ key: `companies-error:${subject}`, text, tone: "error" });
    return () => dismiss(id);
  }, [subject, text, toast, dismiss]);
  return null;
}

export function CompaniesSection() {
  const rootRef = useRef<HTMLElement>(null);
  const toolbarRef = useRef<HTMLDivElement>(null);
  useMeasuredCssSize({ rootRef, elementRef: toolbarRef, property: "--register-toolbar-h", ignoreZero: true });
  const { resource, groups, failures } = useCompanies();
  const [urlOpen, setUrlOpen] = useState(false);

  // The material rides on `body` so the Dialog portal, which renders outside
  // this tree, is painted by the same material as the register behind it.
  useBodyAttribute("data-material", "register");

  return (
    <section className="company-ledger" aria-label={companiesSectionCompanies()} ref={rootRef}>
      {/* A write failure is not transient: it stays until its own subject is
          written again. Same layer as every confirmation, error tone. */}
      {failures.map((failure) => (
        <WriteFailureToast key={failure.key} subject={failure.key} text={failure.text} />
      ))}
      <AsyncBoundary
        resource={resource}
        failed={companiesSectionLoadFailed()}
        refreshFailed={companiesSectionRefreshFailed()}
        skeleton={<div className="ledger-loading">{companiesSectionLoadingCompanies()}</div>}
      >
        {() => {
          const visible = groups.filter((group) => group.rows.length > 0);
          return (
            <>
              <AttentionStrip />
              <LedgerToolbar toolbarRef={toolbarRef} />
              <div className="ledger-body">
                <div className="ledger-side">
                  <CompaniesIndex />
                </div>
                <div className="ledger-register">
                  <div className="ledger-row ledger-colhead" aria-hidden="true">
                    <span />
                    <span />
                    <span>{companiesSectionCompany()}</span>
                    <span className="ledger-state-cell">{companiesSectionCoverage()}</span>
                    <span className="ledger-num">{companiesSectionOpen()}</span>
                    <span className="ledger-bar-cell" />
                    <span />
                  </div>

                  {visible.map((group) => (
                    <SectorSection
                      key={group.slug}
                      group={group}
                      before={group.slug === DIRECTORY_SLUG ? <DirectoryNote /> : undefined}
                      collapsible={group.slug === DIRECTORY_SLUG}
                    />
                  ))}

                  {visible.length === 0 && <RegisterEmpty />}

                  <AddMoreCompanies onAdd={() => setUrlOpen(true)} />
                </div>
              </div>
            </>
          );
        }}
      </AsyncBoundary>

      <AddCompanyDialog open={urlOpen} onClose={() => setUrlOpen(false)} />
      <FollowConfirmDialog />
    </section>
  );
}
