import { useEffect, useState } from "react";
import { type PluginDetail, type PluginRobots, type PluginView, api } from "../../api";
import { list } from "../../copy/format";
import { Button, Dialog, Switch } from "../../ui";
import { Content } from "../../ui/Content";
import { Msg } from "../../ui/Msg";
import {
  settingsPluginSettingsUninstall,
  settingsPluginSettingsUninstallLead,
  settingsPluginSettingsUninstallTitle,
  settingsPluginSettingsVersion,
  settingsPluginsSectionApprove,
  settingsPluginsSectionApproveAndTurnOn,
  settingsPluginsSectionApproveAndUse,
  settingsPluginsSectionApproveCode,
  settingsPluginsSectionApproveFactRank,
  settingsPluginsSectionApproveFacts,
  settingsPluginsSectionApproveGap,
  settingsPluginsSectionApproveIdentity,
  settingsPluginsSectionApproveLead,
  settingsPluginsSectionApproveLeft,
  settingsPluginsSectionApproveLicence,
  settingsPluginsSectionApproveNeeds,
  settingsPluginsSectionApproveRead,
  settingsPluginsSectionApproveReads,
  settingsPluginsSectionApproveSlot,
  settingsPluginsSectionApproveStillOn,
  settingsPluginsSectionApproveTitle,
  settingsPluginsSectionApproveUpdates,
  settingsPluginsSectionBrings,
  settingsCancel,
  settingsPluginsSectionCredit,
  settingsPluginsSectionFactField,
  settingsPluginsSectionRemove,
  settingsPluginsSectionRemoveConfirm,
  settingsPluginsSectionRemoveLead,
  settingsPluginsSectionRemoveTitle,
  settingsPluginsSectionRobotsAllow,
  settingsPluginsSectionRobotsAllowButton,
  settingsPluginsSectionRobotsAllowNote,
  settingsPluginsSectionRobotsClose,
  settingsPluginsSectionRobotsFailed,
  settingsPluginsSectionRobotsHeading,
  settingsPluginsSectionRobotsMore,
  settingsPluginsSectionRobotsNothing,
  settingsPluginsSectionRobotsReading,
  settingsPluginsSectionRobotsSite,
  settingsPluginsSectionRobotsTitle,
  settingsPluginsSectionSchedule,
  settingsPluginsSectionTurnOn,
  settingsPluginsSectionTurnOnLead,
  settingsPluginsSectionTurnOnTitle,
} from "../../copy/gen/settings";
import { sharedResultsOfCompany } from "../../copy/gen/shared";
import { leftToRead, outOf, readFor, removeWords, slotList, slotWord } from "./pluginWords";
// The dialog form these confirmations wear (`.ledger-form`, `.ledger-confirm`)
// belongs to the register material; import it rather than lean on another
// screen's chunk having loaded it.
import "../../design/materials/register-material.css";
import "./PluginsSection.css";

/* The three confirmations a plugin can ask for, shared by Settings > Plugins
   and one plugin's settings. Each shows what the action does before it does it;
   a plugin's own words render through `Content`. */

/** Approval is of the install AS SHOWN: the caller sends this detail's
 *  fingerprint, and a plugin that changed meanwhile is refused. So the dialog
 *  shows everything the approval records: what it is (version, code), what it
 *  brings (slots, company fact fields and their trust, the older rows it
 *  answers with), the sites it reads and how it presents itself there, what
 *  each update receives and when it runs, and whose data it is.
 *  `andTurnOn`: the person reached it through the switch, so approving also
 *  turns it on. A plugin still on (an update lapsed its approval) runs and
 *  answers again once approved, and the button says so. */
/** "pay by level: 7 of 1,180 companies and benefits: 21 of 1,180 companies":
 *  how far each kind has read, so approving says what will still be empty. */
function readSoFar(plugin: PluginView): string {
  return list(plugin.slots.map((slot) => {
    const read = readFor(plugin, slot);
    const t = outOf(plugin, read);
    return settingsPluginsSectionApproveSlot({
      slot: slotWord(slot), count: sharedResultsOfCompany({ n: read, t, total: t }),
    });
  }));
}

/** What turning it on leaves empty: a company it has not
 *  read shows none of it and none of ours, how far each kind has read, and the
 *  time the rest takes. One paragraph, said alike when approving and turning on. */
function GapNote({ plugin }: { plugin: PluginView }) {
  const left = leftToRead(plugin);
  return (
    <p data-testid="plugin-approval-gap">
      {settingsPluginsSectionApproveGap()}
      {plugin.companies > 0 && <>{" "}{settingsPluginsSectionApproveRead({ slots: readSoFar(plugin) })}</>}
      {left && <>{" "}{settingsPluginsSectionApproveLeft(left)}</>}
    </p>
  );
}

/** Turning an approved plugin on while it has read fewer than all followed
 *  companies (`leavesGaps`): it answers app-wide at once, so the switch says
 *  what goes empty first, as approving does. */
export function TurnOnDialog({
  plugin,
  onCancel,
  onTurnOn,
}: {
  plugin: PluginView;
  onCancel: () => void;
  onTurnOn: () => void;
}) {
  return (
    <Dialog isOpen onClose={onCancel} label={settingsPluginsSectionTurnOnTitle()} width={480}
            closeOnScrim={false} className="app-overlay">
      <div className="ledger-form ledger-confirm" data-testid="plugin-turn-on">
        <h3>{settingsPluginsSectionTurnOnTitle()}</h3>
        <p><Content text={plugin.name} /></p>
        <p>{settingsPluginsSectionTurnOnLead()}</p>
        <GapNote plugin={plugin} />
        <div className="ledger-form-actions">
          <Button onClick={onCancel}>{settingsCancel()}</Button>
          <Button variant="primary" onClick={onTurnOn}>{settingsPluginsSectionTurnOn()}</Button>
        </div>
      </div>
    </Dialog>
  );
}

/** The sites' robots files as read for a dialog. */
type RobotsRead = { state: "loading" } | { state: "failed" } | { state: "ready"; robots: PluginRobots };

/** A consent: every site whose file was read, by its sha256 (a site with no rule
 *  today is named too, so rules it adds later are asked about again). */
export type RobotsConsent = Record<string, string>;

const consentFor = (robots: PluginRobots): RobotsConsent =>
  Object.fromEntries(robots.sites.flatMap((site) => (site.sha256 ? [[site.host, site.sha256]] : [])));

const asksToSkip = (robots: PluginRobots) => robots.sites.some((site) => site.state === "rules");

/** Same files as the consent on record: the person already allowed exactly these. */
const sameConsent = (robots: PluginRobots) => {
  const shown = consentFor(robots);
  const kept = robots.consent ?? {};
  return Object.keys(shown).length > 0 && Object.entries(shown).every(([host, sha]) => kept[host] === sha);
};

/** Reads each declared site's robots rules when a dialog opens (network, server side). */
function useSiteRules(id: string): RobotsRead {
  const [read, setRead] = useState<RobotsRead>({ state: "loading" });
  useEffect(() => {
    let live = true;
    api.pluginRobots(id).then(
      (robots) => { if (live) setRead({ state: "ready", robots }); },
      () => { if (live) setRead({ state: "failed" }); },
    );
    return () => { live = false; };
  }, [id]);
  return read;
}

/** Shown rules per site, at most this many each, then "and N more". */
const SHOWN_RULES = 8;

/** What each site's robots file says for RoleBand: its rules, or why there are none. */
function SiteRules({ read }: { read: RobotsRead }) {
  if (read.state === "loading") return <p>{settingsPluginsSectionRobotsReading()}</p>;
  if (read.state === "failed") return <p>{settingsPluginsSectionRobotsFailed()}</p>;
  return (
    <>
      {read.robots.sites.map((site) => (
        <div key={site.host} data-testid={`plugin-robots-site-${site.host}`}>
          <p><b><Content text={site.host} /></b>{" "}{settingsPluginsSectionRobotsSite({ state: site.state })}</p>
          {site.state === "rules" && (
            <ul className="plugin-robots-rules">
              {site.disallow.slice(0, SHOWN_RULES).map((pattern) => (
                <li key={pattern}><code><Content text={pattern} /></code></li>
              ))}
              {site.disallow.length > SHOWN_RULES && (
                <li>{settingsPluginsSectionRobotsMore({ count: site.disallow.length - SHOWN_RULES })}</li>
              )}
            </ul>
          )}
        </div>
      ))}
    </>
  );
}

/** The sites' rules with the person's choice, shared by the approval and Review:
 *  a site that sets rules against RoleBand offers
 *  the switch; the choice is per plugin, covering everything it reads. */
function RobotsChoice({ read, allow, onAllow }: { read: RobotsRead; allow: boolean; onAllow: (next: boolean) => void }) {
  return (
    <div data-testid="plugin-approval-robots">
      <p><b>{settingsPluginsSectionRobotsHeading()}</b></p>
      <SiteRules read={read} />
      {read.state === "ready" && asksToSkip(read.robots) && (
        <>
          <Switch checked={allow} onChange={onAllow} label={settingsPluginsSectionRobotsAllow()}>
            {settingsPluginsSectionRobotsAllow()}
          </Switch>
          <p className="plugin-settings-note">{settingsPluginsSectionRobotsAllowNote()}</p>
        </>
      )}
    </div>
  );
}

/** The choice as the server takes it: the files shown, or null (follow them). */
const choiceOf = (read: RobotsRead, allow: boolean): RobotsConsent | null =>
  read.state === "ready" && allow && asksToSkip(read.robots) ? consentFor(read.robots) : null;

/** Review a plugin's sites' rules after approval (a site changed its file, or a
 *  second thought): allow it past them as shown, or leave it following them. */
export function RobotsDialog({
  plugin,
  onCancel,
  onAllow,
}: {
  plugin: PluginView;
  onCancel: () => void;
  onAllow: (robots: RobotsConsent) => void;
}) {
  const read = useSiteRules(plugin.id);
  const [allow, setAllow] = useState(false);
  const rules = read.state === "ready" && asksToSkip(read.robots);
  return (
    <Dialog isOpen onClose={onCancel} label={settingsPluginsSectionRobotsTitle()} width={480} className="app-overlay">
      <div className="ledger-form ledger-confirm" data-testid="plugin-robots">
        <h3>{settingsPluginsSectionRobotsTitle()}</h3>
        <p><Content text={plugin.name} /></p>
        <RobotsChoice read={read} allow={allow} onAllow={setAllow} />
        {read.state === "ready" && !rules && <p>{settingsPluginsSectionRobotsNothing()}</p>}
        <div className="ledger-form-actions">
          {rules ? (
            <>
              <Button onClick={onCancel}>{settingsCancel()}</Button>
              <Button variant="primary" disabled={!allow}
                      onClick={() => { const robots = choiceOf(read, allow); if (robots) onAllow(robots); }}>
                {settingsPluginsSectionRobotsAllowButton()}
              </Button>
            </>
          ) : (
            <Button onClick={onCancel}>{settingsPluginsSectionRobotsClose()}</Button>
          )}
        </div>
      </div>
    </Dialog>
  );
}

export function ApproveDialog({
  detail,
  andTurnOn = false,
  onCancel,
  onApprove,
}: {
  detail: PluginDetail;
  andTurnOn?: boolean;
  onCancel: () => void;
  /** `robots`: the files the person allowed it past, or null. */
  onApprove: (robots: RobotsConsent | null) => void;
}) {
  const read = useSiteRules(detail.id);
  const [allow, setAllow] = useState(false);
  // An approval again (an update lapsed it) shows the choice on record for the
  // same files; changed files start from "follow them".
  const ready = read.state === "ready" ? read.robots : null;
  useEffect(() => { if (ready) setAllow(sameConsent(ready)); }, [ready]);
  const shown = detail.approval;
  const needs = [...new Set(shown.jobs.flatMap((job) => job.needs))];
  const label = detail.enabled
    ? settingsPluginsSectionApproveAndUse()
    : andTurnOn ? settingsPluginsSectionApproveAndTurnOn() : settingsPluginsSectionApprove();
  return (
    <Dialog isOpen onClose={onCancel} label={settingsPluginsSectionApproveTitle()} width={480}
            closeOnScrim={false} className="app-overlay">
      <div className="ledger-form ledger-confirm" data-testid="plugin-approval">
        <h3>{settingsPluginsSectionApproveTitle()}</h3>
        <p><Content text={shown.name} /></p>
        {detail.enabled && <p data-testid="plugin-approval-still-on">{settingsPluginsSectionApproveStillOn()}</p>}
        <p>{settingsPluginsSectionApproveLead()}</p>
        <GapNote plugin={detail} />
        <p data-testid="plugin-approval-version">
          <b>{settingsPluginSettingsVersion()}</b>{" "}<Content text={shown.version} />
        </p>
        {shown.repository && (
          <p data-testid="plugin-approval-code">
            <b>{settingsPluginsSectionApproveCode()}</b>{" "}<Content text={shown.repository} />
          </p>
        )}
        <p>{settingsPluginsSectionBrings({ slots: slotList(shown.slots) })}</p>
        {shown.fact_fields.length > 0 && (
          <p data-testid="plugin-approval-facts">
            {settingsPluginsSectionApproveFacts({
              fields: list(shown.fact_fields.map((field) => settingsPluginsSectionFactField({ field }))),
            })}
            {" "}{settingsPluginsSectionApproveFactRank()}
          </p>
        )}
        {shown.hosts.length > 0 && (
          <p data-testid="plugin-approval-reads">
            <b>{settingsPluginsSectionApproveReads()}</b>{" "}<Content text={list(shown.hosts)} />
            {shown.identity && <>{" "}{settingsPluginsSectionApproveIdentity({ identity: shown.identity })}</>}
          </p>
        )}
        <RobotsChoice read={read} allow={allow} onAllow={setAllow} />
        {shown.jobs.map((job) => (
          <p key={job.name}>
            <b>{settingsPluginsSectionApproveUpdates()}</b>{" "}
            {settingsPluginsSectionSchedule({ schedule: job.schedule })}
          </p>
        ))}
        {needs.map((need) => (
          <p key={need} data-testid="plugin-approval-needs">{settingsPluginsSectionApproveNeeds({ need })}</p>
        ))}
        <p><b>{settingsPluginsSectionCredit()}</b>{" "}<Content text={shown.attribution} /></p>
        <p><b>{settingsPluginsSectionApproveLicence()}</b>{" "}<Content text={shown.licence} /></p>
        <div className="ledger-form-actions">
          <Button onClick={onCancel}>{settingsCancel()}</Button>
          <Button variant="primary" disabled={read.state === "loading"} onClick={() => onApprove(choiceOf(read, allow))}>{label}</Button>
        </div>
      </div>
    </Dialog>
  );
}

/** Remove data deletes rows: the person types the plugin's id to say so. The
 *  id shows as written (the form's labels are upper case, the check is not). */
export function RemoveDataDialog({
  plugin,
  onCancel,
  onRemove,
}: {
  plugin: PluginView;
  onCancel: () => void;
  onRemove: (typed: string) => void;
}) {
  const [typed, setTyped] = useState("");
  return (
    <Dialog isOpen onClose={onCancel} label={settingsPluginsSectionRemoveTitle()} width={440}
            closeOnScrim={false} className="app-overlay">
      <form
        className="ledger-form ledger-confirm"
        onSubmit={(event) => { event.preventDefault(); if (typed === plugin.id) onRemove(typed); }}
      >
        <h3>{settingsPluginsSectionRemoveTitle()}</h3>
        <p>{settingsPluginsSectionRemoveLead(removeWords(plugin))}</p>
        <div>
          <label htmlFor="plugin-remove-confirm" className="plugin-remove-label">
            <Msg of={settingsPluginsSectionRemoveConfirm}
                 elems={{ name: <Content className="plugin-remove-id" text={plugin.id} /> }} />
          </label>
          <input
            id="plugin-remove-confirm"
            autoComplete="off"
            autoCapitalize="off"
            spellCheck={false}
            value={typed}
            onChange={(event) => setTyped(event.target.value)}
          />
        </div>
        <div className="ledger-form-actions">
          <Button onClick={onCancel}>{settingsCancel()}</Button>
          <Button type="submit" variant="danger" disabled={typed !== plugin.id}>
            {settingsPluginsSectionRemove()}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

/** Uninstall keeps every row it published: the dialog says so, and nothing is typed. */
export function UninstallDialog({
  plugin,
  onCancel,
  onUninstall,
}: {
  plugin: PluginView;
  onCancel: () => void;
  onUninstall: () => void;
}) {
  return (
    <Dialog isOpen onClose={onCancel} label={settingsPluginSettingsUninstallTitle()} width={440}
            closeOnScrim={false} className="app-overlay">
      <div className="ledger-form ledger-confirm" data-testid="plugin-uninstall">
        <h3>{settingsPluginSettingsUninstallTitle()}</h3>
        <p><Content text={plugin.name} /></p>
        <p>{settingsPluginSettingsUninstallLead()}</p>
        <div className="ledger-form-actions">
          <Button onClick={onCancel}>{settingsCancel()}</Button>
          <Button variant="danger" onClick={onUninstall}>{settingsPluginSettingsUninstall()}</Button>
        </div>
      </div>
    </Dialog>
  );
}
