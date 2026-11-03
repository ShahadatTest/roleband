import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { BandBadge, LocBadge, MatchBadge } from "./JobBadges";
import { msg } from "../../test/msg";

/* The job row's read-only chip vocabulary. Each one carries a decision that
 * is easy to lose in a rewrite. */

describe("BandBadge", () => {
  it("shows the human band name, not the slug the API sends", () => {
    render(<BandBadge band="director_plus" />);
    expect(screen.getByText("Director+")).toBeInTheDocument();
    expect(screen.queryByText("director_plus")).not.toBeInTheDocument();
  });

  it("falls back to the raw band when the taxonomy adds one the UI has no label for", () => {
    render(<BandBadge band="fellow" />);
    expect(screen.getByText("fellow")).toBeInTheDocument();
  });

  it.each([
    ["staff", "ui-badge-accent"],
    ["principal", "ui-badge-principal"],
    ["director_plus", "ui-badge-director"],
    ["senior", "ui-badge-neutral"],
    ["fellow", "ui-badge-neutral"],
  ])("gives %s its band's hue, as a row tag", (band, tone) => {
    const { container } = render(<BandBadge band={band} />);
    const tag = container.querySelector(".ui-badge")!;
    expect(tag).toHaveClass("ui-badge-tag", tone);
  });

  it("never shows the placeholder Mid of a posting that names no level", () => {
    const { rerender } = render(<BandBadge band="mid" confidence="unconfirmed" basis="none" />);
    expect(screen.getByText("level not stated")).toBeInTheDocument();
    expect(screen.queryByText("Mid-level")).not.toBeInTheDocument();
    expect(screen.queryByText("level unconfirmed")).not.toBeInTheDocument();

    // Control: a Mid the title did state is still shown as Mid-level.
    rerender(<BandBadge band="mid" confidence="confirmed" basis="generic" />);
    expect(screen.getByText("Mid-level")).toBeInTheDocument();
    expect(screen.queryByText("level not stated")).not.toBeInTheDocument();
  });

  it("marks a level the title names but we cannot place, never as not stated and never by its guessed band", () => {
    render(<BandBadge band="staff" confidence="confirmed" basis="unmapped" />);
    expect(screen.getByText("level not mapped")).toBeInTheDocument();
    expect(screen.queryByText("level not stated")).not.toBeInTheDocument();
    expect(screen.queryByText("Staff")).not.toBeInTheDocument();
  });

  it("flags an inferred level ONLY when the confidence says unconfirmed", () => {
    const { rerender } = render(<BandBadge band="senior" confidence="unconfirmed" />);
    expect(screen.getByText("level unconfirmed")).toBeInTheDocument();

    rerender(<BandBadge band="senior" confidence="confirmed" />);
    expect(screen.queryByText("level unconfirmed")).not.toBeInTheDocument();

    rerender(<BandBadge band="senior" />);
    expect(screen.queryByText("level unconfirmed")).not.toBeInTheDocument();
  });
});

describe("LocBadge", () => {
  it("names the group, and falls back to the slug for one it does not know", () => {
    render(<LocBadge slug="silicon_valley" />);
    expect(screen.getByText("Silicon Valley")).toBeInTheDocument();

    render(<LocBadge slug="antarctica-hq" />);
    expect(screen.getByText("antarctica-hq")).toBeInTheDocument();
  });
});

describe("MatchBadge", () => {
  it("renders nothing at all without a textual match", () => {
    const { container, rerender } = render(<MatchBadge matchedVia={[]} />);
    expect(container).toBeEmptyDOMElement();

    rerender(<MatchBadge matchedVia={null} />);
    expect(container).toBeEmptyDOMElement();

    rerender(<MatchBadge />);
    expect(container).toBeEmptyDOMElement();
  });

  it("drops 'exact', because identity is the class chip's claim and not a retrieval source", () => {
    const { container } = render(<MatchBadge matchedVia={["exact"]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("names every remaining source, and says so in the title", () => {
    render(<MatchBadge matchedVia={["keyword", "exact", "fuzzy"]} />);
    expect(screen.getByText("Keyword · Fuzzy")).toBeInTheDocument();
    expect(screen.getByTitle(msg("jobs-matched-via", { sources: "keyword and fuzzy match" }))).toBeInTheDocument();
  });
});
