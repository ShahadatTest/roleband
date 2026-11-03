import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation, useSearchParams } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";
import { readEntry, writeEntry } from "../hooks/filterMemory";
import { useRememberedParams } from "./useRememberedParams";

/* A screen whose lenses ARE the address. They already survive a reload; what
 * they never survived is leaving and coming back, because the nav rail lands
 * on a bare URL. */

const KEYS = ["status", "category"] as const;

function Harness() {
  useRememberedParams("spec", KEYS);
  const [params, setParams] = useSearchParams();
  const loc = useLocation();
  return (
    <>
      <div data-testid="search">{loc.search}</div>
      <div data-testid="status">{params.get("status") ?? ""}</div>
      <button
        onClick={() =>
          setParams(
            (prev) => {
              const next = new URLSearchParams(prev);
              next.set("status", "unread");
              next.append("category", "sync_failed");
              return next;
            },
            { replace: true },
          )
        }
      >
        narrow
      </button>
      <button
        onClick={() =>
          setParams(
            (prev) => {
              const next = new URLSearchParams(prev);
              for (const key of KEYS) next.delete(key);
              return next;
            },
            { replace: true },
          )
        }
      >
        reset
      </button>
    </>
  );
}

const arriveAt = (route: string) =>
  render(
    <MemoryRouter initialEntries={[route]}>
      <Harness />
    </MemoryRouter>,
  );

beforeEach(() => localStorage.clear());

describe("remembered query params", () => {
  it("records the lenses a reader chose, and puts them back on a bare address", async () => {
    const user = userEvent.setup();
    const first = arriveAt("/notifications");
    await user.click(screen.getByText("narrow"));
    await waitFor(() =>
      expect(readEntry("spec:params")).toEqual({ status: ["unread"], category: ["sync_failed"] }),
    );
    first.unmount();

    // The nav rail's own link: no query at all.
    arriveAt("/notifications");
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("unread"));
    expect(screen.getByTestId("search").textContent).toContain("category=sync_failed");
  });

  it("leaves an address that names a lens alone, memory or no memory", async () => {
    writeEntry("spec:params", { status: ["unread"], category: ["sync_failed"] });
    arriveAt("/notifications?status=all");
    // A link, a deep link, Back: an explicit choice made just now outranks one
    // made last night, and nothing is merged in beside it.
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("all"));
    expect(screen.getByTestId("search").textContent).not.toContain("category");
  });

  it("carries params it does not own through a restore untouched", async () => {
    writeEntry("spec:params", { status: ["unread"] });
    arriveAt("/notifications?tab=digest");
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("unread"));
    expect(screen.getByTestId("search").textContent).toContain("tab=digest");
  });

  it("remembers a reset as a choice, so it survives the trip too", async () => {
    const user = userEvent.setup();
    const first = arriveAt("/notifications");
    await user.click(screen.getByText("narrow"));
    await waitFor(() => expect(readEntry("spec:params")).not.toEqual({}));
    // Reset all is the reader saying "show me everything". Coming back to a
    // list still narrowed by what they just cleared would be the worst of both.
    await user.click(screen.getByText("reset"));
    await waitFor(() => expect(readEntry("spec:params")).toEqual({}));
    first.unmount();

    arriveAt("/notifications");
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent(""));
  });

  it("does not erase memory with the bare address it is in the middle of replacing", async () => {
    // The restore and the write both run in the mount commit, and the restore's
    // navigation has not landed yet — so the naive write half reads the bare
    // URL and stores `{}`, wiping exactly what it was restoring.
    writeEntry("spec:params", { status: ["unread"] });
    arriveAt("/notifications");
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("unread"));
    expect(readEntry("spec:params")).toEqual({ status: ["unread"] });
  });
});
