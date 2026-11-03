import { msg } from "../../test/msg";
import { ApiError } from "../../api/transport";
import { act, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { CompanyDiscoveryState, TrackedCompany } from "../../api";
import { api } from "../../api";
import { statsFixture, statusFixture } from "../../test/fixtures";
import { AppProviders } from "../../context/AppProviders";
import { ToastProvider } from "../../ui/Toast";
import { CompaniesDataProvider, useCompanies, useCompaniesSync } from "./CompaniesData";

/* Every write this register makes, and what happens when they overlap.
 *
 * Neither control is disabled while its write is in flight — only the row's
 * `aria-busy` moves — so a second click during one is an ordinary interaction,
 * and the value it sends is computed from the row, which still shows the
 * pre-write state. Two writes in the air and the state the install keeps is
 * decided by which reply the server handled last.
 *
 * TWO shapes, which is the whole reason there is a queue and not a chain. The
 * eye PATCHes one row, so two rows must not wait on each other. The switch
 * PUTs one change but is answered with the WHOLE roster, which the screen
 * adopts, so it must order against every outstanding write in both directions:
 * the reply carries a `visible` for every company, so a row PATCH that lands
 * beside it is echoed away with nothing left to correct it.
 *
 * So the boundary here HOLDS what it was told, per company AND for the roster,
 * behind a gate the test opens by call index. A call list cannot answer the
 * only question that matters — what the install ended up with. It also snapshots
 * its reply when the request ARRIVES rather than when its gate opens, because
 * that is what makes an overlapping write observable at all: a server reads,
 * then commits, and the echo is fixed by the read.
 */

vi.mock("../../api", () => ({
  api: {
    companyDiscovery: vi.fn(),
    companyOpenCounts: vi.fn(),
    syncTargets: vi.fn(),
    setCompanySelection: vi.fn(),
    addCompany: vi.fn(),
    updateCompany: vi.fn(),
    sync: vi.fn(),
    cancelSync: vi.fn(),
    status: vi.fn(),
    stats: vi.fn(),
    markJobViewed: vi.fn(),
    compareSelection: vi.fn().mockResolvedValue({ job_ids: [] }),
    setCompareSelection: vi.fn((jobIds: number[]) => Promise.resolve({ job_ids: jobIds })),
  },
}));


const company = (slug: string, display: string) => ({
  slug,
  display,
  careers_url: "https://example.com/careers",
  sectors: ["faang"],
  aliases: [],
  connector_state: "live" as const,
  parked_reason: null,
  selectable: true,
  tracked: true,
  enabled: true,
  visible: true,
  builtin: true,
  curated: true, directory: false,
  wall: null,
  consented: false,
  status: "active" as const,
});

const STATE: CompanyDiscoveryState = {
  sectors: [
    {
      slug: "faang",
      
      
      company_count: 2,
      ready_count: 0,
      selected_count: 2,
    },
  ],
  companies: [company("google", "Google"), company("apple", "Apple")],
};

/** A companies endpoint that REMEMBERS each company's visibility and the
    roster, and holds every write at a gate the test opens by call index.
    One gate sequence across both endpoints, so a test can interleave them. */
function statefulCompanies() {
  const stored = new Map<string, boolean>([["google", true], ["apple", true]]);
  const tracked = new Map<string, boolean>([["google", true], ["apple", true]]);
  const sent: { slug: string; visible: boolean }[] = [];
  const roster: { follow: string[]; unfollow: string[] }[] = [];
  let calls = 0;
  const gates: { open: () => void; fail: (reason: Error) => void; waited: Promise<void> }[] = [];
  const gateFor = (index: number) => {
    if (!gates[index]) {
      let open = () => {};
      let fail = (_reason: Error) => {};
      const waited = new Promise<void>((resolve, reject) => {
        open = () => resolve();
        fail = reject;
      });
      gates[index] = { open, fail, waited };
    }
    return gates[index];
  };
  const snapshot = (): CompanyDiscoveryState => ({
    ...STATE,
    companies: STATE.companies.map((row) => ({
      ...row,
      visible: stored.get(row.slug) ?? true,
      enabled: tracked.get(row.slug) ?? true,
    })),
  });

  return {
    sent,
    roster,
    read: (slug: string) => stored.get(slug),
    readTracked: (slug: string) => tracked.get(slug),
    /** A follow from elsewhere (the wider-market scan), unseen by the screen. */
    trackElsewhere: (slug: string, value: boolean) => tracked.set(slug, value),
    discovery: async () => snapshot(),
    update: async (slug: string, patch: { visible?: boolean | null }) => {
      const index = calls++;
      sent.push({ slug, visible: patch.visible as boolean });
      await gateFor(index).waited;
      stored.set(slug, patch.visible as boolean);
      return {} as TrackedCompany;
    },
    /* The roster PUT changes the rows it names and answers with the WHOLE
       discovery state, including a `visible` for every company. The echo is
       read at arrival. */
    setSelection: async (write: { follow: string[]; unfollow: string[] }) => {
      const index = calls++;
      roster.push(write);
      const echo = snapshot();
      await gateFor(index).waited;
      for (const slug of write.follow) tracked.set(slug, true);
      for (const slug of write.unfollow) tracked.set(slug, false);
      return {
        ...echo,
        companies: echo.companies.map((row) => ({ ...row, enabled: tracked.get(row.slug) ?? row.enabled })),
      };
    },
    open: (index: number) => act(async () => { gateFor(index).open(); }),
    fail: (index: number, reason: Error) => act(async () => { gateFor(index).fail(reason); }),
  };
}

/** Renders each company the way a register row does: both targets come from
    the roster in context, so they are the pre-write values while a write is
    still in the air — exactly what the screen passes. Neither control is
    disabled, which is also what the screen does. */
function Probe() {
  const { resource, chosen, busy, failures, toggleVisible, toggleCompany } = useCompanies();
  return (
    <div>
      <span data-testid="error">{failures.map((failure) => failure.text).join(" | ")}</span>
      <span data-testid="busy">{[...busy].sort().join(",")}</span>
      <span data-testid="chosen">{[...chosen].sort().join(",")}</span>
      {(resource.data?.companies ?? []).map((row) => (
        <div key={row.slug}>
          <span data-testid={`visible-${row.slug}`}>{row.visible ? "shown" : "hidden"}</span>
          <button onClick={() => void toggleVisible(row)}>
            {`${row.visible ? "Hide" : "Show"} ${row.display}`}
          </button>
          <button onClick={() => toggleCompany(row)}>
            {`${chosen.has(row.slug) ? "Unfollow" : "Follow"} ${row.display}`}
          </button>
        </div>
      ))}
    </div>
  );
}

let server: ReturnType<typeof statefulCompanies>;

const mount = async () => {
  render(
    <MemoryRouter>
      <AppProviders>
        <ToastProvider>
          <CompaniesDataProvider>
            <Probe />
          </CompaniesDataProvider>
        </ToastProvider>
      </AppProviders>
    </MemoryRouter>,
  );
  await screen.findByText("Hide Google");
};

const click = (name: string) => act(async () => {
  screen.getByRole("button", { name }).click();
});

beforeEach(() => {
  vi.clearAllMocks();
  server = statefulCompanies();
  vi.mocked(api.companyDiscovery).mockImplementation(server.discovery);
  vi.mocked(api.companyOpenCounts).mockResolvedValue({ counts: {}, not_counted: {}, unplaced: {}, unsorted: {}, last_read: {} });
  vi.mocked(api.syncTargets).mockResolvedValue({ companies: [], freshness_max_hours: 26 });
  vi.mocked(api.stats).mockResolvedValue(statsFixture);
  vi.mocked(api.status).mockResolvedValue({ ...statusFixture, running: false, manual_queued: [] });
  vi.mocked(api.updateCompany).mockImplementation(server.update);
  vi.mocked(api.setCompanySelection).mockImplementation(server.setSelection);
});

describe("the register's visibility queue", () => {
  it("holds a second write for one company until the first has settled", async () => {
    await mount();

    await click("Hide Google");
    expect(server.sent).toHaveLength(1);

    // The row still reads `shown`, so this is the same target again — which is
    // what the screen sends, and the point is that it does not DISPATCH yet.
    await click("Hide Google");
    expect(server.sent).toHaveLength(1);

    await server.open(0);
    await waitFor(() => expect(server.sent).toHaveLength(2));
  });

  it("leaves the company at the last value asked for, whichever reply lands first", async () => {
    /* The three clicks a reader needs for two DIFFERENT targets in the air:
       hide (A), hide again while A flies (B), then — once A has landed and the
       row flipped — show (C). B and C disagree, B was asked for first, and with
       both in flight the value stored is whichever reply the server handled
       last. Only a fresh read can see it. */
    await mount();

    await click("Hide Google");
    await click("Hide Google");
    await server.open(0);
    await waitFor(() => expect(screen.getByTestId("visible-google")).toHaveTextContent("hidden"));

    await click("Show Google");

    // The LATER-asked write's door opens FIRST — an unqueued pair would both be
    // in the air by now, and this is the delivery order that loses the newer
    // one. Nothing is dispatched yet under a queue, so the gate simply stands
    // open when that write finally reaches it.
    await server.open(2);
    await server.open(1);
    await waitFor(() => expect(screen.getByTestId("busy")).toHaveTextContent(""));

    expect(server.read("google")).toBe(true);
    expect(screen.getByTestId("visible-google")).toHaveTextContent("shown");
    // The notice is part of the claim, not decoration — it is the only thing on
    // this screen that says what happened. Delivered out of order, the last word
    // belongs to the write the reader abandoned.
    expect(screen.getByText("Google back on your radar.")).toBeInTheDocument();
    expect(screen.queryByText("Google hidden from your radar.")).not.toBeInTheDocument();
  });

  it("keeps the row busy until that company's queue drains", async () => {
    await mount();

    await click("Hide Google");
    await click("Hide Google");
    await server.open(0);
    await waitFor(() => expect(server.sent).toHaveLength(2));

    expect(screen.getByTestId("busy")).toHaveTextContent("google");

    await server.open(1);
    await waitFor(() => expect(screen.getByTestId("busy")).toHaveTextContent(""));
  });

  it("lets another company write while one is held", async () => {
    await mount();

    await click("Hide Google");
    await click("Hide Apple");

    expect(server.sent.map((write) => write.slug)).toEqual(["google", "apple"]);
    expect(screen.getByTestId("busy")).toHaveTextContent("apple,google");

    await server.open(1);
    await waitFor(() => expect(screen.getByTestId("visible-apple")).toHaveTextContent("hidden"));
    expect(screen.getByTestId("visible-google")).toHaveTextContent("shown");
  });

  it("does not strand the write behind a failed one, and reports only the newest", async () => {
    await mount();

    await click("Hide Google");
    await click("Hide Google");

    await server.fail(0, new Error("visibility write exploded"));
    await waitFor(() => expect(server.sent).toHaveLength(2));

    await server.open(1);
    await waitFor(() => expect(screen.getByTestId("busy")).toHaveTextContent(""));
    expect(server.read("google")).toBe(false);
    // The failure was superseded by a write that worked; the screen says so.
    expect(screen.getByTestId("error")).toHaveTextContent("");
  });

  it("reports a failure that nothing follows", async () => {
    await mount();

    await click("Hide Google");
    await server.fail(0, new Error("visibility write exploded"));

    // A failure that explains nothing says the sentence alone, never its English.
    await waitFor(() =>
      expect(screen.getByTestId("error")).toHaveTextContent("Couldn't hide Google from your radar."),
    );
    expect(screen.getByTestId("error")).not.toHaveTextContent("exploded");
    expect(screen.getByTestId("busy")).toHaveTextContent("");
  });
});

describe("the register's roster queue", () => {
  it("holds a second roster write until the first has settled", async () => {
    /* Each roster reply is the WHOLE discovery state the screen adopts, so two
       in the air means the screen keeps whichever reply arrived last, not the
       roster after both. */
    await mount();

    await click("Unfollow Google");
    expect(server.roster).toHaveLength(1);

    await click("Unfollow Apple");
    expect(server.roster, "a second roster PUT went out with the first still in flight")
      .toHaveLength(1);

    await server.open(0);
    await waitFor(() => expect(server.roster).toHaveLength(2));
  });

  it("leaves the install holding the last roster asked for, whichever reply lands first", async () => {
    await mount();

    await click("Unfollow Google");
    await click("Unfollow Apple");

    // The door for the SECOND write opens first: both changes must still hold.
    await server.open(1);
    await server.open(0);
    await waitFor(() => expect(screen.getByTestId("busy")).toHaveTextContent(""));

    expect(server.readTracked("google")).toBe(false);
    expect(server.readTracked("apple")).toBe(false);
  });

  it("moves the switch at the click, not when the queue reaches the write", async () => {
    /* The optimistic half has to survive the queue: a switch that does not
       move until a held write drains reads as a dead control. */
    await mount();

    await click("Unfollow Google");
    await click("Unfollow Apple");

    expect(server.roster, "the second write dispatched").toHaveLength(1);
    // Exact, not `toHaveTextContent`: that matches on substring, so every
    // assertion about this list would pass on a superset of itself.
    expect(
      screen.getByTestId("chosen").textContent,
      "the second click left the switch where it was",
    ).toBe("");
  });

  it("puts back only the rows a failed write touched", async () => {
    /* Rolling back to the whole pre-write selection would delete every edit
       made while the failure sat in the queue — and with the order total there
       is always a later write that re-sends them. */
    await mount();

    await click("Unfollow Google");
    await click("Unfollow Apple");

    await server.fail(0, new Error("roster write exploded"));
    await waitFor(() => expect(server.roster).toHaveLength(2));

    // Google is back; Apple's later edit was not collateral. Exact, because a
    // wholesale rollback yields "apple,google" — a superset that a substring
    // matcher reads as a pass.
    expect(screen.getByTestId("chosen").textContent).toBe("google");
    expect(screen.getByTestId("error")).toHaveTextContent("Couldn't unfollow Google.");

    // The second write answers: Apple is unfollowed and Google stays followed.
    await server.open(1);
    await waitFor(() => expect(screen.getByTestId("busy")).toHaveTextContent(""));
    expect(screen.getByTestId("chosen").textContent).toBe("google");
    expect(server.readTracked("google")).toBe(true);
    expect(server.readTracked("apple")).toBe(false);
  });

  it("names the way a failed follow went: follow or unfollow", async () => {
    await mount();
    const unfollowFailed = msg("companies-data-follow-failed", { direction: "unfollow", name: "Google" });
    const followFailed = msg("companies-data-follow-failed", { direction: "follow", name: "Google" });

    await click("Unfollow Google");
    await server.fail(0, new Error("roster write exploded"));
    await waitFor(() => expect(screen.getByTestId("error")).toHaveTextContent(unfollowFailed));
    expect(screen.getByTestId("error")).not.toHaveTextContent(followFailed);

    // Rolled back, so the switch is on again; this time the unfollow lands.
    await click("Unfollow Google");
    await server.open(1);
    await waitFor(() => expect(screen.getByTestId("chosen").textContent).toBe("apple"));

    await click("Follow Google");
    await server.fail(2, new Error("roster write exploded"));
    await waitFor(() => expect(screen.getByTestId("error")).toHaveTextContent(followFailed));
    expect(screen.getByTestId("error")).not.toHaveTextContent(unfollowFailed);
  });

  it("keeps a switch still waiting when the write before it answers", async () => {
    /* The first write's answer is the roster as it stood after that write, so
       it still follows Apple. Adopted whole, it would flip Apple's switch back
       on until the second write answers. */
    await mount();

    await click("Unfollow Google");
    await click("Unfollow Apple");
    await server.open(0);
    await waitFor(() => expect(server.roster).toHaveLength(2));

    expect(screen.getByTestId("chosen").textContent).toBe("");
    await server.open(1);
    await waitFor(() => expect(screen.getByTestId("busy")).toHaveTextContent(""));
    expect(screen.getByTestId("chosen").textContent).toBe("");
  });
});

describe("a roster write names only what it switches", () => {
  it("leaves a company followed since the screen loaded as it is", async () => {
    server.trackElsewhere("apple", false);
    await mount();
    expect(screen.getByRole("button", { name: "Follow Apple" })).toBeInTheDocument();
    server.trackElsewhere("apple", true);

    await click("Unfollow Google");
    await server.open(0);
    await waitFor(() => expect(screen.getByTestId("busy")).toHaveTextContent(""));

    expect(server.roster).toEqual([{ follow: [], unfollow: ["google"] }]);
    expect(server.readTracked("google")).toBe(false);
    expect(server.readTracked("apple"), "the screen never switched Apple").toBe(true);
  });
});

describe("a roster write and a row write together", () => {
  it("does not echo away a visibility change it overlapped", async () => {
    /* The roster reply carries a `visible` for every company and the screen
       adopts it whole. Start it while a row PATCH is in the air and its echo
       describes the row as it was BEFORE that PATCH — the eye flips back, the
       database disagrees, and nothing further corrects it. */
    await mount();

    await click("Hide Google");
    expect(server.sent).toHaveLength(1);

    await click("Unfollow Apple");
    expect(server.roster, "the roster PUT went out with a row write in flight")
      .toHaveLength(0);

    await server.open(0);
    await waitFor(() => expect(screen.getByTestId("visible-google")).toHaveTextContent("hidden"));
    await waitFor(() => expect(server.roster).toHaveLength(1));

    await server.open(1);
    await waitFor(() => expect(screen.getByTestId("busy")).toHaveTextContent(""));

    expect(server.read("google")).toBe(false);
    expect(
      screen.getByTestId("visible-google"),
      "the roster reply echoed away the row write it overlapped",
    ).toHaveTextContent("hidden");
  });

  it("holds a row write back while a roster write is in the air", async () => {
    await mount();

    await click("Unfollow Apple");
    await click("Hide Google");

    expect(server.sent, "a row PATCH ran while a roster write was in the air").toHaveLength(0);
    await server.open(0);
    await waitFor(() => expect(server.sent).toHaveLength(1));
  });

  it("keeps a row busy until BOTH writers have let go of it", async () => {
    /* Two writers with two counters and one shared set would let whichever
       finished first clear the row, which would then read idle with a write
       outstanding. */
    await mount();

    await click("Hide Google");
    await click("Unfollow Google");
    expect(screen.getByTestId("busy")).toHaveTextContent("google");

    await server.open(0);
    await waitFor(() => expect(server.roster).toHaveLength(1));
    expect(
      screen.getByTestId("busy"),
      "the row re-armed with the roster write still outstanding",
    ).toHaveTextContent("google");

    await server.open(1);
    await waitFor(() => expect(screen.getByTestId("busy")).toHaveTextContent(""));
  });
});

describe("a write failure", () => {
  it("is not cleared by a write to another company", async () => {
    /* One `error` slot cleared at every write start would let the rows erase
       each other's failures: a failed write would leave no trace on screen
       while its row showed the pre-write value, which reads as a click that
       never registered. */
    await mount();

    await click("Hide Google");
    await server.fail(0, new Error("visibility write exploded"));
    await waitFor(() =>
      expect(screen.getByTestId("error")).toHaveTextContent("Couldn't hide Google"));

    await click("Hide Apple");
    await server.open(1);
    await waitFor(() => expect(screen.getByTestId("visible-apple")).toHaveTextContent("hidden"));

    expect(
      screen.getByTestId("error"),
      "another row's write erased the only account of Google's failure",
    ).toHaveTextContent("Couldn't hide Google");
  });

  it("is not cleared by the other kind of write either", async () => {
    // The roster path is the one with a rollback, so clearing its failure
    // leaves a switch that reverted under the reader's hand and no reason why.
    await mount();

    await click("Unfollow Google");
    await server.fail(0, new Error("roster write exploded"));
    await waitFor(() =>
      expect(screen.getByTestId("error")).toHaveTextContent("Couldn't unfollow Google"));

    await click("Hide Apple");
    await server.open(1);
    await waitFor(() => expect(screen.getByTestId("visible-apple")).toHaveTextContent("hidden"));

    expect(screen.getByTestId("error")).toHaveTextContent("Couldn't unfollow Google");
  });

  it("is cleared by the next attempt on its own subject", async () => {
    await mount();

    await click("Hide Google");
    await server.fail(0, new Error("visibility write exploded"));
    await waitFor(() =>
      expect(screen.getByTestId("error")).toHaveTextContent("Couldn't hide Google"));

    await click("Hide Google");
    await server.open(1);
    await waitFor(() => expect(screen.getByTestId("error")).toHaveTextContent(""));
  });

  it("names the company, and says why from the failure's code, never the server's English", async () => {
    await mount();

    await click("Hide Google");
    await server.fail(0, new ApiError("'google' is already tracked", 409, "company-conflict"));

    await waitFor(() => expect(screen.getByTestId("error")).toHaveTextContent(
      `Couldn't hide Google from your radar. ${msg("error-company-conflict")}`,
    ));
    expect(screen.getByTestId("error")).not.toHaveTextContent("already tracked");
  });
});

describe("asking for a scan", () => {
  /** The register asks for a scan the way its row button does. */
  function ScanProbe() {
    const { resource, failures, toggleVisible } = useCompanies();
    const { syncCompanies } = useCompaniesSync();
    const google = resource.data?.companies.find((row) => row.slug === "google");
    return (
      <div>
        <span data-testid="scan-error">{failures.map((f) => f.text).join(" | ")}</span>
        <button
          onClick={() => syncCompanies(["google"], {
            confirm: "Scanning Google…",
            failure: "Couldn't start a scan for Google.",
          })}
        >
          Scan Google
        </button>
        {google && (
          <button onClick={() => void toggleVisible(google)}>Hide Google</button>
        )}
      </div>
    );
  }

  const mountScan = async () => {
    render(
      <MemoryRouter>
        <AppProviders>
          <ToastProvider>
            <CompaniesDataProvider>
              <ScanProbe />
            </CompaniesDataProvider>
          </ToastProvider>
        </AppProviders>
      </MemoryRouter>,
    );
    await screen.findByText("Scan Google");
  };

  it("says nothing started when the trigger failed", async () => {
    /* `triggerSync` swallows its own error so it can retire the optimistic
       bridge, which means it resolves EXACTLY as it does on success. The board
       must not read that as confirmation: its notice is the one surface on
       this screen whose whole job is to say whether the ask landed. */
    vi.mocked(api.sync).mockRejectedValue(new Error("offline"));
    await mountScan();

    await click("Scan Google");

    await waitFor(() =>
      expect(screen.getByTestId("scan-error")).toHaveTextContent(
        "Couldn't start a scan for Google.",
      ));
    expect(
      screen.queryByText("Scanning Google…"),
      "the board confirmed a scan that never started",
    ).not.toBeInTheDocument();
  });

  it("confirms only once the trigger has landed", async () => {
    vi.mocked(api.sync).mockResolvedValue({ status: "started", companies: ["google"], queued: ["google"] });
    await mountScan();

    await click("Scan Google");

    await waitFor(() => expect(screen.getByText("Scanning Google…")).toBeInTheDocument());
    expect(screen.getByTestId("scan-error")).toHaveTextContent("");
  });

  it("clears a previous scan failure when the next attempt starts", async () => {
    vi.mocked(api.sync).mockRejectedValueOnce(new Error("offline"));
    await mountScan();

    await click("Scan Google");
    await waitFor(() =>
      expect(screen.getByTestId("scan-error")).toHaveTextContent("Couldn't start a scan"));

    vi.mocked(api.sync).mockResolvedValue({ status: "started", companies: ["google"], queued: ["google"] });
    await click("Scan Google");
    await waitFor(() => expect(screen.getByTestId("scan-error")).toHaveTextContent(""));
  });

  it("leaves a row write's failure alone", async () => {
    /* The keyed discipline, across the third writer: a scan speaks for the
       `scan` subject and for nothing else. */
    vi.mocked(api.sync).mockResolvedValue({ status: "started", companies: ["google"], queued: ["google"] });
    await mountScan();

    await click("Hide Google");
    await server.fail(0, new Error("visibility write exploded"));
    await waitFor(() =>
      expect(screen.getByTestId("scan-error")).toHaveTextContent("Couldn't hide Google"));

    await click("Scan Google");
    await waitFor(() => expect(screen.getByText("Scanning Google…")).toBeInTheDocument());
    expect(
      screen.getByTestId("scan-error"),
      "asking for a scan erased a row write's failure",
    ).toHaveTextContent("Couldn't hide Google");
  });
});
