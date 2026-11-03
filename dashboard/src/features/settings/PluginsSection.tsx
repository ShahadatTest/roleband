import { useCallback, useEffect, useId, useState } from "react";
import { useNavigate } from "react-router-dom";
import { PluginView, PluginsResponse, api } from "../../api";
import { useSyncEpoch } from "../../context/SyncState";
import { useAsyncResource, useRefetchOn } from "../../hooks/useAsyncResource";
import { AsyncBoundary, Badge, Button, EmptyState, Icon, SearchField, Switch } from "../../ui";
import { Card, CardMessage, CardRow } from "../../ui/Card";
import { Content } from "../../ui/Content";
import {
  settingsPluginsSectionComingSoon,
  settingsPluginsSectionComingSoonNote,
  settingsPluginsSectionIntro,
  settingsPluginsSectionLoadFailed,
  settingsPluginsSectionLoading,
  settingsPluginsSectionMore,
  settingsPluginsSectionMoreNote,
  settingsPluginsSectionMoved,
  settingsPluginsSectionNoMatch,
  settingsPluginsSectionNone,
  settingsPluginsSectionOnCount,
  settingsPluginsSectionOpenSettings,
  settingsPluginsSectionPending,
  settingsPluginsSectionRefreshFailed,
  settingsPluginsSectionSearch,
  settingsPluginsSectionStart,
  settingsPluginsSectionStartName,
  settingsPluginsSectionState,
  settingsPluginsSectionTitle,
  settingsPluginsSectionTurnOnFirst,
  settingsPluginsSectionUse,
} from "../../copy/gen/settings";
import { ApproveDialog, TurnOnDialog } from "./PluginDialogs";
import { PluginDescription, RunWords } from "./PluginOwnWords";
import { FACTS_JOIN, RowState, ago, rowState, runnable, slotWord, timingRest } from "./pluginWords";
import { noticeText, usePluginActions } from "./usePluginActions";
import "./PluginsSection.css";

/* Settings > Plugins. Optional add-ons that add to what RoleBand can do;
   each says what it does in its own words. Plugins are a preview: while the
   API says they are not available (`ROLEBAND_PLUGINS` off), a Coming soon row
   stands where the list and its search would be, and More plugins stays as it is.

   Each plugin is one kit row (`ui/Card` `CardRow`, as
   Privacy's and Data retention's): its switch (on = its data is used) left of
   its name and what it does, both in the plugin's own words
   (`PluginOwnWords`), its last update (how it ended and when, then what it
   did as the plugin tells it), how many companies its own data answers for
   and when it next updates, then Start (named by its plugin for a screen reader: every row has
   one) and a gear that opens its own settings (`/settings/plugins/:id`:
   schedule, Pause, history, remove data, uninstall). Search filters the
   installed plugins. Install is on the command line: More plugins shows the
   command, and no install control.

   The switch reads `enabled`, the user's choice, not `state`: an update that
   lapsed a plugin's approval leaves it on and waiting, and turning it off
   needs no approval. Start and the data need `state === "enabled"`; when Start
   cannot run, the reason is on screen beside it, never only in a tooltip.
   Pause lives on the plugin's settings, on its Next update line, with one
   meaning there: hold updates (and stop the one running).

   It watches `/api/status.reference` through the sync epoch: when estimates
   move (a plugin turned on or off, a clean update), the list refetches; while a
   plugin updates, a Start waits for its run, or estimates are moving it polls.
   What estimates did is said under the intro, above the list. */

const POLL_MS = 3_000;

/** What installs a plugin, typed in RoleBand's folder: code the person copies,
 *  never copy (`data-copy="code"`). `scripts.plugin` resolves from `backend/`
 *  only, hence the `cd`. */
const INSTALL_COMMAND = /* not copy */ "cd backend && .venv/bin/python -m scripts.plugin install <plugin-folder>";

/** The states a row's badge says: only those the switch and the update line
 *  do not already say. "On" beside a switch that is on is the same fact twice. */
const BADGE_TONE: Partial<Record<RowState, "neutral" | "info" | "warning">> = {
  needs_approval: "warning",
  updating: "info",
  removed: "neutral",
};

/** Does the query name this plugin: its name, id, what it brings, or its source. */
function matches(plugin: PluginView, query: string): boolean {
  const q = query.trim().toLocaleLowerCase();
  if (!q) return true;
  const haystack = [plugin.name, plugin.id, plugin.attribution ?? "", ...plugin.slots.map(slotWord)];
  return haystack.some((text) => text.toLocaleLowerCase().includes(q));
}

function PluginRow({
  plugin,
  busy,
  starting,
  error,
  onToggle,
  onStart,
  onOpen,
}: {
  plugin: PluginView;
  busy: boolean;
  starting: boolean;
  error: string | null;
  onToggle: (next: boolean) => void;
  onStart: () => void;
  onOpen: () => void;
}) {
  const state = rowState(plugin, starting);
  const removed = state === "removed";
  const whyId = useId();
  const tone = BADGE_TONE[state];
  const badge = tone && <Badge size="sm" tone={tone}>{settingsPluginsSectionState({ state })}</Badge>;
  const canRun = runnable(plugin);
  return (
    <>
      <CardRow
        testId={`plugin-row-${plugin.id}`}
        toggle={(slot) => (
          <Switch
            {...slot}
            checked={plugin.enabled}
            onChange={onToggle}
            disabled={busy || removed}
            label={settingsPluginsSectionUse({ name: plugin.name })}
          />
        )}
        title={<Content text={plugin.name} />}
        description={<span data-testid={`plugin-answers-${plugin.id}`}><PluginDescription plugin={plugin} /></span>}
        facts={
          <span data-testid={`plugin-facts-${plugin.id}`}>
            <RunWords run={plugin.last_run} starting={starting && !plugin.running} />
            {timingRest(plugin, starting).map((fact) => FACTS_JOIN + fact).join("")}
          </span>
        }
        trailing={
          <>
            {/* Why Start waits, said where it waits: on but unapproved is the
                badge itself; off is a line of its own. */}
            {!removed && !canRun && plugin.enabled ? <span id={whyId}>{badge}</span> : badge}
            {!removed && !canRun && !plugin.enabled && (
              <span id={whyId} className="plugins-why">{settingsPluginsSectionTurnOnFirst()}</span>
            )}
            {!removed && (
              <Button
                size="sm"
                disabled={busy || starting || plugin.running || !canRun}
                // Every row has a Start: its name says whose (the visible word leads it).
                aria-label={settingsPluginsSectionStartName({ name: plugin.name })}
                aria-describedby={canRun ? undefined : whyId}
                onClick={onStart}
              >
                <Icon name="play" size={14} />
                {settingsPluginsSectionStart()}
              </Button>
            )}
            <Button
              variant="icon"
              size="sm"
              aria-label={settingsPluginsSectionOpenSettings({ name: plugin.name })}
              onClick={onOpen}
            >
              <Icon name="gear" size={16} />
            </Button>
          </>
        }
      />
      {error && <CardMessage role="alert">{error}</CardMessage>}
    </>
  );
}

function ReferenceLine({ reference }: { reference: PluginsResponse["reference"] }) {
  if (reference.target_fp !== null && reference.pending_jobs > 0) {
    return (
      <CardMessage tone="info" role="status" className="plugins-reference">
        {settingsPluginsSectionPending({ pending: reference.pending_jobs })}
      </CardMessage>
    );
  }
  const change = reference.last_change;
  if (!change || change.moved + change.gained + change.lost === 0) return null;
  return (
    <CardMessage tone="info" role="note" className="plugins-reference">
      {settingsPluginsSectionMoved({
        moved: change.moved + change.gained + change.lost,
        companies: change.companies,
        when: ago(change.at),
      })}
    </CardMessage>
  );
}

export function PluginsSection() {
  const plugins = useAsyncResource<PluginsResponse>(() => api.plugins(), []);
  const { referenceVersion } = useSyncEpoch();
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const { refresh, mutate } = plugins;
  const adopt = useCallback((plugin: PluginView) => mutate((current) => current && {
    ...current, plugins: current.plugins.map((p) => (p.id === plugin.id ? plugin : p)),
  }), [mutate]);
  const actions = usePluginActions({ refresh: () => refresh({ preserveData: true }), adopt });

  // Estimates moved somewhere (a status poll saw a new reference change). Only
  // a change: the mount already fetched.
  useRefetchOn(referenceVersion, refresh);

  // Poll while something is moving: an update running or starting, estimates catching up.
  const moving = Boolean(
    plugins.data?.available && (plugins.data.plugins.some((p) => p.running || actions.isStarting(p))
      || plugins.data.reference.target_fp !== null),
  );
  useEffect(() => {
    if (!moving) return;
    const id = window.setInterval(() => { void refresh({ preserveData: true }); }, POLL_MS);
    return () => window.clearInterval(id);
  }, [moving, refresh]);

  const available = plugins.data?.available ?? false;
  const installed = available ? plugins.data?.plugins ?? [] : [];
  const shown = installed.filter((p) => matches(p, query));
  const live = installed.filter((p) => p.state !== "removed");
  const on = live.filter((p) => p.enabled).length;

  return (
    <Card
      title={settingsPluginsSectionTitle()}
      intro={settingsPluginsSectionIntro()}
      meta={live.length > 0
        ? <span className="plugins-count" data-selection="chrome">{settingsPluginsSectionOnCount({ on, total: live.length })}</span>
        : undefined}
    >
      {/* What estimates did, under the intro that says plugins move them:
          above the list, where the change it reports comes from. */}
      {available && plugins.data && <ReferenceLine reference={plugins.data.reference} />}
      {available && (
        <SearchField
          className="plugins-search"
          label={settingsPluginsSectionSearch()}
          placeholder={settingsPluginsSectionSearch()}
          value={query}
          onChange={setQuery}
        />
      )}
      <AsyncBoundary
        resource={plugins}
        loading={settingsPluginsSectionLoading()}
        failed={settingsPluginsSectionLoadFailed()}
        refreshFailed={settingsPluginsSectionRefreshFailed()}
      >
        {(data) => (
          <>
            {!data.available ? (
              <CardRow
                testId="plugins-coming-soon"
                className="plugins-soon"
                title={<Badge tone="info">{settingsPluginsSectionComingSoon()}</Badge>}
                description={settingsPluginsSectionComingSoonNote()}
              />
            ) : data.plugins.length === 0 ? (
              <EmptyState variant="inline" title={settingsPluginsSectionNone()} />
            ) : shown.length === 0 ? (
              <EmptyState variant="inline" title={settingsPluginsSectionNoMatch()} />
            ) : (
              shown.map((plugin) => (
                <PluginRow
                  key={plugin.id}
                  plugin={plugin}
                  busy={actions.busy.has(plugin.id)}
                  starting={actions.isStarting(plugin)}
                  error={actions.errorFor(plugin.id)}
                  onToggle={(next) => actions.toggle(plugin, next)}
                  onStart={() => void actions.start(plugin)}
                  onOpen={() => navigate(`/settings/plugins/${encodeURIComponent(plugin.id)}`)}
                />
              ))
            )}
            {/* Where plugins to add will be found: a statement of what is
                coming, and how to install one meanwhile. No install control.
                Under plugin rows it starts where their names start, past the
                switch column, so the list has one left edge. */}
            <CardRow
              className={shown.length > 0 ? "plugins-more is-under-rows" : "plugins-more"}
              title={settingsPluginsSectionMore()}
              description={settingsPluginsSectionMoreNote()}
            />
            <pre className={shown.length > 0 ? "plugins-install is-under-rows" : "plugins-install"} data-copy="code">
              {INSTALL_COMMAND}
            </pre>
          </>
        )}
      </AsyncBoundary>

      {actions.notice && <CardMessage tone="info" role="status">{noticeText(actions.notice)}</CardMessage>}

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
    </Card>
  );
}
