/**
 * The comp panel's job is to be honest about two different things at once: what kind of
 * money you get, and how sure we are of each part. These tests pin the honesty.
 *
 * The one that matters most: an `unclear` basis must NOT be split. Anthropic states a
 * figure and never says whether it is base or total; a panel that confidently breaks it
 * into cash/bonus/equity would be inventing a fact the posting does not state.
 */
import { calendarDay } from "../../copy/format";
import { render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { Job, JobCompPackage } from "../../api";
import JobCompPanel from "./JobCompPanel";
import { compPackageFixture, jobFixture } from "../../test/fixtures";
import { msg } from "../../test/msg";
import { activate } from "../../copy/activate";

/** `null` is a row with no package at all — a list row, which never carries one.
 *  The detail route itself always sends an object. */
function withPackage(pkg: JobCompPackage | null): Job {
  return pkg === null ? { ...jobFixture } : { ...jobFixture, comp_package: pkg };
}

// Google job 879: base is stated, and so is the 25% bonus target. Built on the
// complete fixture, so keys this case is not about hold what the route sends.
const GOOGLE: JobCompPackage = compPackageFixture({
  state: "band",
  basis: "base",
  currency: "USD",
  pay_period: "year",
  stated: { low: 240000, high: 334000 },
  bonus_pct: 0.25,
  components: [
    { kind: "base", low: 240000, high: 334000, provenance: "stated" },
    { kind: "bonus", low: 60000, high: 83500, provenance: "stated" },
    { kind: "equity", low: 292289, high: 406769, provenance: "estimated" },
  ],
  total: { low: 592289, high: 824269, provenance: "estimated" },
  estimate: { low: 391162, median: 460191, high: 529219, provenance: "Google L6 estimated median" },
  split_source: "cross_family",
  no_split_reason: null,
  snippet: "US: $240000 - $334000 (USD) + 25% bonus target + equity",
  confidence: "high",
});

// Anthropic job 1: a stated figure whose meaning the employer withheld.
const ANTHROPIC: JobCompPackage = compPackageFixture({
  state: "band",
  basis: "unclear",
  currency: "USD",
  pay_period: "year",
  stated: { low: 210000, high: 260000 },
  bonus_pct: null,
  components: [],
  total: null,
  estimate: { low: 478826, median: 563325, high: 647823, provenance: "Anthropic Senior estimated median" },
  split_source: "measured",
  no_split_reason: "basis_unclear",
  snippet: "Annual Salary: $210,000—$260,000 USD",
  confidence: "high",
});

const NETFLIX: JobCompPackage = {
  ...ANTHROPIC,
  basis: "total",
  stated: { low: 440000, high: 725000 },
  total: { low: 440000, high: 725000, provenance: "stated" },
  estimate: { low: 400000, median: 500000, high: 600000, provenance: "Netflix Staff estimated median" },
  no_split_reason: "employee_election",
  snippet: "The range for this role is $440,000.00 - $725,000.00.",
};

describe("JobCompPanel", () => {
  it("labels the employer-stated base as stated and the equity as estimated", () => {
    render(<JobCompPanel job={withPackage(GOOGLE)} />);

    // The guaranteed-cash line is the whole point of the panel.
    const guaranteed = document.querySelector(".pkg-guaranteed") as HTMLElement;
    expect(within(guaranteed).getByText("Base")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "About the posted base salary" }))
      .toHaveAccessibleDescription("Base salary stated in the posting.");
    expect(screen.queryByText(/of it is base salary/)).not.toBeInTheDocument();
    // The stated band shows in both the guaranteed-cash line and the legend.
    expect(screen.getAllByText("$240K–$334K").length).toBeGreaterThan(0);

    // Every component carries its own provenance, and they are not all the same.
    expect(screen.getAllByText("stated").length).toBeGreaterThanOrEqual(2); // base + bonus
    expect(screen.getAllByText("estimated").length).toBeGreaterThanOrEqual(1); // equity
  });

  it("says the bonus percentage came from the posting", () => {
    render(<JobCompPanel job={withPackage(GOOGLE)} />);
    expect(screen.getByText("25% of base, stated")).toBeInTheDocument();
  });

  it("refuses to split a band whose basis the employer never stated", () => {
    render(<JobCompPanel job={withPackage(ANTHROPIC)} />);

    expect(screen.getByText("basis not stated")).toBeInTheDocument();
    expect(
      screen.getByText(/doesn't say whether this figure is base salary or total compensation/),
    ).toBeInTheDocument();
    // ...and it must not have invented a breakdown to fill the bar.
    expect(screen.queryByText("Base")).not.toBeInTheDocument();
    expect(screen.queryByText("Equity")).not.toBeInTheDocument();
    // The stated figure and our independent estimate are both still shown.
    expect(screen.getAllByText(/\$210K–\$260K/).length).toBeGreaterThan(0);
    expect(screen.getByText(/Independent estimate of total compensation/)).toBeInTheDocument();
    expect(screen.getAllByText("$479K–$648K").length).toBeGreaterThan(0);
  });

  it("names the posting's own employer for an employee-selected mix, never a fixed one", () => {
    // The reason comes from the atlas (`equity_rule`), not from this panel: a
    // second employer with the rule is named as itself.
    render(<JobCompPanel job={{ ...withPackage(NETFLIX), company: "spotify" }} />);
    expect(screen.getByText(/^Spotify states this as total annual compensation/)).toBeInTheDocument();
    expect(screen.queryByText(/Netflix states/)).not.toBeInTheDocument();
  });

  it("explains Netflix total compensation and employee-selected cash/options mix", () => {
    render(<JobCompPanel job={{ ...withPackage(NETFLIX), company: "netflix" }} />);
    expect(screen.getByText(/^Netflix states this as total annual compensation/)).toBeInTheDocument();

    expect(screen.getByText("Posted total compensation")).toBeInTheDocument();
    expect(screen.getByText("employee-selected mix")).toBeInTheDocument();
    expect(screen.getByText(/choose how much is salary versus stock options/)).toBeInTheDocument();
    expect(screen.queryByText(/never says whether it is base salary/)).not.toBeInTheDocument();
    expect(screen.queryByText("Base")).not.toBeInTheDocument();
  });

  it("never labels our own estimate as a figure the employer stated", () => {
    /**
     * With an `unclear` basis there is no package, so the headline falls back to our
     * ESTIMATE while the fixture employer stated $210K-$260K. The label has to describe
     * the number printed under it, or the panel lies in exactly the way it exists to
     * prevent.
     */
    render(<JobCompPanel job={withPackage(ANTHROPIC)} />);

    expect(screen.getByText("Estimated total compensation")).toBeInTheDocument();
    expect(screen.queryByText("Stated by the employer")).not.toBeInTheDocument();

    // The employer's actual figure is still shown, just not as the headline.
    expect(screen.getAllByText(/\$210K–\$260K/).length).toBeGreaterThan(0);
  });

  it("flags a split borrowed from another job family instead of passing it off as measured", () => {
    render(<JobCompPanel job={withPackage(GOOGLE)} />);
    expect(screen.getByText("Split from another discipline")).toBeInTheDocument();
  });

  it("distinguishes 'employer stated nothing' from 'we have not looked yet'", () => {
    const checked: JobCompPackage = {
      ...GOOGLE,
      state: "none_stated",
      basis: null,
      stated: null,
      bonus_pct: null,
      snippet: null,
      components: [
        { kind: "base", low: 160000, high: 200000, provenance: "estimated" },
        { kind: "equity", low: 200000, high: 260000, provenance: "estimated" },
      ],
    };
    const { unmount } = render(<JobCompPanel job={withPackage(checked)} />);
    expect(screen.getByText(/posts no range/)).toBeInTheDocument();
    expect(screen.queryByText(/hasn't been checked/)).not.toBeInTheDocument();
    unmount();

    const unchecked: JobCompPackage = { ...checked, state: "unchecked" };
    render(<JobCompPanel job={withPackage(unchecked)} />);
    expect(screen.getByText(/posting hasn't been checked/)).toBeInTheDocument();
    expect(screen.queryByText(/posts no range/)).not.toBeInTheDocument();
  });

  it("does not annualize an hourly rate", () => {
    const hourly: JobCompPackage = {
      ...ANTHROPIC,
      basis: "base",
      pay_period: "hour",
      stated: { low: 100, high: 150 },
      no_split_reason: "hourly",
      estimate: null,
    };
    render(<JobCompPanel job={withPackage(hourly)} />);
    expect(screen.getByText("hourly rate")).toBeInTheDocument();
    expect(screen.getByText(/shown as stated/)).toBeInTheDocument();
  });

  // The server serves a period checked against the amount's size.
  it("shows a figure whose period it could not tell with no unit, and never as base", () => {
    const unclear: JobCompPackage = {
      ...ANTHROPIC,
      basis: "base",
      pay_period: "unclear",
      stated: { low: 150000, high: 200000 },
      no_split_reason: "period_unclear",
      estimate: null,
      snippet: "Hourly rate: $150,000 - $200,000",
    };
    const { container } = render(<JobCompPanel job={withPackage(unclear)} />);
    expect(screen.getByText("period unclear")).toBeInTheDocument();
    expect(screen.getByText(/by the hour, the month or the year/)).toBeInTheDocument();
    expect(container).not.toHaveTextContent("/ hr");
    expect(container).not.toHaveTextContent("/ yr");
    expect(screen.queryByText("Base")).not.toBeInTheDocument();
  });

  it("gives a monthly rate its own unit and never annualizes it", () => {
    const monthly: JobCompPackage = {
      ...ANTHROPIC,
      basis: "base",
      currency: "EUR",
      pay_period: "month",
      stated: { low: 4500, high: 5500 },
      no_split_reason: "monthly",
      estimate: null,
    };
    const { container } = render(<JobCompPanel job={withPackage(monthly)} />);
    expect(screen.getByText("monthly rate")).toBeInTheDocument();
    expect(container).toHaveTextContent("/ mo");
    expect(container).not.toHaveTextContent("/ yr");
    // In the posting's own currency, never a dollar sign on euros.
    expect(container.querySelector(".pkg-unclear-n")).toHaveTextContent("€5K–€6K");
  });

  it("writes a stated band and the pay floor beside it in one currency and one format", () => {
    const pounds: JobCompPackage = { ...GOOGLE, currency: "GBP" };
    render(<JobCompPanel job={{
      ...withPackage(pounds),
      pay_floor_check: { verdict: "clears", amount: 100000, currency: "GBP", basis: "base" },
    }} />);
    expect(screen.getByTestId("pkg-floor")).toHaveTextContent("Clears your £100K minimum base");
    const guaranteed = document.querySelector(".pkg-guaranteed");
    expect(guaranteed).toHaveTextContent(/^£\d+K–£\d+K/);
    expect(guaranteed).not.toHaveTextContent("$");
  });

  it("labels our yearly estimate per year even when the posting's rate is hourly", () => {
    // The headline is the estimate here, so it must not take the posting's "/ hr".
    const hourly: JobCompPackage = {
      ...ANTHROPIC,
      basis: "base",
      pay_period: "hour",
      stated: { low: 100, high: 150 },
      no_split_reason: "hourly",
    };
    const { container } = render(<JobCompPanel job={withPackage(hourly)} />);
    expect(container.querySelector(".pkg-head .pkg-per")).toHaveTextContent("/ yr");
    expect(container.querySelector(".pkg-unclear-n")).toHaveTextContent("/ hr");
  });

  // The server decides the verdict; the panel says it in one line.
  it.each([
    ["clears", "Clears your $250K minimum base"],
    ["straddles", "Your $250K minimum base falls inside this range"],
    ["below", "Below your $250K minimum base"],
  ] as const)("says how the stated pay compares with the pay floor: %s", (verdict, line) => {
    render(<JobCompPanel job={{ ...withPackage(GOOGLE), pay_floor_check: { verdict, amount: 250000, currency: "USD", basis: "base" } }} />);
    expect(screen.getByTestId("pkg-floor")).toHaveTextContent(line);
  });

  it("says nothing about the pay floor when the server sends no comparison", () => {
    render(<JobCompPanel job={{ ...withPackage(GOOGLE), pay_floor_check: null }} />);
    expect(screen.queryByTestId("pkg-floor")).toBeNull();
    expect(screen.queryByText(/minimum base/)).toBeNull();
  });

  it("says a band came from the posting's pay field, and quotes nothing it did not say", () => {
    const fromField = { ...withPackage({ ...GOOGLE, snippet: null }) };
    const job = { ...fromField, disclosed_comp: { ...fromField.disclosed_comp!, snippet: null, from_pay_field: true } };
    render(<JobCompPanel job={job} />);
    expect(screen.getByTestId("pkg-from-field")).toHaveTextContent("From the posting's compensation field, not its text.");
    expect(screen.queryByText("The employer's exact words")).toBeNull();
  });

  it("shows the grounded quote so the claim can be checked against the posting", () => {
    render(<JobCompPanel job={withPackage(GOOGLE)} />);
    expect(screen.getByText("The employer's exact words")).toBeInTheDocument();
    expect(
      screen.getByText("US: $240000 - $334000 (USD) + 25% bonus target + equity"),
    ).toBeInTheDocument();
  });

  it("degrades to a placeholder rather than throwing when there is no package", () => {
    render(<JobCompPanel job={withPackage(null)} />);
    expect(screen.getByText(/No compensation data/)).toBeInTheDocument();
  });

  it("states how the company builds the offer when that is verified, and nothing when it is not", () => {
    // Amazon: no bonus, back-loaded vest bridged by sign-on, base cap — all verified facts.
    const amazon: JobCompPackage = {
      ...GOOGLE,
      bonus_pct: null,
      policy: {
        verified: true,
        bonus_rule: "none",
        equity_rule: "tc_target_minus_base",
        vesting: "5/15/40/40",
        sign_on_bridges_vesting: true,
        base_cap_usd: 350000,
        annual_refresh: true,
        estimated: ["bonus_rule", "equity_rule", "vesting", "sign_on_bridges_vesting", "base_cap_usd"],
        unknown: [],
      },
    };
    const { unmount } = render(<JobCompPanel job={withPackage(amazon)} />);
    const line = screen.getByTestId("pkg-policy");
    expect(line).toHaveTextContent("vests 5/15/40/40, sign-on cash bridges years 1–2");
    expect(line).toHaveTextContent("no annual bonus");
    expect(line).toHaveTextContent("base capped at $350K");
    unmount();

    // Unverified: every field null. Must render NO policy line — null is "unknown",
    // and a default sentence here would be exactly the invented fact the table forbids.
    const unverified: JobCompPackage = {
      ...GOOGLE,
      policy: {
        verified: false,
        bonus_rule: null,
        equity_rule: null,
        vesting: null,
        sign_on_bridges_vesting: false,
        base_cap_usd: null,
        annual_refresh: null,
        estimated: [],
        unknown: [],
      },
    };
    render(<JobCompPanel job={withPackage(unverified)} />);
    expect(screen.queryByTestId("pkg-policy")).not.toBeInTheDocument();
  });

  // --- one headline, market median as a reading on it (docs/pay.md) ---------------

  it("keeps the estimate without displaying source traceability", () => {
    render(<JobCompPanel job={withPackage({ ...GOOGLE, split_source: "heuristic",
      estimate: { ...GOOGLE.estimate!, provenance: "Google L6 reported median" },
    })} />);
    expect(screen.queryByText(/reported|Google L6/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Splits from/)).not.toBeInTheDocument();
  });

  it("shows the market median as a reading on the headline, not a second headline", () => {
    render(<JobCompPanel job={withPackage({ ...GOOGLE, market_gap: { ratio: 1.04, verdict: "consistent" } })} />);

    // One headline, and it is the package total.
    expect(screen.getByText("Estimated total compensation")).toBeInTheDocument();
    expect(screen.queryByText("Market estimate")).not.toBeInTheDocument();

    const market = screen.getByTestId("pkg-market");
    expect(market).toHaveTextContent("Market median at this level");
    expect(market).toHaveTextContent("$460K");
    expect(market).not.toHaveTextContent("Google L6 estimated median");
    expect(market).not.toHaveTextContent(/sign the level/);
  });

  it("warns when the package and the market median disagree past the tolerance", () => {
    render(
      <JobCompPanel
        job={withPackage({ ...GOOGLE, market_gap: { ratio: 1.71, verdict: "diverges" } })}
      />,
    );

    const market = screen.getByTestId("pkg-market");
    expect(market).toHaveTextContent("1.71×");
    expect(market).toHaveTextContent(/level or the discipline is wrong/);
  });

  it("says nothing about the market when there is no estimate to compare", () => {
    render(
      <JobCompPanel
        job={withPackage({ ...GOOGLE, estimate: null, market_gap: null })}
      />,
    );

    expect(screen.queryByTestId("pkg-market")).not.toBeInTheDocument();
  });

  // --- posted band vs measured base (docs/pay.md) ---------------------------------

  it("cautions that the level may be wrong when the posted band sits above the measured base", () => {
    const job = withPackage({
      ...GOOGLE,
      split_source: "measured",
      reconciliation: { measured_base: 171000, ratio_high: 1.63, verdict: "stated_above_measured" },
    });
    render(<JobCompPanel job={job} />);

    const caution = screen.getByTestId("pkg-reconciliation");
    expect(caution).toHaveTextContent(/The posted range sits well above/);
    expect(caution).toHaveTextContent(/the level may be higher/);
    // The badge still says WHERE the ratios came from (a fact that must not be
    // rewritten), but it does not read as confident.
    const badge = screen.getByText("Measured split");
    expect(badge).toHaveClass("split-src-suspect");
  });

  it("cautions in the other direction too", () => {
    const job = withPackage({
      ...GOOGLE,
      split_source: "measured",
      reconciliation: { measured_base: 400000, ratio_high: 0.6, verdict: "stated_below_measured" },
    });
    render(<JobCompPanel job={job} />);

    expect(screen.getByTestId("pkg-reconciliation")).toHaveTextContent(/the level may be lower/);
  });

  it("says nothing when the posted band and the measured base agree", () => {
    const job = withPackage({
      ...GOOGLE,
      split_source: "measured",
      reconciliation: { measured_base: 272333, ratio_high: 1.23, verdict: "consistent" },
    });
    render(<JobCompPanel job={job} />);

    expect(screen.queryByTestId("pkg-reconciliation")).not.toBeInTheDocument();
    expect(screen.getByText("Measured split")).not.toHaveClass("split-src-suspect");
  });

  it("says nothing when there is no measurement to reconcile against", () => {
    const job = withPackage({
      ...GOOGLE,
      reconciliation: { measured_base: null, ratio_high: null, verdict: null },
    });
    render(<JobCompPanel job={job} />);

    expect(screen.queryByTestId("pkg-reconciliation")).not.toBeInTheDocument();
  });
});

describe("a base-only estimate", () => {
  const BASE_ONLY: JobCompPackage = compPackageFixture({
    state: "none_stated",
    components: [{ kind: "base", low: 170000, high: 230000, provenance: "estimated" }],
    total: null,
    estimate: null,
    split_source: null,
    base_estimate: { low: 170000, median: 200000, high: 230000, provider: "builtin", as_of: null },
  });

  it("says it is the base, why it stands alone, and that it is RoleBand's own data", () => {
    render(<JobCompPanel job={withPackage(BASE_ONLY)} />);
    expect(screen.getByText(msg("role-job-comp-panel-estimated-base"))).toBeInTheDocument();
    const note = screen.getByTestId("comp-base-only");
    expect(note).toHaveTextContent(msg("shared-pay-est-base-hint"));
    expect(note).toHaveTextContent(msg("role-job-comp-panel-from-roleband-data"));
    expect(screen.queryByText(msg("role-job-comp-panel-estimated-total-comp"))).toBeNull();
  });

  it("names no source it is not: another provider's base carries no RoleBand label", () => {
    render(<JobCompPanel job={withPackage({ ...BASE_ONLY, base_estimate: { ...BASE_ONLY.base_estimate!, provider: "manual" } })} />);
    expect(screen.getByTestId("comp-base-only")).not.toHaveTextContent(msg("role-job-comp-panel-from-roleband-data"));
  });
});

describe("a stated base outside US pay, with RoleBand answering", () => {
  it("is shown whole, names RoleBand's US data and no plugin, and keeps the offer policy", () => {
    const LONDON: JobCompPackage = compPackageFixture({
      state: "band", basis: "base", currency: "GBP", pay_period: "year",
      stated: { low: 90000, high: 130000 }, components: [], total: null, split_source: null,
      no_split_reason: "not_us_pay",
      policy: {
        verified: true, bonus_rule: "pct_of_base", equity_rule: "dollar_grant_by_level", vesting: "25/25/25/25",
        sign_on_bridges_vesting: false, base_cap_usd: null, annual_refresh: true, estimated: [], unknown: [],
      },
    });
    render(<JobCompPanel job={withPackage(LONDON)} />);
    const note = document.querySelector<HTMLElement>(".pkg-unclear")!;
    expect(note).toHaveTextContent(/£90K/);
    expect(note).toHaveTextContent(msg("role-job-comp-panel-split-not-reported"));
    expect(note).toHaveTextContent(msg("role-job-comp-panel-roleband-splits-us-pay-only"));
    expect(note).not.toHaveTextContent(/plugin/i);
    expect(document.querySelector(".pkg-bar")).toBeNull();
    expect(screen.getByTestId("pkg-policy")).toBeInTheDocument();
  });
});

describe("a plugin's figure with no split of its own", () => {
  const PLUGIN_TOTAL: JobCompPackage = compPackageFixture({
    state: "none_stated",
    components: [],
    total: null,
    estimate: { low: 793050, median: 933000, high: 1072950, provenance: "Google L7 estimated median" },
    split_source: null,
    no_split_reason: "plugin_without_split",
    policy: null,
  });

  it("shows the plugin's figure whole, with no bar, and says why it is not split", () => {
    render(<JobCompPanel job={withPackage(PLUGIN_TOTAL)} />);
    expect(screen.getByText(msg("role-job-comp-panel-estimated-total-comp"))).toBeInTheDocument();
    const note = screen.getByTestId("pkg-no-split");
    expect(note).toHaveTextContent(msg("role-job-comp-panel-split-not-reported"));
    expect(note).toHaveTextContent(msg("role-job-comp-panel-the-plugin-reports-no-split"));
    // No segment of ours under it: no base, bonus or equity label anywhere.
    expect(screen.queryByText(msg("role-job-comp-panel-estimated-split"))).toBeNull();
    expect(document.querySelector(".pkg-bar")).toBeNull();
    // Our offer policy rides only on our figures.
    expect(screen.queryByTestId("pkg-policy")).toBeNull();
  });

  it("a company the plugin has not read says so, never 'no estimate' or a split not reported", () => {
    const unread = { plugin: "ladder", plugin_name: "Example ladder data", covered: false };
    const empty = { ...PLUGIN_TOTAL, estimate: null, no_split_reason: null };
    const { unmount } = render(<JobCompPanel job={{ ...withPackage(empty), pay_source: unread }} />);
    expect(screen.getByText(msg("shared-pay-not-covered", { plugin: "Example ladder data" }))).toBeInTheDocument();
    expect(screen.queryByText(msg("role-job-comp-panel-no-estimate-available"))).toBeNull();
    unmount();

    render(<JobCompPanel job={{ ...withPackage({
      ...empty, state: "band", basis: "base", currency: "USD", pay_period: "year",
      stated: { low: 240000, high: 334000 }, no_split_reason: "plugin_not_covered",
    }), pay_source: unread }} />);
    expect(screen.getByText(msg("role-job-comp-panel-not-read-yet"))).toBeInTheDocument();
    expect(screen.getByText(msg("shared-pay-not-covered-hint", { plugin: "Example ladder data" }))).toBeInTheDocument();
    expect(screen.queryByText(msg("role-job-comp-panel-split-not-reported"))).toBeNull();
  });

  it("the plugin's figure is never called ours, and its raw provenance is not shown", () => {
    const plugin = { plugin: "ladder", plugin_name: "Example ladder data", covered: true };
    const stated = { ...PLUGIN_TOTAL, state: "band" as const, basis: "base" as const, currency: "USD",
                     pay_period: "year" as const, stated: { low: 240000, high: 334000 } };
    const { unmount } = render(<JobCompPanel job={{ ...withPackage(stated), pay_source: plugin }} />);
    expect(screen.queryByText(/Independent estimate/)).toBeNull();
    expect(document.querySelector(".pkg-vs")).toHaveTextContent(/^Estimated total compensation:/);
    expect(screen.queryByText(/estimated median/)).toBeNull();
    unmount();

    const ours = { plugin: null, plugin_name: null, covered: true };
    render(<JobCompPanel job={{ ...withPackage(stated), pay_source: ours }} />);
    expect(screen.getByText(/Independent estimate/)).toBeInTheDocument();
    expect(screen.queryByText(/estimated median/)).not.toBeInTheDocument();
  });

  it("a company it has read with no figure for this role keeps 'no estimate'", () => {
    const read = { plugin: "ladder", plugin_name: "Example ladder data", covered: true };
    render(<JobCompPanel job={{ ...withPackage({ ...PLUGIN_TOTAL, estimate: null, no_split_reason: null }),
                                pay_source: read }} />);
    expect(screen.getByText(msg("role-job-comp-panel-no-estimate-available"))).toBeInTheDocument();
  });

  it("a stated base under such a plugin is shown as the employer stated it, unsplit", () => {
    render(<JobCompPanel job={withPackage({
      ...PLUGIN_TOTAL, state: "band", basis: "base", currency: "USD", pay_period: "year",
      stated: { low: 240000, high: 334000 },
    })} />);
    expect(screen.queryByTestId("pkg-no-split")).toBeNull();
    expect(screen.getByText(msg("role-job-comp-panel-split-not-reported"))).toBeInTheDocument();
    expect(screen.getByText(msg("role-job-comp-panel-the-plugin-reports-no-split"))).toBeInTheDocument();
  });
});

// --- where the split came from, named by its wire value ---------------------------------

describe("split source chip", () => {
  // Each value composes its own class, the one its rule paints
  // (design/dead-rules.test.ts holds every value to a rule).
  it.each(["measured", "cross_family", "heuristic"] as const)("a %s split wears split-src-%s", (source) => {
    render(<JobCompPanel job={withPackage({ ...GOOGLE, split_source: source })} />);
    const chip = document.querySelector(".split-src");
    expect(chip).not.toBeNull();
    expect(chip).toHaveClass(`split-src-${source}`);
  });
});

describe("who supplied the split", () => {
  const MEASURED = { ...GOOGLE, split_source: "measured" as const };

  it("names the plugin answering pay, and the date its rung is as of", () => {
    const job = { ...withPackage({ ...MEASURED, split_provider: "levels-plugin", split_as_of: "2026-10-01" }),
      pay_source: { ...jobFixture.pay_source!, plugin: "levels-plugin", plugin_name: "Levels", covered: true } };
    render(<JobCompPanel job={job} />);
    expect(screen.getByTestId("comp-split-from")).toHaveTextContent(`Split from Levels, as of ${calendarDay("2026-10-01")}.`);
  });

  it("names RoleBand's own data for a split of ours, without a date it does not have", () => {
    render(<JobCompPanel job={withPackage({ ...MEASURED, split_provider: "builtin", split_as_of: null })} />);
    expect(screen.getByTestId("comp-split-from")).toHaveTextContent("Split from built-in data.");
  });

  it("says nothing where no measured split was read", () => {
    render(<JobCompPanel job={withPackage({ ...MEASURED, split_provider: null, split_as_of: null })} />);
    expect(screen.queryByTestId("comp-split-from")).toBeNull();
  });
});

describe("the panel's own words, in the reader's language", () => {
  afterEach(() => activate("en"));

  it("tags each part stated or estimated in Spanish, in the legend and on the bar", async () => {
    await activate("es");
    render(<JobCompPanel job={withPackage(GOOGLE)} />);

    const legend = document.querySelector(".pkg-legend") as HTMLElement;
    expect(within(legend).getAllByText(msg("role-job-comp-panel-stated"))).toHaveLength(2); // base + bonus
    expect(within(legend).getAllByText(msg("role-job-comp-panel-estimated"))).toHaveLength(1); // equity
    expect(within(legend).queryByText("stated")).toBeNull();
    expect(within(legend).queryByText("estimated")).toBeNull();

    // The bar is read aloud and hovered: each part ends in the same word, never the API's code.
    const bar = screen.getByRole("img", { name: /;/ });
    const spoken = bar.getAttribute("aria-label") ?? "";
    expect(spoken.split("; ").map((part) => part.split(" ").pop())).toEqual([
      msg("role-job-comp-panel-stated"), msg("role-job-comp-panel-stated"), msg("role-job-comp-panel-estimated"),
    ]);
    const titles = [...bar.querySelectorAll(".pkg-seg")].map((seg) => seg.getAttribute("title") ?? "");
    expect(titles.map((title) => title.split(", ").pop())).toEqual([
      msg("role-job-comp-panel-stated"), msg("role-job-comp-panel-stated"), msg("role-job-comp-panel-estimated"),
    ]);
    expect(`${spoken} ${titles.join(" ")}`).not.toMatch(/\b(stated|estimated)\b/);
  });

  it("names an employee-selected mix in Spanish", async () => {
    await activate("es");
    render(<JobCompPanel job={{ ...withPackage(NETFLIX), company: "netflix" }} />);
    expect(screen.getByText(msg("role-job-comp-panel-employee-selected-mix"))).toHaveClass("pkg-tag-warn");
    expect(screen.queryByText("employee-selected mix")).toBeNull();
  });

  it("names the doubted level as the catalog writes it, never recased", () => {
    const job = withPackage({
      ...GOOGLE,
      split_source: "measured",
      reconciliation: { measured_base: 171000, ratio_high: 1.63, verdict: "stated_above_measured" },
    });
    render(<JobCompPanel job={{ ...job, level_band: "staff" }} />);
    expect(screen.getByTestId("pkg-reconciliation")).toHaveTextContent(
      msg("role-job-comp-panel-posted-band-sits-well-above", { band: msg("taxonomy-band-staff") }),
    );
  });
});
