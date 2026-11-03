import { Content } from "../../ui/Content";
import { sourceName } from "../../copy/vocab";

/** Per source the dashboard's catalog cannot name (a plugin's, and the ones it
 *  adopts), the name the profile route sends (`source_names`). */
export type SourceNames = Readonly<Record<string, string>>;

/** A claim's source as text, for an accessible name: ours from the catalog,
 *  a plugin's as the plugin names itself. */
export function sourceText(source: string, names: SourceNames): string {
  return names[source] ?? sourceName(source);
}

/** A claim's source on screen: ours from the catalog, a plugin's as written
 *  (`ui/Content`: third-party text RoleBand did not write or translate). */
export function SourceLabel({ source, names }: { source: string; names: SourceNames }) {
  const own = names[source];
  return own ? <Content text={own} /> : <>{sourceName(source)}</>;
}
