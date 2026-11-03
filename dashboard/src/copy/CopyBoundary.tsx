import { Fragment, useSyncExternalStore, type ReactNode } from "react";
import { activeKey, subscribe } from "./runtime";

/** Remounts everything below it when the language or the region changes
 *  (docs/copy.md). Messages are plain functions called
 *  in render, models and label helpers; a remount is what reaches all of them.
 *  Sits directly inside AppProviders, so data, the URL and server state stay. */
export function CopyBoundary({ children }: { children: ReactNode }) {
  const key = useSyncExternalStore(subscribe, activeKey);
  return <Fragment key={key}>{children}</Fragment>;
}
