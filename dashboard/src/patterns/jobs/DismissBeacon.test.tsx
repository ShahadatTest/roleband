import type { Job } from "../../api";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { useRef, useState } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { jobFixture } from "../../test/fixtures";
import { DismissBeacon } from "./DismissBeacon";
import { msg } from "../../test/msg";

/* The way-back beacon's contract: it sits in
 * the margin level with the seam the row left, the pill IS the undo — one
 * click — and its reveal names the role and carries Undo for where there is
 * no hover. It offers no standing rule: that decision lives in the
 * Not-for-me lens. Rendered against a real host with a real seam element,
 * because "level with" is a claim about the anchor. */

/* As on the Board: the row is there first, and the seam + beacon appear on
 * the dismissal — a beacon never mounts before its host. */
function Host({ onUndo }: { onUndo: (job: Job) => void }) {
  const host = useRef<HTMLDivElement>(null);
  const [gone, setGone] = useState(false);
  return (
    <div ref={host} className="job-margin-host">
      <article className="job-row">Other role</article>
      {gone ? (
        <div className="job-seam" data-seam-for={jobFixture.id} />
      ) : (
        <article className="job-row">
          {jobFixture.title}
          <button type="button" onClick={() => setGone(true)}>Not for me</button>
        </article>
      )}
      {gone && <DismissBeacon host={host} dismissal={{ job: jobFixture }} onUndo={onUndo} />}
    </div>
  );
}

function mount(onUndo: (job: Job) => void) {
  render(<MemoryRouter><Host onUndo={onUndo} /></MemoryRouter>);
  fireEvent.click(screen.getByRole("button", { name: "Not for me" }));
}

function media(matches: (query: string) => boolean) {
  vi.spyOn(window, "matchMedia").mockImplementation((query: string) => ({
    matches: matches(query),
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  }));
}

const pill = () => screen.getByRole("button", { name: msg("jobs-dismissed-aria", { title: "Staff Product Manager, API" }) });

describe("DismissBeacon", () => {
  beforeEach(() => media((q) => /min-width: 1100px|hover: hover/.test(q)));
  afterEach(() => vi.restoreAllMocks());

  it("is level with the seam, and one click on the pill is the undo", () => {
    const onUndo = vi.fn();
    mount(onUndo);
    expect(pill().closest(".job-beacon")).not.toHaveAttribute("data-docked");
    fireEvent.click(pill());
    expect(onUndo).toHaveBeenCalledTimes(1);
    expect(onUndo).toHaveBeenCalledWith(jobFixture);
    // No reveal was needed to get there.
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("names the role on hover, carries Undo there too, and offers no rule", () => {
    const onUndo = vi.fn();
    mount(onUndo);
    fireEvent.pointerEnter(pill().closest(".job-beacon")!);
    const reveal = screen.getByRole("dialog", { name: "Not for me" });
    expect(reveal).toHaveTextContent("Staff Product Manager, API");
    expect(within(reveal).queryByRole("button", { name: /exclude/ })).toBeNull();
    fireEvent.click(within(reveal).getByRole("button", { name: msg("common-undo") }));
    expect(onUndo).toHaveBeenCalledWith(jobFixture);
  });

  it("docks without a margin, and a tap there opens the reveal that carries Undo", () => {
    media(() => false);
    const onUndo = vi.fn();
    mount(onUndo);
    expect(pill().closest(".job-beacon")).toHaveAttribute("data-docked");
    fireEvent.click(pill());
    expect(onUndo).not.toHaveBeenCalled();
    const reveal = screen.getByRole("dialog", { name: "Not for me" });
    fireEvent.click(within(reveal).getByRole("button", { name: msg("common-undo") }));
    expect(onUndo).toHaveBeenCalledWith(jobFixture);
  });
});
