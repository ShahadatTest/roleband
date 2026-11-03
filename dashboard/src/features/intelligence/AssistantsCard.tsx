// Card 2: the MCP server. Cloud-connected, and it says so.
//
// The card is a data sheet first: what a connected app WILL see and what it
// NEVER sees, stated before anything can be enabled. Both lists are read off
// the MCP server's actual payload (backend/tracker/mcp/server.py::_opportunity
// and the tool set): copy here may not promise more or less than that code.
// The lists say WHAT is visible, not how much of it: a live count would read
// as one more shared item and cost a `/api/stats` fetch this card has no
// other use for. One gate switch allows apps to connect at all; the tiles
// stay dimmed and their setup unreachable until it is on.
import { errorText } from "../../api/errorText";
import { useEffect, useState } from "react";
import { AgentAccessState, api } from "../../api";
import { Button, CompanyIcon, Dialog, Icon, Switch } from "../../ui";
import { OriginBadge } from "./OriginBadge";
import {
  aiAssistantsCardAddThisToTheApp,
  aiAssistantsCardAllowAssistantAppsToConnect,
  aiAssistantsCardAllowAssistantAppsToConnect2,
  aiAssistantsCardAllowAssistantAppsToUpdate,
  aiAssistantsCardAllowedReadOnly,
  aiAssistantsCardAnthropic,
  aiAssistantsCardAnyClientThatSpeaksMcp,
  aiAssistantsCardAppClaudeApp,
  aiAssistantsCardAppCodexApp,
  aiAssistantsCardAppOtherApp,
  aiAssistantsCardClipboardAccessWasBlockedSelect,
  aiAssistantsCardCopy,
  aiAssistantsCardDone,
  aiAssistantsCardItCanThenReadWhat,
  aiAssistantsCardMcpServer,
  aiAssistantsCardMcpServer2,
  aiAssistantsCardMostAppsThatSpeakMcp,
  aiAssistantsCardNeverAnythingFromYourOtherApps,
  aiAssistantsCardNeverYourOwnSalaryOrContacts,
  aiAssistantsCardNeverYourProfileAndIntentStatement,
  aiAssistantsCardNotAllowedNothingIsShared,
  aiAssistantsCardNotAllowedToConnect,
  aiAssistantsCardOffNothingLeavesThisComputer,
  aiAssistantsCardOpenai,
  aiAssistantsCardRunThisOnceInA,
  aiAssistantsCardSetUp,
  aiAssistantsCardSetUpAnotherMcpApp,
  aiAssistantsCardSetUpTheClaudeApp,
  aiAssistantsCardSetUpTheCodexApp,
  aiAssistantsCardSharesPayLevelAndHowLongTheRoleHasBeen,
  aiAssistantsCardSharesPublicPagesItAsksRolebandToOpen,
  aiAssistantsCardSharesRoleTitlesCompaniesLocationsAndLink,
  aiAssistantsCardSharesTheFullPostingWhenTheyOpenOne,
  aiAssistantsCardSharesYourProgressOnRolesStagePriorityNo,
  aiAssistantsCardStageNotesNextActionAudited,
  aiAssistantsCardWhatWillBeShared,
  aiAssistantsCardWhatWillNotBeShared,
} from "../../copy/gen/ai";

const WILL_SEE = [
  aiAssistantsCardSharesRoleTitlesCompaniesLocationsAndLink,
  aiAssistantsCardSharesPayLevelAndHowLongTheRoleHasBeen,
  aiAssistantsCardSharesTheFullPostingWhenTheyOpenOne,
  aiAssistantsCardSharesYourProgressOnRolesStagePriorityNo,
  aiAssistantsCardSharesPublicPagesItAsksRolebandToOpen,
];

const NEVER_SEES = [
  aiAssistantsCardNeverYourProfileAndIntentStatement,
  aiAssistantsCardNeverYourOwnSalaryOrContacts,
  aiAssistantsCardNeverAnythingFromYourOtherApps,
];

type App = "claude" | "codex" | "other";

/** The named clients we can give an exact recipe for, plus the open door: MCP
 *  is a protocol, not two products, so a third tile carries the standard JSON
 *  any other client accepts. `slug` is a company mark (Simple Icons); its
 *  absence means the tile wears a UI glyph instead: the two icon sets stay
 *  split by domain, and "any client" is not a company. */
const APPS: Record<
  App,
  { name: string; service: string; slug?: string; setup: string }
> = {
  claude: {
    get name() { return aiAssistantsCardAppClaudeApp(); },
    get service() { return aiAssistantsCardAnthropic(); },
    slug: "claude",
    get setup() { return aiAssistantsCardSetUpTheClaudeApp(); },
  },
  codex: {
    get name() { return aiAssistantsCardAppCodexApp(); },
    get service() { return aiAssistantsCardOpenai(); },
    slug: "codex",
    get setup() { return aiAssistantsCardSetUpTheCodexApp(); },
  },
  other: {
    get name() { return aiAssistantsCardAppOtherApp(); },
    get service() { return aiAssistantsCardAnyClientThatSpeaksMcp(); },
    get setup() { return aiAssistantsCardSetUpAnotherMcpApp(); },
  },
};

export function AssistantsCard() {
  const [state, setState] = useState<AgentAccessState | null>(null);
  const [setup, setSetup] = useState<App | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .agentAccess()
      .then(setState)
      .catch((e) => setError(errorText(e)));
  }, []);

  const save = async (enabled: boolean, allowWrites: boolean) => {
    setSaving(true);
    setError(null);
    try {
      setState(await api.setAgentAccess(enabled, enabled && allowWrites));
    } catch (e) {
      setError(errorText(e));
    } finally {
      setSaving(false);
    }
  };

  const allowed = state?.enabled ?? false;
  const writes = state?.allow_writes ?? false;

  return (
    <section className="intel-card" aria-label={aiAssistantsCardMcpServer2()}>
      <div className="intel-head">
        <div className="intel-head-title">
          <h2>{aiAssistantsCardMcpServer()}</h2>
          <OriginBadge origin="cloud" />
        </div>
        <span className="intel-aside">
          {allowed ? (
            <>{aiAssistantsCardAllowedReadOnly({ choice: (writes) ? "yes" : "no" })}</>
          ) : (
            <>{aiAssistantsCardNotAllowedNothingIsShared()}</>
          )}
        </span>
      </div>

      {/* The sheet and the tiles share the split; the grants do NOT. They are
          the card's control, not a note beside the sheet, and span the card so
          their one-line gate row never depends on the tiles' fixed width. */}
      <div className="intel-split">
        <div>
          <div className="intel-sheet">
            <div>
              <h3>{aiAssistantsCardWhatWillBeShared()}</h3>
              <ul>
                {WILL_SEE.map((say) => say()).map((item) => (
                  <li key={item}>
                    <span className="intel-sheet-glyph" aria-hidden="true">
                      <Icon name="check" size={14} />
                    </span>
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <h3>{aiAssistantsCardWhatWillNotBeShared()}</h3>
              <ul>
                {NEVER_SEES.map((say) => say()).map((item) => (
                  <li key={item} className="is-never">
                    <span className="intel-sheet-glyph" aria-hidden="true">
                      <Icon name="minus" size={14} />
                    </span>
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>

        <div>
          <div className="intel-tiles">
            {(Object.keys(APPS) as App[]).map((app) => (
              <div
                key={app}
                className={`intel-tile${allowed ? "" : " is-waiting"}`}
              >
                <span className="intel-tile-mark">
                  {APPS[app].slug ? (
                    <CompanyIcon
                      slug={APPS[app].slug!}
                      display={APPS[app].name}
                      size={22}
                    />
                  ) : (
                    <Icon name="grid" size={20} />
                  )}
                </span>
                <span>
                  <span className="intel-tile-name">{APPS[app].name}</span>
                  <span className="intel-tile-state">
                    {APPS[app].service}
                    {(" " + aiAssistantsCardNotAllowedToConnect({ choice: (allowed) ? "yes" : "no" }))}
                  </span>
                </span>
                <Button
                  className="ui-btn-strong"
                  disabled={!allowed}
                  title={
                    allowed
                      ? undefined
                      : aiAssistantsCardAllowAssistantAppsToConnect2()
                  }
                  onClick={() => setSetup(app)}
                >
                  {aiAssistantsCardSetUp()}
                </Button>
              </div>
            ))}
          </div>
        </div>

        {/* Both grants in ONE frame: the second is a narrower grant of the
              same permission, and a shared border is what says so. It stays
              its own switch (connecting never implies writing), but the frame
              makes the containment visible. */}
        <div className="intel-grants">
          <div className="intel-gate">
            <Switch
              checked={allowed}
              disabled={saving || state == null}
              onChange={(next) => save(next, writes)}
              label={aiAssistantsCardAllowAssistantAppsToConnect()}
            />
            <b className="intel-grant-name">{aiAssistantsCardAllowAssistantAppsToConnect()}</b>
            {/* No vendor names here. MCP is a protocol and the third tile
                  exists to say so; naming two companies would describe the
                  clients we ship a recipe for rather than what the switch
                  actually opens. The account clause is the
                  load-bearing half anyway: whatever an app sends, it sends
                  under the user's own subscription, never ours. */}
            <span className="intel-gate-note">
              {aiAssistantsCardOffNothingLeavesThisComputer({ choice: (allowed) ? "yes" : "no" })}
            </span>
          </div>

          {/* The narrower grant appears only once the gate is open. While
                nothing may connect, nothing may write either, so this switch
                gates nothing, and this screen's rule is that such a switch does
                not render (same as the egress switch, which appears only once
                an online service exists). Rendering it disabled would put two
                labels of one rank on screen in two different colours. */}
          {allowed && (
            <div className="intel-perm">
              <Switch
                checked={writes}
                disabled={saving}
                onChange={(next) => save(true, next)}
                label={aiAssistantsCardAllowAssistantAppsToUpdate()}
              />
              <b className="intel-grant-name">
                {aiAssistantsCardAllowAssistantAppsToUpdate()}
              </b>
              {writes && (
                <span className="intel-perm-note">
                  {aiAssistantsCardStageNotesNextActionAudited()}
                </span>
              )}
            </div>
          )}
        </div>
      </div>

      {error && (
        <div className="intel-error" role="alert">
          {error}
        </div>
      )}

      {state && setup && (
        <SetupDialog app={setup} state={state} onClose={() => setSetup(null)} />
      )}
    </section>
  );
}

function SetupDialog({
  app,
  state,
  onClose,
}: {
  app: App;
  state: AgentAccessState;
  onClose: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState<string | null>(null);
  // The standard `mcpServers` JSON is what every client but Codex accepts, so
  // the open door hands over exactly the same block rather than a second,
  // hand-written recipe that could drift from it.
  const value =
    app === "codex"
      ? state.codex_command
      : JSON.stringify(state.claude_json, null, 2);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setCopyError(null);
    } catch {
      setCopyError(
        aiAssistantsCardClipboardAccessWasBlockedSelect(),
      );
    }
  };

  return (
    <Dialog
      isOpen
      onClose={onClose}
      label={APPS[app].setup}
      width={520}
      className="app-overlay"
    >
      <div className="ledger-form">
        <h3>{APPS[app].setup}</h3>
        <p className="intel-dialog-note">
          {app === "codex" ? (
            <>{aiAssistantsCardRunThisOnceInA()}</>
          ) : app === "other" ? (
            <>
              {aiAssistantsCardMostAppsThatSpeakMcp()}
            </>
          ) : (
            <>{aiAssistantsCardAddThisToTheApp()}</>
          )}{" "}
          {aiAssistantsCardItCanThenReadWhat()}
        </p>
        <pre className="intel-snippet">{value}</pre>
        {copyError && (
          <p className="intel-dialog-note" role="alert">
            {copyError}
          </p>
        )}
        <div className="ledger-form-actions">
          <Button className="ui-btn-strong" onClick={onClose}>
            {aiAssistantsCardDone()}
          </Button>
          <Button variant="primary" onClick={copy}>
            <Icon name="copy" size={16} />
            {aiAssistantsCardCopy({ choice: (copied) ? "yes" : "no" })}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
