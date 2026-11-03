import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Job, JobDetailRow } from "../../api";
import { activate } from "../../copy/activate";
import { msg } from "../../test/msg";
import { jobDetailRowFixture, jobFixture } from "../../test/fixtures";
import { ComparisonLedger } from "./ComparisonLedger";

vi.mock("../../context/JobWorkspace", () => ({ useJobActions: () => ({ openJob: () => {} }) }));

/* review.css lays the ledger's rows out as grids, and an engine that sees a
 * display change on a table part (WebKit) drops its table semantics. The roles
 * are stated on every part, so a screen reader keeps rows and columns. */
it("states table, row, header and cell roles on every part of the ledger", () => {
  const prior = { ...jobFixture, id: 1, title: "Staff Engineer, Platform" };
  const job = { ...jobFixture, id: 2, title: "Senior Staff Engineer, Platform" };
  render(<MemoryRouter><ComparisonLedger prior={prior} job={job} /></MemoryRouter>);

  const table = screen.getByRole("table");
  expect(table).toHaveAttribute("role", "table");
  const [head, ...body] = within(table).getAllByRole("row");
  expect(within(head).getAllByRole("columnheader")).toHaveLength(3);
  expect(body.length).toBeGreaterThan(1);
  for (const row of body) {
    expect(row).toHaveAttribute("role", "row");
    expect(within(row).getByRole("rowheader")).toHaveAttribute("role", "rowheader");
    for (const cell of within(row).getAllByRole("cell")) expect(cell).toHaveAttribute("role", "cell");
  }
  for (const part of table.querySelectorAll("thead, tbody")) expect(part).toHaveAttribute("role", "rowgroup");
});

describe("the ledger in the reader's language", () => {
  afterEach(() => activate("en"));

  const ledgerRow = (label: string) => screen.getByText(label, { selector: "th > span" }).closest("tr") as HTMLElement;
  const renderLedger = (prior: Job, job: Job) => render(<MemoryRouter><ComparisonLedger prior={prior} job={job} /></MemoryRouter>);

  it("names each posting's status and role group in Spanish, never the code", async () => {
    await activate("es");
    renderLedger(
      { ...jobFixture, id: 1, status: "open", family: "product_management" },
      { ...jobFixture, id: 2, status: "closed", family: "software_engineering" },
    );

    const status = ledgerRow(msg("duplicates-comparison-ledger-status"));
    expect(status).toHaveTextContent(msg("role-job-status-open"));
    expect(status).toHaveTextContent(msg("role-job-status-closed"));
    expect(status).not.toHaveTextContent(/\b(open|closed)\b/);

    const family = ledgerRow(msg("duplicates-comparison-ledger-family"));
    expect(family).toHaveTextContent(msg("vocab-role-product-management"));
    expect(family).toHaveTextContent(msg("vocab-role-software-engineering"));
    expect(family).not.toHaveTextContent(/product_management|software_engineering/);
  });

  it("shows a posted band in the currency it was posted in, and claims no currency the posting did not state", () => {
    const band = (currency: string | null): NonNullable<JobDetailRow["disclosed_comp"]> => ({
      disclosed: true, base_min: 150_000, base_max: 200_000, currency, bonus_pct: null, checked_at: null,
      confidence: "high", from_pay_field: false, pay_basis: "base", pay_period: "year", snippet: null,
    });
    renderLedger(jobDetailRowFixture({ id: 1, disclosed_comp: band("EUR") }), jobDetailRowFixture({ id: 2, disclosed_comp: band(null) }));

    const [euros, unstated] = within(ledgerRow(msg("duplicates-comparison-ledger-disclosed-band"))).getAllByRole("cell");
    expect(euros).toHaveTextContent("€150K–€200K");
    expect(euros).not.toHaveTextContent(/\$|EUR/);
    expect(unstated).toHaveTextContent("150K–200K");
    expect(unstated).not.toHaveTextContent(/\$|€/);
  });
});
