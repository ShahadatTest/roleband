import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { LineageDiff as LineageDiffData } from "../../api";
import { activate } from "../../copy/activate";
import { msg } from "../../test/msg";
import { LineageDiff } from "./LineageDiff";

describe("LineageDiff", () => {
  it("renders nothing for a null or empty diff", () => {
    const { container } = render(<LineageDiff diff={null} />);
    expect(container).toBeEmptyDOMElement();
    const { container: c2 } = render(<LineageDiff diff={{}} />);
    expect(c2).toBeEmptyDOMElement();
  });

  it("labels a title change", () => {
    const diff: LineageDiffData = { title: { from: "Staff SWE", to: "Staff SWE, Inference" } };
    render(<LineageDiff diff={diff} />);
    expect(screen.getByText("Title changed")).toBeInTheDocument();
    expect(screen.getByText("Staff SWE → Staff SWE, Inference")).toBeInTheDocument();
  });

  it("distinguishes a moved band from a newly disclosed one", () => {
    const moved: LineageDiffData = {
      disclosed_band: { from: [240000, 334000], to: [255000, 350000], currency: "USD" },
    };
    render(<LineageDiff diff={moved} />);
    expect(screen.getByText("Posted range moved")).toBeInTheDocument();

    const fresh: LineageDiffData = {
      disclosed_band: { from: null, to: [200000, 300000], currency: "USD" },
    };
    render(<LineageDiff diff={fresh} />);
    expect(screen.getByText("Range newly posted")).toBeInTheDocument();
  });

  it("shows a band and an estimate in the currency the posting stated", () => {
    const diff: LineageDiffData = {
      disclosed_band: { from: [60000, 80000], to: [65000, 85000], currency: "EUR" },
      comp_median: { from: 90000, to: 110000, currency: "GBP" },
    };
    render(<LineageDiff diff={diff} />);
    expect(screen.getByText("€60K–€80K → €65K–€85K")).toBeInTheDocument();
    expect(screen.getByText("£90K → £110K")).toBeInTheDocument();
    expect(screen.queryByText(/\$/)).not.toBeInTheDocument();
  });

  it("names an unknown end of a band without a currency sign", () => {
    const diff: LineageDiffData = { disclosed_band: { from: [null, 80000], to: [null, 85000], currency: "EUR" } };
    render(<LineageDiff diff={diff} />);
    expect(screen.getByText("—–€80K → —–€85K")).toBeInTheDocument();
  });

  it("summarizes location add/remove", () => {
    const diff: LineageDiffData = { locations: { added: ["London, UK"], removed: [] } };
    render(<LineageDiff diff={diff} />);
    expect(screen.getByText("Locations changed")).toBeInTheDocument();
    expect(screen.getByText(/added London, UK/)).toBeInTheDocument();
  });
});

describe("LineageDiff names codes the way the role page does", () => {
  afterEach(() => activate("en"));

  it("names a level change by the levels' names", () => {
    render(<LineageDiff diff={{ level_band: { from: "senior", to: "staff" } }} />);
    expect(screen.getByText(`${msg("taxonomy-band-senior")} → ${msg("taxonomy-band-staff")}`)).toBeInTheDocument();
  });

  it("names a pay basis change, and a posting that stated no band", () => {
    render(<LineageDiff diff={{ pay_basis: { from: null, to: "base" } }} />);
    expect(screen.getByText(`${msg("role-lineage-diff-not-disclosed")} → ${msg("vocab-pay-basis-base")}`)).toBeInTheDocument();
  });

  it("says both in Spanish, with no slug left over", async () => {
    await activate("es");
    expect(msg("taxonomy-band-senior")).not.toBe("Senior");
    render(<LineageDiff diff={{ level_band: { from: "senior", to: "staff" }, pay_basis: { from: "base", to: "total" } }} />);
    expect(screen.getByText(`${msg("taxonomy-band-senior")} → ${msg("taxonomy-band-staff")}`)).toBeInTheDocument();
    expect(screen.getByText(`${msg("vocab-pay-basis-base")} → ${msg("role-job-comp-panel-total-compensation")}`)).toBeInTheDocument();
    expect(screen.queryByText("senior → staff")).toBeNull();
    expect(screen.queryByText("base → total")).toBeNull();
  });
});
