/* A bounded, in-memory record of client-side failures.
 *
 * A failed route chunk can unmount the whole app, and without this nothing
 * anywhere would tell anyone it happened. An error boundary that only paints a retry keeps
 * it that way — the user sees a card, and the failure leaves no trace.
 *
 * This is deliberately NOT a reporting service. RoleBand is local-first and
 * single-user (docs/architecture.md), so the useful destination is the machine
 * already in front of the person: the ring buffer below, read by the
 * notification diagnostics panel. This buffer never leaves the browser. A user
 * who shares crash reports has the same errors sent, cleaned, by the usage
 * library's own exception capture (`diagnostics/sharing.ts`, docs/usage-data.md), which is a
 * separate path this file does not feed.
 *
 * Bounded on purpose. An unbounded log of render errors is itself a leak, and
 * a render loop can produce thousands per second.
 */

export type ClientErrorSource = "route" | "overlay" | "window" | "promise";

export type ClientErrorRecord = {
  at: string;
  source: ClientErrorSource;
  message: string;
  stack?: string;
  /** React's component stack, when the report came from an error boundary. */
  componentStack?: string;
};

const CAP = 50;
const buffer: ClientErrorRecord[] = [];
const listeners = new Set<(records: ClientErrorRecord[]) => void>();

export function recordClientError(
  error: unknown,
  source: ClientErrorSource,
  componentStack?: string | null,
): void {
  const err = error instanceof Error ? error : new Error(String(error));
  buffer.push({
    at: new Date().toISOString(),
    source,
    message: err.message,
    stack: err.stack,
    componentStack: componentStack ?? undefined,
  });
  // Oldest out. The newest failure is the one being diagnosed.
  if (buffer.length > CAP) buffer.splice(0, buffer.length - CAP);
  for (const listener of listeners) listener([...buffer]);
}

/** Newest first — the order anyone diagnosing reads in. */
export function clientErrors(): ClientErrorRecord[] {
  return [...buffer].reverse();
}

export function subscribeClientErrors(fn: (records: ClientErrorRecord[]) => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

/** Test seam. Not called by the app. */
export function clearClientErrors(): void {
  buffer.length = 0;
  for (const listener of listeners) listener([]);
}

/* The two failures no error boundary can see: a throw outside React's render
 * phase (an event handler, a timer) and an unhandled promise rejection — which
 * is what a bare `api.x().then(...)` with no `.catch` produces. Installed once
 * from main.tsx. */
export function installGlobalErrorCapture(target: Window = window): () => void {
  const onError = (event: ErrorEvent) => recordClientError(event.error ?? event.message, "window");
  const onRejection = (event: PromiseRejectionEvent) => recordClientError(event.reason, "promise");
  target.addEventListener("error", onError);
  target.addEventListener("unhandledrejection", onRejection);
  return () => {
    target.removeEventListener("error", onError);
    target.removeEventListener("unhandledrejection", onRejection);
  };
}
