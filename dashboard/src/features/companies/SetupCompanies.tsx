import "./SetupCompanies.css";
import { useState } from "react";
import { Button, CompanyIcon, Icon } from "../../ui";
import type { SetupCompaniesProps } from "../../routing/setupMode";
import { CompaniesDataProvider, useCompanies, useCompanyDirectory } from "./CompaniesData";
import { FollowConfirmDialog } from "./CuratedList";
import { aboutCount, listedCompanies } from "./companiesModel";
import {
  companiesSetupAndMore,
  companiesSetupBack,
  companiesSetupChoiceAria,
  companiesSetupEveryListed,
  companiesSetupEveryListedDetail,
  companiesSetupEverything,
  companiesSetupEverythingDetail,
  companiesSetupFollowedNow,
  companiesSetupLater,
  companiesSetupLoadFailed,
  companiesSetupStart,
  companiesSetupWellKnown,
  companiesSetupWellKnownDetail,
} from "../../copy/gen/companies";

/* First-run setup's last step: which companies the radar scans.

   A fresh install follows the curated list, and keeping what it follows is
   the default answer. The step names what is followed, not the list itself:
   an install that left setup and came back may follow fewer or more.
   The two wider answers are the Settings register's own bulk follows: Follow
   all, and for "Plus other companies" Follow all together with the set of other
   companies, asked as ONE question. They go through the register's
   confirmation, because for a company whose site limits collection the
   dialog's words ARE the consent the server records (followCopy.ts). Setup
   goes on only once that question is answered yes; a cancel leaves the person
   on this step with nothing followed.
 */

type Choice = "curated" | "listed" | "everything";
const CHOICES: readonly string[] = ["curated", "listed", "everything"] satisfies Choice[];

/** How many names stand for the followed companies before "and N more". */
const NAMES_SHOWN = 10;

function SetupCompaniesBody({ footClassName, saving, onBack, onStart, keptChoice, onChoice }: SetupCompaniesProps) {
  const { resource, listAction, requestListAction, requestEverything } = useCompanies();
  const { status } = useCompanyDirectory();
  const [chosen, setChosen] = useState<Choice>(() => (keptChoice && CHOICES.includes(keptChoice) ? keptChoice as Choice : "curated"));
  const [asking, setAsking] = useState(false);

  const state = resource.data ?? null;
  const followed = state?.companies.filter((company) => company.enabled) ?? [];
  const listedCount = listedCompanies(state).length;
  const directorySize = status && !status.following ? status.size : 0;
  // A kept choice the install no longer offers falls back to the default.
  const choice: Choice = (chosen === "listed" && listedCount === 0) || (chosen === "everything" && directorySize === 0) ? "curated" : chosen;

  const start = () => {
    if (choice === "everything") {
      setAsking(true);
      requestEverything();
      return;
    }
    if (choice === "listed" && listAction === "follow-all") {
      setAsking(true);
      requestListAction();
      return;
    }
    void onStart();
  };

  const answered = (followed: boolean) => {
    setAsking(false);
    if (followed) void onStart();
  };

  const options: { id: Choice; label: string; detail: string | null; available: boolean }[] = [
    {
      id: "curated",
      label: companiesSetupWellKnown(),
      detail: followed.length > 0 ? companiesSetupWellKnownDetail({ count: followed.length }) : null,
      available: true,
    },
    {
      id: "listed",
      label: companiesSetupEveryListed(),
      detail: listedCount > 0 ? companiesSetupEveryListedDetail({ count: listedCount }) : null,
      available: listedCount > 0,
    },
    {
      id: "everything",
      label: companiesSetupEverything(),
      detail: directorySize > 0 ? companiesSetupEverythingDetail({ about: aboutCount(directorySize) }) : null,
      available: directorySize > 0,
    },
  ];

  return (
    <div className="setup-companies">
      {followed.length > 0 && (
        <div>
          <p className="setup-companies-label">{companiesSetupFollowedNow()}</p>
          <ul className="setup-companies-names">
            {followed.slice(0, NAMES_SHOWN).map((company) => (
              <li key={company.slug} data-selection="content">
                <CompanyIcon slug={company.slug} display={company.display} size={16} />
                {company.display}
              </li>
            ))}
            {followed.length > NAMES_SHOWN && (
              <li className="setup-companies-more">{companiesSetupAndMore({ count: followed.length - NAMES_SHOWN })}</li>
            )}
          </ul>
        </div>
      )}
      {resource.error && !state && <p className="setup-companies-note" role="status">{companiesSetupLoadFailed()}</p>}

      <fieldset className="setup-companies-choice">
        <legend className="sr-only">{companiesSetupChoiceAria()}</legend>
        <div className="select-card-grid walk-cards">
          {options.filter((option) => option.available).map((option) => (
            <label className="select-card" key={option.id}>
              <input
                type="radio"
                name="setup-companies"
                checked={choice === option.id}
                onChange={() => {
                  setChosen(option.id);
                  onChoice?.(option.id);
                }}
              />
              <span className="select-card-label">{option.label}</span>
              {option.detail && <small>{option.detail}</small>}
            </label>
          ))}
        </div>
      </fieldset>

      <p className="setup-companies-note">
        <Icon name="gear" size={14} />
        {companiesSetupLater()}
      </p>

      <footer className={footClassName}>
        <Button variant="ghost" onClick={onBack}>{companiesSetupBack()}</Button>
        <Button variant="primary" onClick={start} disabled={saving || asking}>
          {companiesSetupStart({ choice: saving ? "yes" : "no" })}
        </Button>
      </footer>
      <FollowConfirmDialog onAnswered={answered} />
    </div>
  );
}

export function SetupCompanies(props: SetupCompaniesProps) {
  return (
    <CompaniesDataProvider>
      <SetupCompaniesBody {...props} />
    </CompaniesDataProvider>
  );
}
