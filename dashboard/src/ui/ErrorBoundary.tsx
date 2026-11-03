import { Component, type ErrorInfo, type ReactNode } from "react";

/* The app's only error boundary, and the reason it exists is lazy routes.
 *
 * A lazy route makes each screen a NETWORK dependency, and `<Suspense>` — the
 * only thing wrapped around them — handles a pending import, never a rejected
 * one. Without this, a dropped connection during navigation throws through the
 * whole tree and unmounts the root: a white page, from a two-second blip.
 *
 * A boundary is a class because there is no hook form; `getDerivedStateFromError`
 * is the only render-phase catch React offers.
 *
 * There is deliberately no soft `retry()`: for the failure this exists to catch
 * — a dead route chunk — clearing render state recovers nothing, because the
 * browser's module map has already recorded the fetch failure for the lifetime
 * of the document (see App.tsx). The reset that DOES work is
 * remounting on navigation, which the caller gets with a `key`. */
export class ErrorBoundary extends Component<
  {
    children: ReactNode;
    fallback: (error: Error) => ReactNode;
    /** Reported for telemetry. Must not throw. */
    onError?: (error: Error, info: ErrorInfo) => void;
  },
  { error: Error | null }
> {
  state: { error: Error | null } = { error: null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    this.props.onError?.(error, info);
  }

  render() {
    const { error } = this.state;
    if (error) return <>{this.props.fallback(error)}</>;
    return <>{this.props.children}</>;
  }
}
