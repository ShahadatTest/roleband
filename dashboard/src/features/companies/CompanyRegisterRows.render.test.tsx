import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { CompanyDirectoryStatus, CompanyDiscoveryCompany, CompanyDiscoveryState } from "../../api";
import { api } from "../../api";
import { statsFixture, statusFixture } from "../../test/fixtures";
import { AppProviders } from "../../context/AppProviders";
import { ToastProvider } from "../../ui/Toast";
import { CompaniesDataProvider } from "./CompaniesData";
import { CompaniesSection } from "./CompaniesSection";

/* Which rows a change draws. A search can put most of the catalog on screen,
 * and a switch then moves the selection several times (the click, the write
 * settling); drawing every row each time is what made a switch slow. Counted
 * through each row's mark, which every drawing of a row renders once. */

const drawn = vi.hoisted(() => [] as string[]);
vi.mock("../../ui", async (importOriginal) => {
  const ui = await importOriginal<typeof import("../../ui")>();
  return {
    ...ui,
    CompanyIcon: (props: Parameters<typeof ui.CompanyIcon>[0]) => {
      drawn.push(props.slug);
      return <ui.CompanyIcon {...props} />;
    },
  };
});

vi.mock("../../api", () => ({
  api: {
    companyDiscovery: vi.fn(),
    companyOpenCounts: vi.fn(),
    searchCompanyDirectory: vi.fn(),
    companyDirectoryStatus: vi.fn(),
    setCompanySelection: vi.fn(),
    syncTargets: vi.fn(),
    status: vi.fn(),
    stats: vi.fn(),
    compareSelection: vi.fn().mockResolvedValue({ job_ids: [] }),
    setCompareSelection: vi.fn((jobIds: number[]) => Promise.resolve({ job_ids: jobIds })),
  },
}));

const company = (slug: string, over: Partial<CompanyDiscoveryCompany> = {}): CompanyDiscoveryCompany => ({
  slug,
  display: slug[0].toUpperCase() + slug.slice(1),
  careers_url: "https://example.com/careers",
  sectors: ["faang"],
  aliases: [],
  connector_state: "live",
  parked_reason: null,
  selectable: true,
  tracked: false,
  enabled: false,
  visible: true,
  builtin: true,
  curated: true,
  directory: false,
  wall: null,
  consented: false,
  status: null,
  ...over,
});

const state: CompanyDiscoveryState = {
  sectors: [{ slug: "faang", company_count: 5, ready_count: 0, selected_count: 1 }],
  companies: [
    company("google", { tracked: true, enabled: true, status: "active" }),
    company("apple"),
    company("amazon"),
    company("netflix"),
    company("microsoft"),
  ],
};

const noSet: CompanyDirectoryStatus = {
  size: 0, following: false, since: null, checked: 0, to_check: 0, with_roles: 0, waiting_for_power: false,
};

beforeEach(() => {
  vi.clearAllMocks();
  drawn.length = 0;
  vi.mocked(api.companyDiscovery).mockResolvedValue(state);
  vi.mocked(api.companyOpenCounts).mockResolvedValue({
    counts: { google: 3 }, not_counted: {}, unplaced: {}, unsorted: {}, last_read: {},
  });
  vi.mocked(api.companyDirectoryStatus).mockResolvedValue(noSet);
  vi.mocked(api.syncTargets).mockResolvedValue({ companies: [], freshness_max_hours: 26 });
  vi.mocked(api.stats).mockResolvedValue(statsFixture);
  vi.mocked(api.status).mockResolvedValue(statusFixture);
});

async function renderRegister() {
  render(
    <MemoryRouter initialEntries={["/settings/companies"]}>
      <AppProviders>
        <ToastProvider>
          <CompaniesDataProvider>
            <CompaniesSection />
          </CompaniesDataProvider>
        </ToastProvider>
      </AppProviders>
    </MemoryRouter>,
  );
  await screen.findByRole("checkbox", { name: "Apple" });
  await act(async () => {});
}

describe("the register's rows", () => {
  it("draws every row when it first loads (the control)", async () => {
    await renderRegister();
    for (const slug of ["google", "apple", "amazon", "netflix", "microsoft"]) {
      expect(drawn).toContain(slug);
    }
  });

  it("a switch draws its own row while its write is out, and no other", async () => {
    vi.mocked(api.setCompanySelection).mockReturnValue(new Promise(() => {}));
    await renderRegister();
    drawn.length = 0;

    fireEvent.click(screen.getByRole("checkbox", { name: "Apple" }));
    await act(async () => {});

    expect(screen.getByRole("checkbox", { name: "Apple" })).toBeChecked();
    expect(new Set(drawn)).toEqual(new Set(["apple"]));
  });
});
