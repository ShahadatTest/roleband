import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { JobLinkRow } from "./JobLinkRow";

/* A job row is a real destination. Keyboard reach and
 * "open in a new tab" come from the anchor; the app's overlay navigation
 * survives a plain click. */

/** Records whether the click was still default-prevented once every handler
 *  in the tree had run. */
function trackDefaultPrevented() {
  let seen = false;
  document.addEventListener("click", (e) => { seen = e.defaultPrevented; }, { once: true });
  return () => seen;
}

const renderRow = (props: Partial<Parameters<typeof JobLinkRow>[0]> = {}) => {
  const onOpen = vi.fn();
  render(
    <MemoryRouter>
      <button>Before</button>
      <JobLinkRow jobId={101} company="openai" onOpen={onOpen} className="mini-job" {...props}>
        <span>Staff Product Manager</span>
      </JobLinkRow>
    </MemoryRouter>,
  );
  return { onOpen, link: screen.getByRole("link", { name: /Staff Product Manager/ }) };
};

describe("patterns/jobs/JobLinkRow", () => {
  it("is a link to the canonical position URL, keeping its screen's class", () => {
    const { link } = renderRow();
    expect(link).toHaveAttribute("href", "/company/openai/job/101");
    expect(link).toHaveClass("job-link", "mini-job");
  });

  it("falls back to the id-only URL when the caller has no company slug", () => {
    const { link } = renderRow({ company: null });
    expect(link).toHaveAttribute("href", "/job/101");
  });

  it("opens through the app on a plain click, without letting the browser navigate", async () => {
    const { onOpen, link } = renderRow();
    // Listen at the DOCUMENT: React delegates to the root container, so a
    // listener on the link itself would read defaultPrevented before the
    // component's own handler had run.
    const prevented = trackDefaultPrevented();
    await userEvent.click(link);
    expect(onOpen).toHaveBeenCalledWith(101, "openai");
    expect(prevented()).toBe(true);
  });

  it("is reachable by Tab and opens on Enter", async () => {
    const { onOpen } = renderRow();
    screen.getByRole("button", { name: "Before" }).focus();
    await userEvent.tab();
    expect(document.activeElement).toBe(screen.getByRole("link", { name: /Staff Product Manager/ }));
    await userEvent.keyboard("{Enter}");
    expect(onOpen).toHaveBeenCalledWith(101, "openai");
  });

  it.each([
    ["cmd/ctrl", { metaKey: true }],
    ["shift", { shiftKey: true }],
    ["middle button", { button: 1 }],
  ])("leaves a %s intent to the browser: no app navigation, no preventDefault", async (_name, init) => {
    const { onOpen, link } = renderRow();
    const prevented = trackDefaultPrevented();
    // fireEvent, not userEvent: the modifier has to be ON the click, and the
    // top-level userEvent helpers do not carry held keys between calls.
    fireEvent.click(link, init);
    expect(onOpen).not.toHaveBeenCalled();
    expect(prevented()).toBe(false);
  });
});
