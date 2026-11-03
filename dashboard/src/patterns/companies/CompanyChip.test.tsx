import { fireEvent, render as rtlRender, screen, waitFor } from "@testing-library/react";
import { StrictMode } from "react";
import type { ReactElement } from "react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { CompanyCard } from "../../api";
import { api } from "../../api";
import { CompanyChip, __clearCompanyCardCache } from "./CompanyChip";
import { msg } from "../../test/msg";

vi.mock("../../api", () => ({ api: { companyCard: vi.fn() } }));

function render(ui: ReactElement, { strict = false }: { strict?: boolean } = {}) {
  const tree = <MemoryRouter initialEntries={["/"]}>{ui}</MemoryRouter>;
  return rtlRender(strict ? <StrictMode>{tree}</StrictMode> : tree);
}

function LocationProbe() {
  const loc = useLocation();
  return <div data-testid="location">{`${loc.pathname}${loc.search}`}</div>;
}

const card = (over: Partial<CompanyCard> = {}): CompanyCard => ({
  slug: "google",
  display_name: "Google",
  logo_url: null,
  brand_color: "#4285F4",
  ticker: "GOOG",
  is_public: true,
  has_profile: true,
  open_roles: 12,
  unfollowed: false,
  top_cities: [],
  price: 213.95,
  change_pct: 1.24,
  currency: "USD",
  price_as_of: "2026-07-13",
  ...over,
});

const cardFn = () => vi.mocked(api.companyCard);

describe("CompanyChip hover card", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    __clearCompanyCardCache();
    vi.useRealTimers();
  });

  it("carries the brand MARK beside the name in the line's ink — never a brand fill", () => {
    render(<CompanyChip slug="google" />);
    const chip = screen.getByRole("button", { name: msg("shared-company-chip-aria", { company: "Google" }) });
    // No inline paint: the ink comes from the line the chip sits on, so twenty
    // rows cannot put twenty full-chroma fills on one canvas. The mark
    // rests muted (no `is-brand`): hover lights it.
    expect(chip.getAttribute("style")).toBeNull();
    const mark = chip.querySelector(".ui-company-icon");
    expect(mark).not.toBeNull();
    expect(mark).not.toHaveClass("is-brand");
    expect(chip).toHaveTextContent("Google");
  });

  it("renders the company name as an accessible control", () => {
    cardFn().mockResolvedValue(card());
    render(<CompanyChip slug="google" />);
    expect(
      screen.getByRole("button", { name: msg("shared-company-chip-aria", { company: "Google" }) }),
    ).toBeInTheDocument();
  });

  it("reveals price, ticker, and open-role count on hover", async () => {
    cardFn().mockResolvedValue(card());
    render(<CompanyChip slug="google" />);

    fireEvent.mouseEnter(screen.getByRole("button").parentElement!);
    await waitFor(() => expect(cardFn()).toHaveBeenCalledWith("google"));

    expect(await screen.findByText("$213.95")).toBeInTheDocument();
    expect(screen.getByText("+1.24%")).toBeInTheDocument();
    expect(screen.getByText("GOOG")).toBeInTheDocument();
    expect(screen.getByText(msg("shared-company-open-roles", { count: 12 }))).toBeInTheDocument();
  });

  it("shows a price in the currency it trades in, and a fall with its sign", async () => {
    cardFn().mockResolvedValue(card({ price: 1234.5, currency: "EUR", change_pct: -0.5 }));
    render(<CompanyChip slug="google" />);
    fireEvent.mouseEnter(screen.getByRole("button").parentElement!);
    expect(await screen.findByText("€1,234.50")).toBeInTheDocument();
    expect(screen.getByText("-0.50%")).toBeInTheDocument();
    expect(screen.queryByText(/\$/)).toBeNull();
  });

  it("says an unfollowed company's roles are not on the Board, instead of a count", async () => {
    // Its count is the Board's, 0, and "No open roles right now"
    // would claim the company is not hiring when the user just does not follow it.
    cardFn().mockResolvedValue(card({ open_roles: 0, unfollowed: true }));
    render(<CompanyChip slug="google" />);
    fireEvent.mouseEnter(screen.getByRole("button").parentElement!);
    expect(
      await screen.findByText(msg("shared-company-not-followed", { company: "Google" })),
    ).toBeInTheDocument();
    expect(screen.queryByText(msg("shared-company-no-open-roles"))).toBeNull();
  });

  it("shows the busiest hiring cities when the card carries them", async () => {
    cardFn().mockResolvedValue(
      card({ top_cities: ["Mountain View, CA", "London, UK"] }),
    );
    render(<CompanyChip slug="google" />);
    fireEvent.mouseEnter(screen.getByRole("button").parentElement!);

    expect(
      await screen.findByText("Mountain View, CA · London, UK"),
    ).toBeInTheDocument();
  });

  it("portals the card to <body> so it escapes the job row's stacking context", async () => {
    // Regression: each job row establishes a stacking context (entrance transform),
    // so a card rendered inside the row was painted under later sibling rows. It
    // must live directly under <body>.
    cardFn().mockResolvedValue(card());
    render(<CompanyChip slug="google" />);
    fireEvent.mouseEnter(screen.getByRole("button").parentElement!);

    await screen.findByText("$213.95");
    const portal = document.querySelector(".co-card-portal");
    expect(portal).not.toBeNull();
    expect(portal!.parentElement).toBe(document.body);
  });

  it("still opens under StrictMode (the mount-cleanup must not pin it closed)", async () => {
    // Regression: an `alive` ref set only in cleanup was flipped false by
    // StrictMode's simulated unmount and never reset, silently swallowing every
    // setState — the card never appeared in the real (StrictMode) app.
    cardFn().mockResolvedValue(card());
    render(<CompanyChip slug="google" />, { strict: true });

    fireEvent.mouseEnter(screen.getByRole("button").parentElement!);
    expect(await screen.findByText("$213.95")).toBeInTheDocument();
    expect(screen.getByText(msg("shared-company-open-roles", { count: 12 }))).toBeInTheDocument();
  });

  it("does not show a price line for a private company", async () => {
    cardFn().mockResolvedValue(
      card({ slug: "openai", display_name: "OpenAI", is_public: false, ticker: null, price: null }),
    );
    render(<CompanyChip slug="openai" />);
    fireEvent.mouseEnter(screen.getByRole("button").parentElement!);
    expect(await screen.findByText("12 open roles")).toBeInTheDocument();
    expect(screen.queryByText(/\$/)).not.toBeInTheDocument();
  });

  it("navigates to the company profile on click", async () => {
    cardFn().mockResolvedValue(card());
    render(
      <>
        <CompanyChip slug="google" />
        <LocationProbe />
      </>,
    );
    fireEvent.click(screen.getByRole("button"));
    await waitFor(() =>
      expect(screen.getByTestId("location")).toHaveTextContent("/company/google"),
    );
  });

  it("stops the click from bubbling to a clickable parent (the job row)", () => {
    cardFn().mockResolvedValue(card());
    const onRowClick = vi.fn();
    render(
      <div onClick={onRowClick}>
        <CompanyChip slug="google" />
      </div>,
    );
    fireEvent.click(screen.getByRole("button"));
    expect(onRowClick).not.toHaveBeenCalled();
  });

  it("shares one request across repeated hovers of the same company", async () => {
    cardFn().mockResolvedValue(card());
    render(<CompanyChip slug="google" />);
    const wrap = screen.getByRole("button").parentElement!;
    fireEvent.mouseEnter(wrap);
    await waitFor(() => expect(cardFn()).toHaveBeenCalledTimes(1));
    fireEvent.mouseLeave(wrap);
    fireEvent.mouseEnter(wrap);
    // The module-level cache means no second fetch.
    expect(cardFn()).toHaveBeenCalledTimes(1);
  });
});
