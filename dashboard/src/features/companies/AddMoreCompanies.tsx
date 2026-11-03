import { number as copyNumber } from "../../copy/format";
import { errorText } from "../../api/errorText";
import { FormEvent, ReactNode, useEffect, useRef, useState } from "react";
import { Dialog, Icon, ProgressBar } from "../../ui";
import { Button } from "../../ui/Button";
import { ADD_MORE_SLUG, useCompanies, useCompanyDirectory } from "./CompaniesData";
import { aboutCount } from "./companiesModel";
import {
  companiesAddMoreCompaniesASpecificCompany,
  companiesAddMoreCompaniesAboutCompaniesCheckedDaily,
  companiesAddMoreCompaniesFirstScanState,
  companiesAddMoreCompaniesAboutCompaniesOnTheSame,
  companiesAddMoreCompaniesAcme,
  companiesAddMoreCompaniesAddACompanyByLink,
  companiesAddMoreCompaniesAddByLinkDialog,
  companiesAddMoreCompaniesAddByLink,
  companiesAddMoreCompaniesAddCompany,
  companiesAddMoreCompaniesAddMoreCompanies,
  companiesAddMoreCompaniesAddedByItsCareersPage,
  companiesAddMoreCompaniesCancel,
  companiesAddMoreCompaniesCareersPageLink,
  companiesAddMoreCompaniesCareersPageLinkAria,
  companiesAddMoreCompaniesCompaniesScanned,
  companiesAddMoreCompaniesCompanyName,
  companiesAddMoreCompaniesCouldnTAddThatCompany,
  companiesAddMoreCompaniesEachOneIsCheckedDaily,
  companiesAddMoreCompaniesFindTheOnesHiringFor,
  companiesAddMoreCompaniesHiringForYou,
  companiesAddMoreCompaniesHiringForYouSoFar,
  companiesAddMoreCompaniesFirstScanNote,
  companiesAddMoreCompaniesNotOnThisListPaste,
  companiesAddMoreCompaniesDailyCheckNote,
  companiesAddMoreCompaniesQuietToday,
  companiesAddMoreCompaniesScannedOfAbout,
  companiesAddMoreCompaniesStopScanning,
  companiesAddMoreCompaniesStopScanningTheWiderMarket,
  companiesAddMoreCompaniesTheWiderMarket,
  companiesAddMoreCompaniesTheWiderMarketHeading,
  companiesAddMoreCompaniesTryAgain,
} from "../../copy/gen/companies";

/* The end of the register: companies that are not on it.
 *
 * Two ways in, side by side because they are independent and a user may take
 * both: the set of other companies, scanned daily and followed only where it
 * hires for the radar, and one company the user has in mind, by its link.
 * The set's whole state lives in its card: the offer, the first pass's
 * progress, and the way to stop. The companies it found are ordinary rows in
 * the "Other companies" group above. */
export function AddMoreCompanies({ onAdd }: { onAdd: () => void }) {
  const { searching, scrollTarget, clearScrollTarget } = useCompanies();
  const { status, requestDirectory } = useCompanyDirectory();
  const headingRef = useRef<HTMLHeadingElement>(null);

  // An index link lands here like it lands on a sector: in view, and focused.
  useEffect(() => {
    if (scrollTarget !== ADD_MORE_SLUG) return;
    clearScrollTarget();
    const heading = headingRef.current;
    if (!heading) return;
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    heading.scrollIntoView?.({ block: "start", behavior: reduced ? "auto" : "smooth" });
    heading.focus();
  }, [scrollTarget, clearScrollTarget]);

  const size = status?.size ?? 0;
  // A search is about finding one company; the set's card waits.
  const showSet = size > 0 && !searching;

  return (
    <section className="ledger-add-more" aria-labelledby="ledger-add-more-title">
      <h2 className="ledger-sector-title" id="ledger-add-more-title" ref={headingRef} tabIndex={-1}>
        {companiesAddMoreCompaniesAddMoreCompanies()}
      </h2>
      <div className="ledger-add-more-options">
        {showSet && status && <SetCard status={status} requestDirectory={requestDirectory} />}
        <AddCard
          icon="plus"
          title={companiesAddMoreCompaniesASpecificCompany()}
          fact={companiesAddMoreCompaniesAddedByItsCareersPage()}
          note={companiesAddMoreCompaniesNotOnThisListPaste()}
          action={
            <Button className="ui-btn-strong" onClick={onAdd}>
              {companiesAddMoreCompaniesAddByLink()}
            </Button>
          }
        />
      </div>
    </section>
  );
}

/** One card anatomy for both ways in, so they read as a pair: a header (icon
 *  tile, title, one fact), a body on the card's own left edge, and the action
 *  pinned to the foot so the two buttons share a line whatever the bodies
 *  hold. Copy never names the app: two cards side by side saying "RoleBand"
 *  twice would be the first thing a reader notices. */
function AddCard({
  icon,
  title,
  fact,
  note,
  label,
  children,
  action,
}: {
  icon: "plus" | "globe";
  title: string;
  fact: string;
  note: string;
  label?: string;
  children?: ReactNode;
  action: ReactNode;
}) {
  return (
    <div className="ledger-add-card" role={label ? "group" : undefined} aria-label={label}>
      <div className="ledger-add-card-head">
        <span className="ledger-add-card-icon" aria-hidden="true">
          <Icon name={icon} size={18} />
        </span>
        <div>
          <h3 className="ledger-add-card-title">{title}</h3>
          <p className="ledger-add-card-fact">{fact}</p>
        </div>
      </div>
      {children}
      <p className="ledger-add-card-note">{note}</p>
      <div className="ledger-add-card-actions">{action}</div>
    </div>
  );
}

/** A pair of figures over the set's progress: a numeral, then what it counts.
 *  Read in that order by a screen reader and by a copy, so each one is a
 *  phrase ("6,610 scanned of about 13,000"), never a label then a number. */
function SetFigures({ figures }: { figures: [value: string, label: string][] }) {
  return (
    <div className="ledger-add-card-figures" data-selection="chrome">
      {figures.map(([value, label]) => (
        <p key={label}>
          <b>{value}</b> <span>{label}</span>
        </p>
      ))}
    </div>
  );
}

function SetCard({
  status,
  requestDirectory,
}: {
  status: NonNullable<ReturnType<typeof useCompanyDirectory>["status"]>;
  requestDirectory: (following: boolean) => void;
}) {
  const about = aboutCount(status.size);
  const firstPass = status.following && status.checked < status.to_check;
  const hiring = copyNumber(status.with_roles);
  const quiet = Math.max(0, status.to_check - status.with_roles);
  // The scan waits for mains power: said, so a line that stopped
  // moving is not read as a broken scan.
  const onBattery = status.waiting_for_power;
  const label = companiesAddMoreCompaniesTheWiderMarket();

  const stop = (
    <Button aria-label={companiesAddMoreCompaniesStopScanningTheWiderMarket()} onClick={() => requestDirectory(false)}>
      {companiesAddMoreCompaniesStopScanning()}
    </Button>
  );

  if (!status.following) {
    return (
      <AddCard
        icon="globe"
        label={label}
        title={companiesAddMoreCompaniesTheWiderMarketHeading()}
        fact={companiesAddMoreCompaniesAboutCompaniesOnTheSame({ about: String(about) })}
        note={companiesAddMoreCompaniesEachOneIsCheckedDaily()}
        action={
          <Button className="ui-btn-strong" onClick={() => requestDirectory(true)}>
            {companiesAddMoreCompaniesFindTheOnesHiringFor()}
          </Button>
        }
      />
    );
  }

  return firstPass ? (
    <AddCard
      icon="globe"
      label={label}
      title={companiesAddMoreCompaniesTheWiderMarketHeading()}
      fact={companiesAddMoreCompaniesFirstScanState({ scan: onBattery ? "paused" : "running", about: String(about) })}
      note={
        companiesAddMoreCompaniesFirstScanNote({ scan: onBattery ? "paused" : "running" })
      }
      action={stop}
    >
      <SetFigures
        figures={[
          [copyNumber(status.checked), companiesAddMoreCompaniesScannedOfAbout({ to_check: String(aboutCount(status.to_check)) })],
          [hiring, companiesAddMoreCompaniesHiringForYouSoFar()],
        ]}
      />
      <ProgressBar value={status.checked} max={status.to_check} label={companiesAddMoreCompaniesCompaniesScanned()} />
    </AddCard>
  ) : (
    <AddCard
      icon="globe"
      label={label}
      title={companiesAddMoreCompaniesTheWiderMarketHeading()}
      fact={companiesAddMoreCompaniesAboutCompaniesCheckedDaily({ about: String(about) })}
      note={
        companiesAddMoreCompaniesDailyCheckNote({ scan: onBattery ? "paused" : "running" })
      }
      action={stop}
    >
      <SetFigures
        figures={[
          [hiring, companiesAddMoreCompaniesHiringForYou()],
          [copyNumber(quiet), companiesAddMoreCompaniesQuietToday()],
        ]}
      />
    </AddCard>
  );
}

export function AddCompanyDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { addByUrl } = useCompanies();
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [adding, setAdding] = useState(false);
  // The dialog says why an add failed, inside itself: an app-wide
  // toast paints under the scrim. The typed values stay, so trying again is
  // one click.
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!url.trim()) return;
    setAdding(true);
    setError(null);
    try {
      await addByUrl({ name: name.trim(), careers_url: url.trim() });
      setName("");
      setUrl("");
      onClose();
    } catch (caught) {
      // The action, then why from the failure's code, or the next step.
      setError(companiesAddMoreCompaniesCouldnTAddThatCompany({ caught: String(errorText(caught, companiesAddMoreCompaniesTryAgain())) }));
    } finally {
      setAdding(false);
    }
  };

  return (
    <Dialog
      isOpen={open}
      onClose={onClose}
      label={companiesAddMoreCompaniesAddByLinkDialog()}
      width={420}
      className="app-overlay"
    >
      <form className="ledger-form" onSubmit={submit}>
        <h3>{companiesAddMoreCompaniesAddACompanyByLink()}</h3>
        <div>
          <label htmlFor="company-url-name">{companiesAddMoreCompaniesCompanyName()}</label>
          <input
            id="company-url-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder={companiesAddMoreCompaniesAcme()}
          />
        </div>
        <div>
          <label htmlFor="company-url-value">{companiesAddMoreCompaniesCareersPageLink()}</label>
          <input
            id="company-url-value"
            type="url"
            aria-label={companiesAddMoreCompaniesCareersPageLinkAria()}
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            placeholder="https://company.com/careers"
            required
          />
        </div>
        {error && <p className="ledger-form-error" role="alert">{error}</p>}
        <div className="ledger-form-actions">
          <Button onClick={onClose}>{companiesAddMoreCompaniesCancel()}</Button>
          <Button variant="primary" type="submit" disabled={adding}>
            {companiesAddMoreCompaniesAddCompany({ state: adding ? "adding" : "idle" })}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
