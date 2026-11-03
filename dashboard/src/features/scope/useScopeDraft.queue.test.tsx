import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, type ScopeAxes, type ScopeRefreshResult, type ScopeSettingsPayload } from "../../api";
import { ScopeDraftProvider, useScopeDraft } from "./useScopeDraft";
import { profileStateFixture, scopeCatalogFixture, settingsSaveFixture } from "../../test/fixtures";

/* What happens to a scope write that is still in the air.
 *
 * `useScopeDraft.test.tsx` proves the save path sends the right body with
 * one request at a time and nothing racing it. These are the questions a mock
 * that resolves immediately cannot ask: what the install ends up HOLDING when
 * two writes overlap, and what happens to an edit made while a response is on
 * its way back. Both need a boundary the test can hold open, and a boundary
 * that REMEMBERS — a call list says which payloads were sent, never which one
 * the server kept.
 */

vi.mock("../../api", async () => {
  const actual = await vi.importActual<typeof import("../../api")>("../../api");
  return {
    ...actual,
    api: {
      ...actual.api,
      scopeCatalog: vi.fn(),
      profile: vi.fn(),
      saveSettings: vi.fn(),
      refreshScopeCatalog: vi.fn(),
    },
  };
});

const refreshStats = vi.fn();
vi.mock("../../context/MissionState", () => ({ useMissionActions: () => ({ refreshStats }) }));


/* The catalog lists no role families, so the server reads no answers off the
   flat lists. */
const AXES: ScopeAxes = {
  enabled_role_groups: ["software_engineering"],
  enabled_seniority_bands: ["entry", "mid", "senior"],
  enabled_role_tracks: ["technical"],
  enabled_location_groups: ["uk"],
  enabled_domain_groups: ["ai_ml"],
  excluded_domain_groups: [],
  excluded_location_groups: [],
  include_unstated_level: false,
  role_answers: [],
};

const CATALOG = scopeCatalogFixture({
  settings: AXES,
  domains: [{ slug: "ai_ml", selected: true, count: 8, examples: [], kind: "technology" }],
  unclassified_domain_count: 0,
  levels: [
    { slug: "entry", order: 1, default_enabled: false, selected: true, new: false, count: 1, decoder: {} },
    { slug: "mid", order: 2, default_enabled: false, selected: true, new: false, count: 1, decoder: {} },
    { slug: "senior", order: 3, default_enabled: true, selected: true, new: false, count: 1, decoder: {} },
  ],
  locations: [
    { slug: "uk", display: "United Kingdom", default_enabled: true, selected: true, new: false, count: 4, kind: "country", parent: null, uncovered_by: [], prominent: true },
  ],
  tracks: [
    { slug: "technical", order: 2, default_enabled: true, selected: true, new: false, count: 9, allowed_bands: ["entry", "mid", "senior"] },
  ],
  joint_counts_ready: false,
});

/** A settings endpoint that HOLDS what it was told, and holds each caller at
    the door until the test opens it. `read()` is the fresh read: the question
    "which payload did the install end up with", which no call list answers. */
function statefulSettings() {
  let stored = { ...AXES };
  const received: ScopeSettingsPayload[] = [];
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
  const handler = async (body: ScopeSettingsPayload) => {
    const index = received.length;
    received.push(body);
    await gateFor(index).waited;
    stored = {
      enabled_role_groups: body.enabled_role_groups ?? [],
      enabled_seniority_bands: body.enabled_seniority_bands ?? [],
      enabled_role_tracks: body.enabled_role_tracks ?? [],
      enabled_location_groups: body.enabled_location_groups ?? [],
      enabled_domain_groups: body.enabled_domain_groups ?? [],
      excluded_domain_groups: body.excluded_domain_groups ?? [],
      excluded_location_groups: body.excluded_location_groups ?? [],
      include_unstated_level: body.include_unstated_level ?? false,
      role_answers: body.role_answers ?? [],
    };
    return settingsSaveFixture(stored, { in_scope_changed: 1 });
  };
  return {
    handler,
    received,
    read: () => stored,
    open: (index: number) => act(async () => { gateFor(index).open(); }),
    fail: (index: number, reason: Error) => act(async () => { gateFor(index).fail(reason); }),
  };
}

function Probe() {
  const d = useScopeDraft();
  return (
    <div>
      <span data-testid="catalog">{d.catalog ? "loaded" : "none"}</span>
      <span data-testid="saving">{d.saving ? "saving" : "idle"}</span>
      <span data-testid="refreshing">{d.refreshing ? "refreshing" : "idle"}</span>
      <span data-testid="message">{d.refreshMessage ?? ""}</span>
      <span data-testid="error">{d.error ?? ""}</span>
      <span data-testid="dirty">{d.dirty ? "dirty" : "clean"}</span>
      <span data-testid="draft-roles">{[...d.selectedRoles].sort().join(",")}</span>
      <span data-testid="saved-roles">{[...d.savedRoles].sort().join(",")}</span>
      <button onClick={() => d.save()}>save</button>
      <button onClick={() => d.toggleRole("data")}>toggle data</button>
      <button onClick={() => d.refreshInventory()}>refresh</button>
    </div>
  );
}

const renderDraft = () => render(<ScopeDraftProvider><Probe /></ScopeDraftProvider>);

const loaded = async () => {
  const user = userEvent.setup();
  renderDraft();
  await screen.findByText("loaded");
  return user;
};

const click = (name: string) => screen.getByRole("button", { name });

let server: ReturnType<typeof statefulSettings>;

beforeEach(() => {
  vi.clearAllMocks();
  server = statefulSettings();
  vi.mocked(api.scopeCatalog).mockResolvedValue(CATALOG);
  vi.mocked(api.profile).mockResolvedValue(profileStateFixture());
  vi.mocked(api.saveSettings).mockImplementation(server.handler);
  vi.mocked(api.refreshScopeCatalog).mockResolvedValue({ status: "started" });
});

describe("the scope draft's save queue", () => {
  it("holds a second save until the first has settled", async () => {
    /* Both writes PUT the whole scope, so two in flight at once means the
       install keeps whichever response the network happened to deliver last —
       which is not necessarily the later write. The shipped buttons disable on
       `saving`, but that only appears once the provider has re-rendered, and
       this provider's re-render draws the whole role catalog. */
    const user = await loaded();

    await user.click(click("save"));
    expect(server.received).toHaveLength(1);

    await user.click(click("toggle data"));
    await user.click(click("save"));
    expect(server.received).toHaveLength(1);

    await server.open(0);
    await waitFor(() => expect(server.received).toHaveLength(2));
    expect(server.received[1].enabled_role_groups).toContain("data");
  });

  it("leaves the install holding the last payload even when the second reply would land first", async () => {
    /* The reason the queue is a queue and not a stale-response guard. Guards
       fix what the SCREEN adopts; they cannot fix what the database keeps. With
       both writes in the air, the second one's row can be overwritten by the
       first one's — the install silently keeps the payload the user abandoned,
       and a fresh read is the only thing that can tell. */
    const user = await loaded();

    await user.click(click("save"));
    await user.click(click("toggle data"));
    await user.click(click("save"));

    // The door for the SECOND write opens first: nothing is holding it back.
    await server.open(1);
    await server.open(0);

    await waitFor(() => expect(screen.getByTestId("saving")).toHaveTextContent("idle"));
    expect(server.received).toHaveLength(2);
    expect([...server.read().enabled_role_groups].sort()).toEqual(["data", "software_engineering"]);
  });

  it("keeps saving while queued work is still waiting", async () => {
    const user = await loaded();

    await user.click(click("save"));
    await user.click(click("save"));
    await server.open(0);

    await waitFor(() => expect(server.received).toHaveLength(2));
    expect(screen.getByTestId("saving")).toHaveTextContent("saving");

    await server.open(1);
    await waitFor(() => expect(screen.getByTestId("saving")).toHaveTextContent("idle"));
  });

  it("does not strand the write behind a failed one", async () => {
    const user = await loaded();

    await user.click(click("save"));
    await user.click(click("toggle data"));
    await user.click(click("save"));

    await server.fail(0, new Error("scope save exploded"));
    await waitFor(() => expect(server.received).toHaveLength(2));

    await server.open(1);
    await waitFor(() => expect(screen.getByTestId("saving")).toHaveTextContent("idle"));
    // The write that succeeded is the one the install holds, and the failure it
    // followed is off the screen: a newer write reports for itself.
    expect([...server.read().enabled_role_groups].sort()).toEqual(["data", "software_engineering"]);
    expect(screen.getByTestId("error")).toHaveTextContent("");
  });

  it("reports a failure that nothing follows", async () => {
    const user = await loaded();

    await user.click(click("save"));
    await server.fail(0, new Error("scope save exploded"));

    await waitFor(() => expect(screen.getByTestId("error")).toHaveTextContent("Couldn't save your radar. Try again."));
    expect(screen.getByTestId("error")).not.toHaveTextContent("exploded");
    expect(screen.getByTestId("saving")).toHaveTextContent("idle");
  });
});

describe("an edit made while a scope write is in flight", () => {
  it("survives the response instead of being echoed away", async () => {
    /* The response describes the state at the CLICK. Adopting its axes into the
       draft wholesale deletes anything toggled since — no error, and the draft
       reads clean, so the user is told their radar is saved while the thing
       they just picked is gone. */
    const user = await loaded();

    await user.click(click("save"));
    await user.click(click("toggle data"));
    await server.open(0);

    await waitFor(() => expect(screen.getByTestId("saved-roles")).toHaveTextContent("software_engineering"));
    expect(screen.getByTestId("draft-roles")).toHaveTextContent("data,software_engineering");
    expect(screen.getByTestId("dirty")).toHaveTextContent("dirty");
  });
});

describe("the scope draft's inventory refresh", () => {
  it("keeps the newest refresh's status when an older one answers late", async () => {
    /* PersonaRail disables its button while `refreshing`, so this is the
       provider's own contract rather than a click path: a response that is no
       longer the current attempt may not speak for the screen. */
    const resolvers: ((value: ScopeRefreshResult) => void)[] = [];
    vi.mocked(api.refreshScopeCatalog).mockImplementation(
      () => new Promise<ScopeRefreshResult>((resolve) => { resolvers.push(resolve); }),
    );
    const user = await loaded();

    await user.click(click("refresh"));
    await user.click(click("refresh"));
    expect(resolvers).toHaveLength(2);

    await act(async () => { resolvers[1]({ status: "started" }); });
    await waitFor(() => expect(screen.getByTestId("message")).toHaveTextContent("Counting roles again"));
    expect(screen.getByTestId("refreshing")).toHaveTextContent("idle");

    await act(async () => { resolvers[0]({ status: "deferred" }); });
    expect(screen.getByTestId("message")).toHaveTextContent("Counting roles again");
    expect(screen.getByTestId("refreshing")).toHaveTextContent("idle");
  });
});
