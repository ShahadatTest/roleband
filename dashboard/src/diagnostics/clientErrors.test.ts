import { afterEach, describe, expect, it, vi } from "vitest";
import {
  clearClientErrors,
  clientErrors,
  installGlobalErrorCapture,
  recordClientError,
  subscribeClientErrors,
} from "./clientErrors";

afterEach(() => clearClientErrors());

describe("client error buffer", () => {
  it("records a failure with its source and keeps the newest first", () => {
    recordClientError(new Error("older"), "route");
    recordClientError(new Error("newer"), "overlay");
    const [first, second] = clientErrors();
    expect(first.message).toBe("newer");
    expect(first.source).toBe("overlay");
    expect(second.message).toBe("older");
    expect(Date.parse(first.at)).not.toBeNaN();
  });

  it("keeps a non-Error throw readable instead of dropping it", () => {
    // A rejected fetch promise often carries a string or a Response, not an
    // Error; losing those is how a diagnostics panel ends up empty during the
    // exact incident it exists for.
    recordClientError("plain string failure", "promise");
    expect(clientErrors()[0].message).toBe("plain string failure");
  });

  it("is BOUNDED, so a render loop cannot exhaust memory through it", () => {
    for (let i = 0; i < 120; i += 1) recordClientError(new Error(`e${i}`), "route");
    const records = clientErrors();
    expect(records).toHaveLength(50);
    // The 50 kept are the most recent, not the first 50 seen.
    expect(records[0].message).toBe("e119");
    expect(records[records.length - 1].message).toBe("e70");
  });

  it("notifies subscribers and stops after unsubscribe", () => {
    const seen = vi.fn();
    const off = subscribeClientErrors(seen);
    recordClientError(new Error("one"), "route");
    expect(seen).toHaveBeenCalledTimes(1);
    off();
    recordClientError(new Error("two"), "route");
    expect(seen).toHaveBeenCalledTimes(1);
  });

  /* An `error` event that reaches the end of its dispatch uncancelled is a
     REPORTED error: jsdom escalates it, vitest records it as an unhandled
     error, and the RUN exits 1 while every test still passes. The capture
     listener must not cancel (an app has no business suppressing the browser's
     own reporting of an error it merely observed), so the test cancels for it.
     A second listener does not stop the first: `preventDefault` marks the
     event, it does not halt propagation. */
  const dispatchWindowError = (error: Error) => {
    const cancel = (event: Event) => event.preventDefault();
    window.addEventListener("error", cancel);
    try {
      window.dispatchEvent(
        new ErrorEvent("error", { error, message: error.message, cancelable: true }),
      );
    } finally {
      window.removeEventListener("error", cancel);
    }
  };

  it("captures the two failures no error boundary can see", () => {
    // A boundary catches render-phase throws only. An event-handler throw and
    // an unhandled rejection — which is what a bare `api.x().then()` with no
    // `.catch` produces — bypass it entirely.
    const uninstall = installGlobalErrorCapture(window);

    dispatchWindowError(new Error("handler blew up"));
    const rejection = new Event("unhandledrejection") as Event & { reason?: unknown };
    rejection.reason = new Error("nobody caught this");
    window.dispatchEvent(rejection);

    expect(clientErrors().map((r) => [r.source, r.message])).toEqual([
      ["promise", "nobody caught this"],
      ["window", "handler blew up"],
    ]);

    uninstall();
    dispatchWindowError(new Error("after uninstall"));
    expect(clientErrors()).toHaveLength(2);
  });
});
