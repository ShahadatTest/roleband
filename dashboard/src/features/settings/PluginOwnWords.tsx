import type { PluginRunView, PluginView } from "../../api";
import { settingsPluginSettingsRunSummary } from "../../copy/gen/settings";
import { Content } from "../../ui/Content";
import { Msg } from "../../ui/Msg";
import { bringsLine, ownSummary, runLine } from "./pluginWords";

/* Where a plugin speaks for itself on both plugin screens: what it does
   (manifest `description`) and what a run did (`ctx.summary`). Its words are
   third-party text, shown as written; RoleBand's own words stand in only for
   a plugin that says nothing. */

/** What the plugin does, in its own words; else what it brings, by kind of data. */
export function PluginDescription({ plugin }: { plugin: PluginView }) {
  return plugin.description ? <Content text={plugin.description} /> : <>{bringsLine(plugin)}</>;
}

/** How a run ended and when (the host's account), then what it did in the
 *  plugin's own words. `starting`: Start was pressed and its run has not shown up yet. */
export function RunWords({ run, starting = false }: { run: PluginRunView | null; starting?: boolean }) {
  const line = runLine(run, starting);
  const summary = ownSummary(run, starting);
  if (!summary) return <>{line}</>;
  return <Msg of={settingsPluginSettingsRunSummary} args={{ run: line }} elems={{ summary: <Content text={summary} /> }} />;
}
