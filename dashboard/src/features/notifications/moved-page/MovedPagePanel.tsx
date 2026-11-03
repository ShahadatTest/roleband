import { useState, type FormEvent } from "react";
import type { MovedBoard } from "../../../api";
import { Button } from "../../../ui";
import { foundSentence, type MovedPage } from "./model";
import "./moved-page.css";
import {
  notificationsMovedPagePanelCareersPageLink,
  notificationsMovedPagePanelCheck,
  notificationsMovedPagePanelCouldnTLookJustNow,
  notificationsMovedPagePanelFindNewCareersPage,
  notificationsMovedPagePanelLookingForSNewCareers,
  notificationsMovedPagePanelRolebandCouldnTFindIt,
  notificationsMovedPagePanelNotThisOne,
  notificationsMovedPagePanelPasteTheLinkToS,
  notificationsMovedPagePanelSCareersPage,
  notificationsMovedPagePanelStopFollowing,
  notificationsMovedPagePanelUseThisCareersPage,
} from "../../../copy/gen/notifications";
import { Msg } from "../../../ui/Msg";

export interface MovedPageVerbs {
  /** Where the page went, or null. With `careersUrl`, the page at that link. */
  find: (company: string, careersUrl?: string) => Promise<MovedBoard | null>;
  /** Point the company at what `find` answered. Resolves true once moved. */
  move: (page: MovedPage, board: MovedBoard) => Promise<boolean>;
  stopFollowing: (page: MovedPage) => Promise<void>;
}

type Step =
  | { kind: "idle" }
  | { kind: "looking" }
  | { kind: "found"; board: MovedBoard }
  | { kind: "ask"; note: string };

/** The answers to "{Company}'s careers page is gone": find where it
 *  went, use it, give its link, or stop following. Every verb is the
 *  controller's; this holds only which step the person is on. */
export function MovedPagePanel({ page, verbs }: { page: MovedPage; verbs: MovedPageVerbs }) {
  const [step, setStep] = useState<Step>({ kind: "idle" });
  const [link, setLink] = useState("");
  const [busy, setBusy] = useState(false);
  const inputId = `moved-page-${page.company}`;

  const look = async (careersUrl?: string) => {
    setStep({ kind: "looking" });
    try {
      const board = await verbs.find(page.company, careersUrl);
      if (board) setStep({ kind: "found", board });
      else
        setStep({
          kind: "ask",
          note: notificationsMovedPagePanelRolebandCouldnTFindIt({ choice: (careersUrl) ? "yes" : "no", display: (careersUrl) ? "" : String(page.display) }),
        });
    } catch {
      setStep({ kind: "ask", note: notificationsMovedPagePanelCouldnTLookJustNow() });
    }
  };

  const check = (event: FormEvent) => {
    event.preventDefault();
    if (link.trim()) void look(link.trim());
  };

  const use = async (board: MovedBoard) => {
    setBusy(true);
    try {
      await verbs.move(page, board);
    } finally {
      setBusy(false);
    }
  };

  const stop = (
    <Button size="sm" onClick={() => void verbs.stopFollowing(page)} disabled={busy}>
      {notificationsMovedPagePanelStopFollowing()}
    </Button>
  );

  return (
    <div className="moved-page" role="group" aria-label={notificationsMovedPagePanelSCareersPage({ display: String(page.display) })}>
      {step.kind === "idle" && (
        <div className="moved-page-actions">
          <Button size="sm" className="ui-btn-strong" onClick={() => void look()}>
            {notificationsMovedPagePanelFindNewCareersPage()}
          </Button>
          {stop}
        </div>
      )}
      {step.kind === "looking" && (
        <p className="moved-page-note" role="status">
          <Msg of={notificationsMovedPagePanelLookingForSNewCareers} elems={{ display: page.display }} />
        </p>
      )}
      {step.kind === "found" && (
        <>
          <p className="moved-page-note" role="status">{foundSentence(step.board, page.display)}</p>
          <div className="moved-page-actions">
            <Button size="sm" variant="primary" onClick={() => void use(step.board)} disabled={busy}>
              {notificationsMovedPagePanelUseThisCareersPage({ choice: (busy) ? "yes" : "no" })}
            </Button>
            <Button
              size="sm"
              onClick={() => setStep({ kind: "ask", note: notificationsMovedPagePanelPasteTheLinkToS({ display: String(page.display) }) })}
              disabled={busy}
            >
              {notificationsMovedPagePanelNotThisOne()}
            </Button>
          </div>
        </>
      )}
      {step.kind === "ask" && (
        <>
          <p className="moved-page-note" role="status">{step.note}</p>
          <form className="moved-page-form" onSubmit={check}>
            <label htmlFor={inputId} className="sr-only">{notificationsMovedPagePanelCareersPageLink()}</label>
            <input
              id={inputId}
              type="url"
              value={link}
              onChange={(event) => setLink(event.target.value)}
              placeholder="https://company.com/careers"
              required
            />
            <Button size="sm" type="submit">{notificationsMovedPagePanelCheck()}</Button>
            {stop}
          </form>
        </>
      )}
    </div>
  );
}
