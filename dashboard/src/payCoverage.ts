/* Who answers pay app-wide, and the companies it has read: one read,
   `GET /api/pay-coverage`, shared by every screen that shows a posting's pay so
   a company the plugin has not read says "not covered", never a bare dash.
   Coverage moves only when a switch lands (the applied set), so the read is kept
   per reference version and re-read when the version moves. Its own module so
   it loads with the screens that show pay, never the shell. */
import { useEffect, useState } from "react";
import { api } from "./api";
import type { PayCoverage } from "./api/plugins";
import { usePayByPlugin, useReferenceVersion } from "./context/SyncState";

/** A plugin answering pay and the companies it has read; null while ours answers. */
export interface PayCover {
  plugin: string;
  name: string;
  companies: ReadonlySet<string>;
}

const toCover = (wire: PayCoverage): PayCover | null =>
  wire.plugin ? { plugin: wire.plugin, name: wire.plugin_name ?? wire.plugin, companies: new Set(wire.companies) } : null;

let cached: { version: number; cover: PayCover | null } | null = null;
let pending: { version: number; read: Promise<PayCover | null> } | null = null;

function read(version: number): Promise<PayCover | null> {
  if (pending?.version === version) return pending.read;
  // Through a resolved promise, so a client without the call (a test's partial
  // mock) fails the read, not the render; a failed read is tried again by the
  // next screen that asks.
  const promise = Promise.resolve().then(() => api.payCoverage()).then(toCover).then(
    (cover) => {
      if (pending?.version === version) cached = { version, cover };
      return cover;
    },
    (caught: unknown) => {
      if (pending?.version === version) pending = null;
      throw caught;
    },
  );
  pending = { version, read: promise };
  return promise;
}

/** The plugin answering pay and what it has read, or null (ours answers, or not
 *  read yet: a failed read says nothing rather than "not covered" everywhere).
 *  Read only while the status says a plugin answers pay, so ours costs nothing. */
export function usePayCoverage(): PayCover | null {
  const version = useReferenceVersion();
  const byPlugin = usePayByPlugin();
  const [cover, setCover] = useState<PayCover | null>(() => (cached?.version === version ? cached.cover : null));
  useEffect(() => {
    if (!byPlugin) {
      setCover(null);
      return;
    }
    if (cached?.version === version) {
      setCover(cached.cover);
      return;
    }
    let live = true;
    read(version).then((next) => { if (live) setCover(next); }, () => {});
    return () => { live = false; };
  }, [version, byPlugin]);
  return byPlugin ? cover : null;
}
