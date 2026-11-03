import { msg } from "../../test/msg";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { CompanyDirectoryStatus, CompanyDiscoveryCompany, CompanyDiscoveryState } from "../../api";
import { api } from "../../api";
import { statsFixture, statusFixture } from "../../test/fixtures";
import { AppProviders } from "../../context/AppProviders";
import { ToastProvider } from "../../ui/Toast";
import { SetupCompanies } from "./SetupCompanies";

/* First-run setup's companies step. Its two wider answers are the register's
   own bulk follows, so what is held here is the order of things: nothing is
   followed without the confirmation the register asks, the words of that
   confirmation are what is recorded as consent, a cancel keeps the person on
   the step, and the profile is saved only once every asked follow is
   answered yes. */

vi.mock("../../api", () => ({
  api: {
    companyDiscovery: vi.fn(),
    companyOpenCounts: vi.fn(),
    searchCompanyDirectory: vi.fn(),
    companyDirectoryStatus: vi.fn(),
    followCompanyDirectory: vi.fn(),
    setCompanySelection: vi.fn(),
    syncTargets: vi.fn(),
    sync: vi.fn(),
    cancelSync: vi.fn(),
    status: vi.fn(),
    stats: vi.fn(),
    compareSelection: vi.fn().mockResolvedValue({ job_ids: [] }),
    setCompareSelection: vi.fn((jobIds: number[]) => Promise.resolve({ job_ids: jobIds })),
  },
}));

const company = (over: Partial<CompanyDiscoveryCompany>): CompanyDiscoveryCompany => ({
  slug: "acme",
  display: "Acme",
  careers_url: "https://example.com/careers",
  sectors: ["technology"],
  aliases: [],
  connector_state: "live",
  parked_reason: null,
  selectable: true,
  tracked: false,
  enabled: false,
  visible: true,
  builtin: true,
  curated: false,
  directory: false,
  wall: null,
  consented: false,
  status: null,
  ...over,
});

/* An install whose follows are not the curated list: two curated companies
   followed, one followed though not curated, one curated though not followed,
   and two named ones not followed, one of which limits collection, so
   following it needs consent. */
const STATE: CompanyDiscoveryState = {
  sectors: [{ slug: "technology", company_count: 6, ready_count: 0, selected_count: 3 }],
  companies: [
    company({ slug: "apple", display: "Apple", curated: true, tracked: true, enabled: true }),
    company({ slug: "stripe", display: "Stripe", curated: true, tracked: true, enabled: true }),
    company({ slug: "figma", display: "Figma", tracked: true, enabled: true }),
    company({ slug: "datadog", display: "Datadog", curated: true }),
    company({ slug: "databricks", display: "Databricks" }),
    company({ slug: "google", display: "Google", wall: "robots" }),
  ],
};

const DIRECTORY: CompanyDirectoryStatus = {
  size: 10214, following: false, since: null, checked: 0, to_check: 10214, with_roles: 0, waiting_for_power: false,
};

let onStart: ReturnType<typeof vi.fn<() => Promise<void>>>;
let onBack: ReturnType<typeof vi.fn<() => void>>;

function renderStep(kept: { keptChoice?: string; onChoice?: (choice: string) => void } = {}) {
  return render(
    <MemoryRouter>
      <AppProviders>
        <ToastProvider>
          <SetupCompanies footClassName="walk-step-foot" saving={false} onBack={onBack} onStart={onStart} {...kept} />
        </ToastProvider>
      </AppProviders>
    </MemoryRouter>,
  );
}

const choose = (label: string) => userEvent.click(screen.getByRole("radio", { name: new RegExp(`^${label}`) }));
const start = () => userEvent.click(screen.getByRole("button", { name: msg("companies-setup-start", { choice: "no" }) }));
const dialogText = (dialog: HTMLElement) =>
  [within(dialog).getByRole("heading").textContent, ...within(dialog).getAllByText(/./, { selector: "p" })
    .map((p) => p.textContent)].join("\n\n");

beforeEach(() => {
  vi.clearAllMocks();
  onStart = vi.fn(() => Promise.resolve());
  onBack = vi.fn();
  vi.mocked(api.companyDiscovery).mockResolvedValue(STATE);
  vi.mocked(api.companyOpenCounts).mockResolvedValue({ counts: {}, not_counted: {}, unplaced: {}, unsorted: {}, last_read: {} });
  vi.mocked(api.searchCompanyDirectory).mockResolvedValue({ size: 0, match_count: 0, matches: [] });
  vi.mocked(api.companyDirectoryStatus).mockResolvedValue(DIRECTORY);
  vi.mocked(api.followCompanyDirectory).mockResolvedValue({ ...DIRECTORY, following: true, since: "2026-10-27T08:00:00Z" });
  vi.mocked(api.setCompanySelection).mockImplementation(async () => STATE);
  vi.mocked(api.syncTargets).mockResolvedValue({ companies: [], freshness_max_hours: 26 });
  vi.mocked(api.status).mockResolvedValue(statusFixture);
  vi.mocked(api.stats).mockResolvedValue(statsFixture);
});

describe("SetupCompanies", () => {
  it("names the companies followed now and starts on them by default, following nothing more", async () => {
    renderStep();

    const named = await screen.findByText("Apple");
    const list = named.closest("ul");
    // What is followed, whether or not it is on the curated list; a curated
    // company the install does not follow is not claimed.
    expect(list).toHaveTextContent("Stripe");
    expect(list).toHaveTextContent("Figma");
    expect(list).not.toHaveTextContent("Datadog");
    expect(list).not.toHaveTextContent("Databricks");
    expect(screen.getByRole("radio", { name: /^Well-known companies/ })).toBeChecked();
    expect(screen.getByRole("radio", { name: /^Well-known companies/ }))
      .toHaveAccessibleName(expect.stringContaining(msg("companies-setup-well-known-detail", { count: 3 })));

    await start();

    expect(onStart).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(api.setCompanySelection).not.toHaveBeenCalled();
    expect(api.followCompanyDirectory).not.toHaveBeenCalled();
  });

  it("every listed company asks the register's question, records its words as consent, then starts", async () => {
    renderStep();
    await screen.findByText("Apple");
    await choose("Every listed company");
    await start();

    const ask = await screen.findByRole("dialog");
    // The person has not answered yet: nothing is followed and nothing saved.
    expect(onStart).not.toHaveBeenCalled();
    const shown = dialogText(ask);
    await userEvent.click(within(ask).getByRole("button", { name: msg("companies-follow-copy-follow-all", { count: 3 }) }));

    await waitFor(() => expect(api.setCompanySelection).toHaveBeenCalledTimes(1));
    const [sent, consents] = vi.mocked(api.setCompanySelection).mock.calls[0];
    expect([...sent.follow].sort()).toEqual(["databricks", "datadog", "google"]);
    expect(consents).toEqual([{ slug: "google", text: shown, locale: "en" }]);
    await waitFor(() => expect(onStart).toHaveBeenCalledTimes(1));
    expect(api.followCompanyDirectory).not.toHaveBeenCalled();
  });

  it("a cancelled question keeps the person on the step, follows nothing and saves nothing", async () => {
    renderStep();
    await screen.findByText("Apple");
    await choose("Every listed company");
    await start();

    const ask = await screen.findByRole("dialog");
    await userEvent.click(within(ask).getByRole("button", { name: msg("companies-follow-copy-keep", { curatedList: msg("shared-curated-list") }) }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(api.setCompanySelection).not.toHaveBeenCalled();
    expect(onStart).not.toHaveBeenCalled();
    // The step is still there, ready to answer again.
    expect(screen.getByRole("button", { name: msg("companies-setup-start", { choice: "no" }) })).toBeEnabled();
  });

  it("every company asks one question, records its words as consent, follows the list and the rest, then starts", async () => {
    renderStep();
    await screen.findByText("Apple");
    await choose("Plus other companies");
    await start();

    const ask = await screen.findByRole("dialog", { name: msg("companies-follow-copy-follow-every-company-question") });
    expect(onStart).not.toHaveBeenCalled();
    expect(ask).toHaveTextContent(msg("companies-follow-copy-some-of-these-companies-careers"));
    const shown = dialogText(ask);
    await userEvent.click(within(ask).getByRole("button", { name: msg("companies-follow-copy-follow-every-company") }));

    await waitFor(() => expect(api.followCompanyDirectory).toHaveBeenCalledWith(true));
    expect(api.setCompanySelection).toHaveBeenCalledTimes(1);
    const [sent, consents] = vi.mocked(api.setCompanySelection).mock.calls[0];
    expect([...sent.follow].sort()).toEqual(["databricks", "datadog", "google"]);
    expect(consents).toEqual([{ slug: "google", text: shown, locale: "en" }]);
    await waitFor(() => expect(onStart).toHaveBeenCalledTimes(1));
    // One question for one choice: no second dialog follows the yes.
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("a cancelled every-company question follows nothing, starts no scan and stays on the step", async () => {
    renderStep();
    await screen.findByText("Apple");
    await choose("Plus other companies");
    await start();

    const ask = await screen.findByRole("dialog");
    await userEvent.click(within(ask).getByRole("button", { name: msg("companies-follow-copy-cancel") }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(api.setCompanySelection).not.toHaveBeenCalled();
    expect(api.followCompanyDirectory).not.toHaveBeenCalled();
    expect(onStart).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: msg("companies-setup-start", { choice: "no" }) })).toBeEnabled();
  });

  it("every company with the whole list already followed asks without a consent and only starts the rest", async () => {
    const followed = STATE.companies.map((entry) => ({ ...entry, tracked: true, enabled: true }));
    vi.mocked(api.companyDiscovery).mockResolvedValue({ ...STATE, companies: followed });
    renderStep();
    await screen.findByText("Apple");
    await choose("Plus other companies");
    await start();

    const ask = await screen.findByRole("dialog", { name: msg("companies-follow-copy-follow-every-company-question") });
    expect(ask).not.toHaveTextContent(msg("companies-follow-copy-some-of-these-companies-careers"));
    await userEvent.click(within(ask).getByRole("button", { name: msg("companies-follow-copy-follow-every-company") }));

    await waitFor(() => expect(api.followCompanyDirectory).toHaveBeenCalledWith(true));
    expect(api.setCompanySelection).not.toHaveBeenCalled();
    await waitFor(() => expect(onStart).toHaveBeenCalledTimes(1));
  });

  /* A reload of setup's last step keeps the answer: the walk hands back the
     choice it kept for the tab, and is told of each new one. */
  it("opens on the choice kept for the tab, and hands on each new one", async () => {
    const onChoice = vi.fn();
    renderStep({ keptChoice: "listed", onChoice });
    await screen.findByText("Apple");
    expect(screen.getByRole("radio", { name: /^Every listed company/ })).toBeChecked();
    await choose("Plus other companies");
    expect(onChoice).toHaveBeenLastCalledWith("everything");
  });

  it("a kept choice the install no longer offers, or of another shape, opens on the default", async () => {
    vi.mocked(api.companyDirectoryStatus).mockResolvedValue({ ...DIRECTORY, following: true });
    const { unmount } = renderStep({ keptChoice: "everything" });
    await screen.findByText("Apple");
    expect(screen.queryByRole("radio", { name: /^Plus other companies/ })).toBeNull();
    expect(screen.getByRole("radio", { name: /^Well-known companies/ })).toBeChecked();
    await start();
    expect(api.followCompanyDirectory).not.toHaveBeenCalled();
    unmount();
    renderStep({ keptChoice: "all of them" });
    await screen.findByText("Apple");
    expect(screen.getByRole("radio", { name: /^Well-known companies/ })).toBeChecked();
  });

  it("names Settings as the place to follow single companies later, and Back goes back", async () => {
    renderStep();
    await screen.findByText("Apple");
    expect(screen.getByText(msg("companies-setup-later"))).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: msg("companies-setup-back") }));
    expect(onBack).toHaveBeenCalledTimes(1);
  });
});
