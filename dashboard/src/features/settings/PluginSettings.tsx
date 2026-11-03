import { useCallback, useEffect, useId, useState } from "react";
import { useNavigate } from "react-router-dom";
import { PluginDetail, PluginSchedule, PluginSlot, PluginView, api, isNotFound } from "../../api";
import { date, list, timestamp } from "../../copy/format";
import { useSyncEpoch } from "../../context/SyncState";
import { useAsyncResource, useRefetchOn } from "../../hooks/useAsyncResource";
import { AsyncBoundary, Badge, Button, EmptyState, Icon, Segmented, Switch } from "../../ui";
import { Card, CardMessage, CardRow } from "../../ui/Card";
import { Content, Diagnostic } from "../../ui/Content";
import { Msg } from "../../ui/Msg";
import {
  settingsPluginSettingsBack,
  settingsPluginSettingsBrings,
  settingsPluginSettingsHistory,
  settingsPluginSettingsHowOften,
  settingsPluginSettingsLast,
  settingsPluginSettingsLoadFailed,
  settingsPluginSettingsLoading,
  settingsPluginSettingsNeedsApproval,
  settingsPluginSettingsNext,
  settingsPluginSettingsNextValue,
  settingsPluginSettingsNoHistory,
  settingsPluginSettingsNotFound,
  settingsPluginSettingsOption,
  settingsPluginSettingsOutcome,
  settingsPluginSettingsPublished,
  settingsPluginSettingsRefreshFailed,
  settingsPluginSettingsRemoveHeading,
  settingsPluginSettingsRemoveNote,
  settingsPluginSettingsRemoveWaiting,
  settingsPluginSettingsReport,
  settingsPluginSettingsReportAt,
  settingsPluginSettingsReports,
  settingsPluginSettingsLeft,
  settingsPluginSettingsLeftValue,
  settingsPluginSettingsRobotsReview,
  settingsPluginSettingsRobotsState,
  settingsPluginSettingsRobotsStop,
  settingsPluginSettingsSlotGap,
  settingsPluginSettingsSlotNone,
  settingsPluginsSectionRead,
  settingsPluginSettingsSlotState,
  settingsPluginSettingsSuggests,
  settingsPluginSettingsUninstall,
  settingsPluginSettingsUpdates,
  settingsPluginSettingsVersion,
  settingsPluginsSectionApproveFirst,
  settingsPluginsSectionApproveLicence,
  settingsPluginsSectionApproveReads,
  settingsPluginsSectionCredit,
  settingsPluginsSectionPause,
  settingsPluginsSectionRemove,
  settingsPluginsSectionResume,
  settingsPluginsSectionRobotsHeading,
  settingsPluginsSectionReview,
  settingsPluginsSectionStart,
  settingsPluginsSectionState,
  settingsPluginsSectionTurnOnFirst,
  settingsPluginsSectionUse,
} from "../../copy/gen/settings";
import { ApproveDialog, RemoveDataDialog, RobotsDialog, TurnOnDialog, UninstallDialog } from "./PluginDialogs";
import { PluginDescription, RunWords } from "./PluginOwnWords";
import {
  companiesRead,
  leftToRead,
  outOf,
  readFor,
  removeWords,
  rowState,
  runOutcome,
  runnable,
  slotWord,
} from "./pluginWords";
import { noticeText, usePluginActions } from "./usePluginActions";
import "./PluginsSection.css";

/* One plugin's settings (Settings > Plugins > gear): the
   screen the collapsed row leaves out. Kit cards, as the list is (`ui/Card`):
   the plugin's own card first, its name the heading and its switch left of the
   words it governs ("Use {plugin}"), with approval asked for in that row; then
   how often it updates, when next (Pause / Resume on that line: they govern the
   schedule) and how the last update went (Start on that line), what it brings
   and how many of the followed companies it has read (one it has not shows
   none of it, and none of RoleBand's own in its place) with how long
   the rest takes, whose credit it carries, its
   recent updates (each at its own time, how far it got, and an error's own
   words), and the two irreversible acts: remove its data (typed confirmation,
   only while off) and uninstall (keeps its data, unread). Deep-linkable at
   `/settings/plugins/:id`; "All plugins" goes back.

   Pause has one meaning, here and nowhere else: hold every update (and stop
   the one running); Resume releases it. Neither takes Start's place. The
   switch reads `enabled` (the user's choice); Start, Pause and
   Resume need the plugin runnable (`state === "enabled"`), and Remove data
   needs the switch off, so a plugin whose approval lapsed while on can be
   turned off without approving and only then have its data removed. */

const POLL_MS = 3_000;
type Choice = NonNullable<PluginSchedule>;

/** Does any of the plugin's updates start on its own? A manual schedule
 *  never does, so it has nothing for Pause to stop. */
const scheduled = (plugin: PluginView) => plugin.jobs.some((job) => job.schedule !== "manual");

function nextValue(plugin: PluginView): string {
  if (plugin.state === "needs_approval" && plugin.enabled) {
    return settingsPluginSettingsNextValue({ state: "approval", when: "" });
  }
  if (plugin.state !== "enabled") return settingsPluginSettingsNextValue({ state: "off", when: "" });
  if (plugin.paused) return settingsPluginSettingsNextValue({ state: "paused", when: "" });
  if (plugin.last_run?.continues && !plugin.running) {
    return settingsPluginSettingsNextValue({ state: "continues", when: "" });
  }
  if (!scheduled(plugin)) return settingsPluginSettingsNextValue({ state: "manual", when: "" });
  if (!plugin.next_update_at) return settingsPluginSettingsNextValue({ state: "first", when: "" });
  return settingsPluginSettingsNextValue({ state: "due", when: date(plugin.next_update_at, "weekday") });
}

function UpdatesCard({
  plugin,
  busy,
  starting,
  onSchedule,
  onStart,
  onPause,
  onResume,
}: {
  plugin: PluginView;
  busy: boolean;
  starting: boolean;
  onSchedule: (schedule: Choice) => void;
  onStart: () => void;
  onPause: () => void;
  onResume: () => void;
}) {
  const enabled = runnable(plugin);
  const whyId = useId();
  const suggested: Choice = plugin.jobs[0]?.manifest_schedule ?? "manual";
  const current: Choice = plugin.schedule ?? suggested;
  return (
    <Card title={settingsPluginSettingsUpdates()}>
      <dl className="plugin-settings-facts">
        <div>
          <dt className="eyebrow">{settingsPluginSettingsHowOften()}</dt>
          <dd>
            <Segmented
              label={settingsPluginSettingsHowOften()}
              value={current}
              onChange={(value) => { if (!busy && value !== current) onSchedule(value); }}
              options={plugin.schedules.map((value) => ({
                value, label: settingsPluginSettingsOption({ schedule: value }), disabled: busy,
              }))}
            />
            <small className="plugin-settings-note">{settingsPluginSettingsSuggests({ schedule: suggested })}</small>
          </dd>
        </div>
        {/* Pause and Resume govern the schedule, so they sit on the line that
            says what the schedule does next; Start makes an update now, so it
            sits on the line that says how the last one went. Pause shows
            while a schedule is set or an update runs (it stops that update):
            "When you ask" with nothing running has nothing to pause. Resume
            stays while paused, so a pause kept from an earlier schedule can
            still be lifted. */}
        <div>
          <dt className="eyebrow">{settingsPluginSettingsNext()}</dt>
          <dd className="plugin-settings-line" data-testid="plugin-next-update">
            <span>{nextValue(plugin)}</span>
            {enabled && (plugin.paused ? (
              <Button size="sm" disabled={busy} onClick={onResume}>{settingsPluginsSectionResume()}</Button>
            ) : (scheduled(plugin) || plugin.running) && (
              <Button size="sm" disabled={busy} onClick={onPause}>
                <Icon name="pause" size={14} />
                {settingsPluginsSectionPause()}
              </Button>
            ))}
          </dd>
        </div>
        <div>
          <dt className="eyebrow">{settingsPluginSettingsLast()}</dt>
          <dd className="plugin-settings-line" data-testid="plugin-last-update">
            <span><RunWords run={plugin.last_run} starting={starting && !plugin.running} /></span>
            <span className="plugin-settings-act">
              {!enabled && (
                <span id={whyId} className="plugins-why">
                  {plugin.enabled ? settingsPluginsSectionApproveFirst() : settingsPluginsSectionTurnOnFirst()}
                </span>
              )}
              <Button
                size="sm"
                disabled={busy || starting || plugin.running || !enabled}
                aria-describedby={enabled ? undefined : whyId}
                onClick={onStart}
              >
                <Icon name="play" size={14} />
                {settingsPluginsSectionStart()}
              </Button>
            </span>
          </dd>
        </div>
      </dl>
    </Card>
  );
}

/** One kind of data: how many of the followed companies the plugin has read
 *  whole. While it answers, what each company it has not read shows: none of
 *  this kind, and none of RoleBand's own in its place.
 *  Off or waiting for approval it says why it is not used, then the count it
 *  would answer with. */
function SlotAnswer({ plugin, slot }: { plugin: PluginView; slot: PluginSlot }) {
  const read = readFor(plugin, slot);
  const count = settingsPluginsSectionRead({ read, companies: outOf(plugin, read) });
  if (!runnable(plugin)) {
    const state = plugin.state === "needs_approval" && plugin.enabled ? "approval" : "off";
    return (
      <dd>
        <span>{settingsPluginSettingsSlotState({ state })}</span>
        <small className="plugin-settings-note">{count}</small>
      </dd>
    );
  }
  const left = outOf(plugin, read) - read;
  return (
    <dd>
      <span>{count}</span>
      {plugin.active_slots.includes(slot) && left > 0 && (
        <small className="plugin-settings-note">
          {settingsPluginSettingsSlotGap({
            read, left, none: settingsPluginSettingsSlotNone({ slot: slot.replaceAll(".", "_") }),
          })}
        </small>
      )}
    </dd>
  );
}

/** Whether it follows its sites' robots rules: followed, allowed past
 *  them (since when), or allowed with a site that changed its file since, whose
 *  disallowed pages are skipped until the person reviews them. */
function robotsState(plugin: PluginView): string {
  if (plugin.robots_lapsed.length > 0) {
    return settingsPluginSettingsRobotsState({ state: "lapsed", hosts: list(plugin.robots_lapsed), when: "" });
  }
  if (plugin.robots_consent_at) {
    return settingsPluginSettingsRobotsState({ state: "allowed", hosts: "", when: date(plugin.robots_consent_at) });
  }
  return settingsPluginSettingsRobotsState({ state: "follows", hosts: "", when: "" });
}

function BringsCard({
  plugin,
  busy,
  onReviewRobots,
  onFollowRobots,
}: {
  plugin: PluginView;
  busy: boolean;
  onReviewRobots: () => void;
  onFollowRobots: () => void;
}) {
  const left = leftToRead(plugin);
  const allowed = !!plugin.robots_consent_at && plugin.robots_lapsed.length === 0;
  return (
    <Card title={settingsPluginSettingsBrings()}>
      <dl className="plugin-settings-facts">
        {plugin.slots.map((slot) => (
          <div key={slot} data-testid={`plugin-slot-${slot}`}>
            <dt className="eyebrow">{slotWord(slot)}</dt>
            <SlotAnswer plugin={plugin} slot={slot} />
          </div>
        ))}
        {left && (
          <div data-testid="plugin-left">
            <dt className="eyebrow">{settingsPluginSettingsLeft()}</dt>
            <dd>{settingsPluginSettingsLeftValue(left)}</dd>
          </div>
        )}
        {plugin.reports.length > 0 && (
          <div data-testid="plugin-reports">
            <dt className="eyebrow">{settingsPluginSettingsReports()}</dt>
            <dd>
              <ul className="plugin-settings-reports">
                {plugin.reports.map((report) => (
                  <li key={report.key} data-testid={`plugin-report-${report.key}`}>
                    <span>
                      <Msg of={settingsPluginSettingsReport} args={{ value: report.value }}
                        elems={{ label: <Content text={report.label} /> }} />
                    </span>
                    <small className="plugin-settings-note">
                      {settingsPluginSettingsReportAt({ when: date(report.reported_at) })}
                    </small>
                  </li>
                ))}
              </ul>
            </dd>
          </div>
        )}
        <div>
          <dt className="eyebrow">{settingsPluginsSectionApproveReads()}</dt>
          <dd><Content text={list(plugin.hosts)} /></dd>
        </div>
        <div data-testid="plugin-robots-state">
          <dt className="eyebrow">{settingsPluginsSectionRobotsHeading()}</dt>
          <dd className="plugin-settings-line">
            <span>{robotsState(plugin)}</span>
            {allowed ? (
              <Button size="sm" disabled={busy} onClick={onFollowRobots}>{settingsPluginSettingsRobotsStop()}</Button>
            ) : (
              <Button size="sm" disabled={busy} onClick={onReviewRobots}>{settingsPluginSettingsRobotsReview()}</Button>
            )}
          </dd>
        </div>
        {plugin.attribution && (
          <div>
            <dt className="eyebrow">{settingsPluginsSectionCredit()}</dt>
            <dd><Content text={plugin.attribution} /></dd>
          </div>
        )}
        {plugin.licence && (
          <div>
            <dt className="eyebrow">{settingsPluginsSectionApproveLicence()}</dt>
            <dd><Content text={plugin.licence} /></dd>
          </div>
        )}
        <div>
          <dt className="eyebrow">{settingsPluginSettingsVersion()}</dt>
          <dd><Content text={plugin.version} /></dd>
        </div>
      </dl>
    </Card>
  );
}

/** When an update started, to the minute: three updates one afternoon read
 *  apart, as "3 hours ago" three times would not. Two in one minute (a Pause,
 *  then Start at once) are told apart by their seconds. */
const RUN_TIME: Intl.DateTimeFormatOptions = {
  weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit",
};
const RUN_TIME_SECONDS: Intl.DateTimeFormatOptions = { ...RUN_TIME, second: "2-digit" };

function runTimes(runs: PluginDetail["runs"]): string[] {
  const minutes = runs.map((run) => timestamp(run.started_at, RUN_TIME));
  return runs.map((run, i) => (minutes.indexOf(minutes[i]) !== minutes.lastIndexOf(minutes[i])
    ? timestamp(run.started_at, RUN_TIME_SECONDS) : minutes[i]));
}

/** An update whose end the reader may need explained: its own words follow. */
const EXPLAINED = new Set<string>(["error", "partial"]);

function HistoryCard({ detail }: { detail: PluginDetail }) {
  const times = runTimes(detail.runs);
  return (
    <Card title={settingsPluginSettingsHistory()}>
      {detail.runs.length === 0 ? (
        <EmptyState variant="inline" title={settingsPluginSettingsNoHistory()} />
      ) : (
        <ul className="plugin-settings-runs">
          {detail.runs.map((run, i) => {
            const rows = Object.values(run.published).reduce((sum, n) => sum + n, 0);
            // The plugin's own account of what it did, else how many companies it read.
            const read = run.summary ? <Content text={run.summary} /> : companiesRead(run);
            return (
              <li key={run.id}>
                <time className="plugin-run-when" dateTime={run.started_at}>{times[i]}</time>
                <span className="plugin-run-outcome">{settingsPluginSettingsOutcome({ outcome: runOutcome(run) })}</span>
                {read && <span className="plugin-run-read">{read}</span>}
                <span className="plugin-settings-note plugin-run-rows">{settingsPluginSettingsPublished({ rows })}</span>
                {run.message && EXPLAINED.has(run.outcome) && (
                  <Diagnostic className="plugin-run-message" text={run.message} />
                )}
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}

export function PluginSettings({ pluginId }: { pluginId: string }) {
  const navigate = useNavigate();
  const detail = useAsyncResource<PluginDetail>(() => api.plugin(pluginId), [pluginId]);
  const { referenceVersion } = useSyncEpoch();
  const { refresh, mutate } = detail;
  // A write answers with the row: keep this screen's runs and approval around it.
  const adopt = useCallback((plugin: PluginView) => mutate((current) => (
    current && current.id === plugin.id ? { ...current, ...plugin } : current
  )), [mutate]);
  const actions = usePluginActions({ refresh: () => refresh({ preserveData: true }), adopt });
  const [removing, setRemoving] = useState(false);
  const removeWhyId = useId();
  const [uninstalling, setUninstalling] = useState(false);
  const back = () => navigate("/settings/plugins");

  useRefetchOn(referenceVersion, refresh);

  const running = Boolean(detail.data && (detail.data.running || actions.isStarting(detail.data)));
  useEffect(() => {
    if (!running) return;
    const id = window.setInterval(() => { void refresh({ preserveData: true }); }, POLL_MS);
    return () => window.clearInterval(id);
  }, [running, refresh]);

  return (
    <div className="plugin-settings">
      <Button size="sm" className="plugin-settings-back" onClick={back}>
        <Icon name="arrowLeft" size={14} />
        {settingsPluginSettingsBack()}
      </Button>
      {detail.error && isNotFound(detail.error) ? (
        <CardMessage tone="info" role="status">{settingsPluginSettingsNotFound()}</CardMessage>
      ) : (
        <AsyncBoundary
          resource={detail}
          loading={settingsPluginSettingsLoading()}
          failed={settingsPluginSettingsLoadFailed()}
          refreshFailed={settingsPluginSettingsRefreshFailed()}
        >
          {(plugin) => {
            const busy = actions.busy.has(plugin.id);
            const starting = actions.isStarting(plugin);
            const state = rowState(plugin, starting);
            const error = actions.errorFor(plugin.id);
            const removed = plugin.state === "removed";
            const approval = plugin.state === "needs_approval";
            // The badge says only what the switch beside it does not.
            const tone = state === "needs_approval" ? "warning" : state === "updating" ? "info"
              : removed ? "neutral" : null;
            return (
              <>
                <Card
                  title={<Content text={plugin.name} />}
                  meta={tone && <Badge size="sm" tone={tone}>{settingsPluginsSectionState({ state })}</Badge>}
                >
                  <CardRow
                    toggle={(slot) => (
                      <Switch
                        {...slot}
                        checked={plugin.enabled}
                        onChange={(next) => actions.toggle(plugin, next)}
                        disabled={busy || removed}
                        label={settingsPluginsSectionUse({ name: plugin.name })}
                      />
                    )}
                    title={<Msg of={settingsPluginsSectionUse} elems={{ name: <Content text={plugin.name} /> }} />}
                    description={approval ? settingsPluginSettingsNeedsApproval() : <PluginDescription plugin={plugin} />}
                    trailing={approval && (
                      <Button size="sm" disabled={busy} onClick={() => actions.review(plugin)}>
                        {settingsPluginsSectionReview()}
                      </Button>
                    )}
                  />
                  {actions.notice && <CardMessage tone="info" role="status">{noticeText(actions.notice)}</CardMessage>}
                  {error && <CardMessage role="alert">{error}</CardMessage>}
                </Card>

                {!removed && (
                  <UpdatesCard
                    plugin={plugin}
                    busy={busy}
                    starting={starting}
                    onSchedule={(schedule) => void actions.setSchedule(plugin, schedule)}
                    onStart={() => void actions.start(plugin)}
                    onPause={() => void actions.pause(plugin)}
                    onResume={() => void actions.resume(plugin)}
                  />
                )}
                <BringsCard
                  plugin={plugin}
                  busy={busy}
                  onReviewRobots={() => actions.reviewRobots(plugin)}
                  onFollowRobots={() => void actions.setRobots(plugin, null)}
                />
                <HistoryCard detail={plugin} />

                <Card title={settingsPluginSettingsRemoveHeading()} intro={settingsPluginSettingsRemoveNote(removeWords(plugin))}>
                  <div className="plugin-settings-actions">
                    {/* Held while the stored estimates still read its rows: the
                        server would refuse it then. */}
                    {!plugin.enabled && plugin.estimates_read && (
                      <span id={removeWhyId} className="plugins-why">{settingsPluginSettingsRemoveWaiting()}</span>
                    )}
                    <Button
                      variant="danger"
                      size="sm"
                      disabled={busy || plugin.enabled || plugin.estimates_read}
                      aria-describedby={!plugin.enabled && plugin.estimates_read ? removeWhyId : undefined}
                      onClick={() => setRemoving(true)}
                    >
                      {settingsPluginsSectionRemove()}
                    </Button>
                    {!removed && (
                      <Button variant="danger" size="sm" disabled={busy} onClick={() => setUninstalling(true)}>
                        {settingsPluginSettingsUninstall()}
                      </Button>
                    )}
                  </div>
                </Card>

                {actions.turningOn && (
                  <TurnOnDialog plugin={actions.turningOn} onCancel={actions.cancelTurnOn} onTurnOn={actions.confirmTurnOn} />
                )}
                {actions.approving && (
                  <ApproveDialog
                    detail={actions.approving.detail}
                    andTurnOn={actions.approving.andTurnOn}
                    onCancel={actions.cancelApproval}
                    onApprove={(robots) => actions.approving && actions.approve(actions.approving, robots)}
                  />
                )}
                {actions.reviewingRobots && (
                  <RobotsDialog
                    plugin={actions.reviewingRobots}
                    onCancel={actions.cancelRobots}
                    onAllow={(robots) => actions.reviewingRobots && void actions.setRobots(actions.reviewingRobots, robots)}
                  />
                )}
                {removing && (
                  <RemoveDataDialog
                    plugin={plugin}
                    onCancel={() => setRemoving(false)}
                    onRemove={(typed) => { setRemoving(false); void actions.removeData(plugin, typed); }}
                  />
                )}
                {uninstalling && (
                  <UninstallDialog
                    plugin={plugin}
                    onCancel={() => setUninstalling(false)}
                    onUninstall={() => { setUninstalling(false); void actions.uninstall(plugin); }}
                  />
                )}
              </>
            );
          }}
        </AsyncBoundary>
      )}
    </div>
  );
}
