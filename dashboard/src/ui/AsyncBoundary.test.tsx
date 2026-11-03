import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { useAsyncResource } from "../hooks/useAsyncResource";
import { msg } from "../test/msg";
import { AsyncBoundary } from "./AsyncBoundary";

function makeResource<T>(
  overrides: { data?: T | null; error?: Error | null; loading?: boolean; retry?: () => void } = {},
): { data: T | null; error: Error | null; loading: boolean; retry: () => void } {
  return {
    data: overrides.data ?? null,
    error: overrides.error ?? null,
    loading: overrides.loading ?? false,
    retry: overrides.retry ?? vi.fn(),
  };
}

/** A caller's whole messages, as a screen passes them from its catalog. */
const JOBS = {
  loading: "Loading jobs…",
  failed: "Couldn't load jobs",
  emptyTitle: "No jobs yet",
  refreshFailed: "Couldn't refresh jobs. Showing the last result.",
};

describe("AsyncBoundary", () => {
  it("shows the default loading state while loading", () => {
    render(
      <AsyncBoundary resource={makeResource({ loading: true })} {...JOBS}>
        {() => <p>ready</p>}
      </AsyncBoundary>,
    );
    expect(screen.getByRole("status")).toHaveTextContent("Loading jobs…");
    expect(screen.queryByText("ready")).not.toBeInTheDocument();
  });

  it("renders a custom skeleton slot instead of the spinner", () => {
    render(
      <AsyncBoundary
        resource={makeResource({ loading: true })}
        {...JOBS}
        skeleton={<div data-testid="skeleton-rows" />}
      >
        {() => <p>ready</p>}
      </AsyncBoundary>,
    );
    expect(screen.getByTestId("skeleton-rows")).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("renders the error state with a working retry callback", async () => {
    const retry = vi.fn();
    render(
      <AsyncBoundary
        resource={makeResource({ error: new Error("boom"), retry })}
        {...JOBS}
      >
        {() => <p>ready</p>}
      </AsyncBoundary>,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Couldn't load jobs");
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(retry).toHaveBeenCalledTimes(1);
  });

  it("passes loaded data to the ready render prop", () => {
    render(
      <AsyncBoundary resource={makeResource({ data: { title: "Staff PM" } })} {...JOBS}>
        {(data) => <p>{data.title}</p>}
      </AsyncBoundary>,
    );
    expect(screen.getByText("Staff PM")).toBeInTheDocument();
  });

  it("renders the empty slot when isEmpty says so", () => {
    render(
      <AsyncBoundary
        resource={makeResource({ data: [] as string[] })}
        {...JOBS}
        isEmpty={(rows) => rows.length === 0}
        empty={<p>Nothing tracked yet.</p>}
      >
        {(rows) => <p>{rows.length} rows</p>}
      </AsyncBoundary>,
    );
    expect(screen.getByText("Nothing tracked yet.")).toBeInTheDocument();
  });

  it("falls back to the radar EmptyState when no empty slot is given", () => {
    render(
      <AsyncBoundary
        resource={makeResource({ data: [] as string[] })}
        {...JOBS}
        isEmpty={(rows) => rows.length === 0}
      >
        {(rows) => <p>{rows.length} rows</p>}
      </AsyncBoundary>,
    );
    expect(screen.getByText("No jobs yet")).toBeInTheDocument();
  });

  it("drives loading -> error -> retry -> ready against a real useAsyncResource", async () => {
    // Fake resource: first request rejects, the retry resolves.
    let calls = 0;
    let reject!: (e: Error) => void;
    let resolve!: (v: string[]) => void;
    const request = vi.fn(() => {
      calls += 1;
      return new Promise<string[]>((res, rej) => {
        resolve = res;
        reject = rej;
      });
    });

    function Screen() {
      const resource = useAsyncResource(request, []);
      return (
        <AsyncBoundary resource={resource} loading="Loading companies…">
          {(rows) => <p>{rows.join(", ")}</p>}
        </AsyncBoundary>
      );
    }

    render(<Screen />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading companies…");

    await act(async () => reject(new Error("api down")));
    expect(screen.getByRole("alert")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(calls).toBe(2);

    await act(async () => resolve(["Google", "Anthropic"]));
    expect(screen.getByText("Google, Anthropic")).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("treats a resolved-null payload as empty, not as a failed request", () => {
    /* A resource that legitimately resolves to null is EMPTY, not failed.
       "Couldn't load" over an Error the boundary FABRICATED tells the user to
       retry a request that already succeeded, and hides a real empty state
       behind a false failure. */
    render(
      <AsyncBoundary resource={makeResource<{ n: number }>({ data: null })} {...JOBS}>
        {() => <p>ready</p>}
      </AsyncBoundary>,
    );
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByText(/couldn.t load/i)).not.toBeInTheDocument();
    expect(screen.getByText("No jobs yet")).toBeInTheDocument();
  });

  it("still reports a real error, and does not call it empty", () => {
    // The other half: narrowing the null case must not swallow a genuine failure.
    render(
      <AsyncBoundary
        resource={makeResource<{ n: number }>({ error: new Error("nope") })}
        {...JOBS}
      >
        {() => <p>ready</p>}
      </AsyncBoundary>,
    );
    expect(screen.queryByText("No jobs yet")).not.toBeInTheDocument();
    expect(screen.getByText(/couldn.t load jobs/i)).toBeInTheDocument();
  });

  it("says so when a background refresh failed, without throwing the data away", () => {
    /* `useAsyncResource` routes a failed REFRESH to `refreshError` rather than
       `error`, deliberately: a poll that fails should not blank a working
       screen. Unrendered, a failing poll leaves a frozen list looking freshly
       loaded, which is the worst of both: stale AND confident. */
    render(
      <AsyncBoundary
        resource={{
          ...makeResource<{ n: number }>({ data: { n: 1 } }),
          refreshError: new Error("offline"),
        }}
        {...JOBS}
      >
        {(d) => <p>rows: {d.n}</p>}
      </AsyncBoundary>,
    );
    // The data stays on screen — that is the point of refreshError existing.
    expect(screen.getByText(/rows: 1/)).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(/couldn.t refresh jobs/i);
    expect(screen.getByRole("button", { name: /try again/i })).toBeInTheDocument();
  });

  it("stays quiet when the refresh succeeded", () => {
    render(
      <AsyncBoundary resource={makeResource<{ n: number }>({ data: { n: 1 } })} {...JOBS}>
        {(d) => <p>rows: {d.n}</p>}
      </AsyncBoundary>,
    );
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});

/* Whole messages: each state says exactly the catalog string it is handed, so
   a translation is one sentence with its own grammar, never a frame around a
   noun from another language. */
describe("AsyncBoundary with whole messages", () => {
  const messages = {
    loading: "Loading the ledger…",
    failed: "Couldn't load the ledger",
    emptyTitle: "No ledger rows yet",
    refreshFailed: "Couldn't refresh the ledger. Showing the last result.",
  };

  it("says each state as the message it was given, and nothing built around it", () => {
    const { rerender } = render(
      <AsyncBoundary resource={makeResource({ loading: true })} {...messages}>{() => <p>ready</p>}</AsyncBoundary>,
    );
    expect(screen.getByRole("status")).toHaveTextContent(new RegExp(`^\\s*${messages.loading}$`));

    rerender(<AsyncBoundary resource={makeResource({ error: new Error("boom") })} {...messages}>{() => <p>ready</p>}</AsyncBoundary>);
    expect(screen.getByRole("heading")).toHaveTextContent(new RegExp(`^${messages.failed}$`));

    rerender(
      <AsyncBoundary resource={makeResource({ data: [] as string[] })} isEmpty={(rows) => rows.length === 0} {...messages}>
        {() => <p>ready</p>}
      </AsyncBoundary>,
    );
    expect(screen.getByText(messages.emptyTitle)).toBeInTheDocument();

    rerender(
      <AsyncBoundary resource={{ ...makeResource({ data: ["a"] }), refreshError: new Error("offline") }} {...messages}>
        {(rows) => <p>rows: {rows.length}</p>}
      </AsyncBoundary>,
    );
    expect(screen.getByRole("status")).toHaveTextContent(messages.refreshFailed);
    expect(screen.getByText(/rows: 1/)).toBeInTheDocument();
  });

  it("falls back to whole generic messages when it is given none of its own", () => {
    const { rerender } = render(<AsyncBoundary resource={makeResource({ loading: true })}>{() => <p>ready</p>}</AsyncBoundary>);
    expect(screen.getByRole("status")).toHaveTextContent(msg("ui-loading"));

    rerender(<AsyncBoundary resource={makeResource({ error: new Error("boom") })}>{() => <p>ready</p>}</AsyncBoundary>);
    expect(screen.getByRole("heading")).toHaveTextContent(msg("ui-load-failed"));

    rerender(<AsyncBoundary resource={makeResource({ data: null })}>{() => <p>ready</p>}</AsyncBoundary>);
    expect(screen.getByText(msg("shared-empty"))).toBeInTheDocument();

    rerender(
      <AsyncBoundary resource={{ ...makeResource({ data: ["a"] }), refreshError: new Error("offline") }}>
        {(rows) => <p>rows: {rows.length}</p>}
      </AsyncBoundary>,
    );
    expect(screen.getByRole("status")).toHaveTextContent(msg("shared-refresh-failed"));
    // A legacy frame with nothing in it ("Loading …", "No  yet") is the failure this guards.
    expect(document.body).not.toHaveTextContent(/Loading …|No\s+yet|refresh \./);
  });
});
