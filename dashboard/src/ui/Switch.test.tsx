import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Switch } from "./Switch";

/* Contracts no call site carries by hand. */

describe("Switch", () => {
  it("reports the NEXT value, so a caller never reads the event itself", async () => {
    const onChange = vi.fn();
    render(<Switch label="Track Anthropic" checked={false} onChange={onChange} />);
    await userEvent.click(screen.getByRole("checkbox", { name: "Track Anthropic" }));
    expect(onChange).toHaveBeenCalledWith(true);
  });

  it("is reached by clicking the target around the track, not only the track", async () => {
    const onChange = vi.fn();
    const { container } = render(<Switch label="Track Anthropic" checked={false} onChange={onChange} />);
    const target = container.querySelector(".ui-switch") as HTMLElement;
    // The wrapper is a <label>, so its padding forwards the click. A <span>
    // wrapper swallows it.
    expect(target.tagName).toBe("LABEL");
    await userEvent.click(target);
    expect(onChange).toHaveBeenCalledWith(true);
  });

  it("takes its name from visible text when it has some", () => {
    render(
      <Switch checked onChange={() => {}}>
        Following only
      </Switch>,
    );
    expect(screen.getByRole("checkbox", { name: "Following only" })).toBeChecked();
  });

  it("carries the half-state, which JSX alone cannot set", () => {
    const { rerender } = render(<Switch label="All shown" checked={false} onChange={() => {}} indeterminate />);
    const box = screen.getByRole("checkbox", { name: "All shown" }) as HTMLInputElement;
    expect(box.indeterminate).toBe(true);

    rerender(<Switch label="All shown" checked={false} onChange={() => {}} />);
    expect(box.indeterminate).toBe(false);
  });

  it("does not fire while disabled, and keeps its describedBy", async () => {
    const onChange = vi.fn();
    render(
      <>
        <Switch label="Track Netflix" describedBy="why" checked={false} disabled onChange={onChange} />
        <p id="why">Netflix has no connector yet</p>
      </>,
    );
    const box = screen.getByRole("checkbox", { name: "Track Netflix" });
    expect(box).toHaveAccessibleDescription("Netflix has no connector yet");
    await userEvent.click(box);
    expect(onChange).not.toHaveBeenCalled();
  });

  it("only stretches to its row when it has no label of its own", () => {
    const { container, rerender } = render(<Switch label="Track Meta" checked onChange={() => {}} />);
    expect(container.querySelector(".ui-switch")).not.toHaveClass("is-labelled");

    rerender(
      <Switch checked onChange={() => {}}>
        Following only
      </Switch>,
    );
    expect(container.querySelector(".ui-switch")).toHaveClass("is-labelled");
  });
});
