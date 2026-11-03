import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Pager } from "./Pager";

describe("Pager", () => {
  it.each([0, 1, 20])("has no controls when %s results fit on one page", (total) => {
    const change = vi.fn();
    render(<Pager total={total} pageSize={20} offset={0} onOffsetChange={change} />);
    expect(screen.queryByRole("button")).toBeNull();
    expect(change).not.toHaveBeenCalled();
  });

  it("computes partial last pages and emits bounded offsets only on interaction", async () => {
    const change = vi.fn();
    const { rerender } = render(<Pager total={41} pageSize={20} offset={0} onOffsetChange={change} />);
    expect(screen.getByText("Page 1 of 3")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Prev" }));
    expect(change).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(change).toHaveBeenLastCalledWith(20);
    rerender(<Pager total={41} pageSize={20} offset={20} onOffsetChange={change} />);
    expect(screen.getByText("Page 2 of 3")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Prev" }));
    expect(change).toHaveBeenLastCalledWith(0);
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(change).toHaveBeenLastCalledWith(40);
    rerender(<Pager total={41} pageSize={20} offset={40} onOffsetChange={change} />);
    expect(screen.getByText("Page 3 of 3")).toBeVisible();
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
    change.mockClear();
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(change).not.toHaveBeenCalled();
  });

  it("uses the supplied page size, not the current screens' common size", async () => {
    const change = vi.fn();
    render(<Pager total={14} pageSize={7} offset={7} onOffsetChange={change} />);
    expect(screen.getByText("Page 2 of 2")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Prev" }));
    expect(change).toHaveBeenCalledWith(0);
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
  });
});
