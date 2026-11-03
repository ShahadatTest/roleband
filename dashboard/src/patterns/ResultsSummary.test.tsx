import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Button } from "../ui";
import { ResultsSummary } from "./ResultsSummary";

describe("ResultsSummary", () => {
  it.each([
    [0, undefined, "0 roles"], [1, undefined, "1 role"],
    [1, 3, "1 of 3 roles"], [0, 1, "0 of 1 role"],
    [0, 0, "0 of 0 roles"], [2, null, "2 roles"],
  ])("reads an exact count with real spaces: %s of %s", (count, total, text) => {
    const { container } = render(<ResultsSummary count={count} total={total} noun="role" />);
    expect(container.textContent).toBe(text);
  });

  it("formats large counts and supports caller-owned noun, prefix and metadata", () => {
    const { container } = render(<ResultsSummary count={1204} total={4000} noun="company"
      prefix="Showing" meta={<> · needs review</>} />);
    expect(container.textContent).toBe(`Showing ${(1204).toLocaleString()} of ${(4000).toLocaleString()} companies · needs review`);
  });

  it("renders the reset slot without clearing or guessing the count itself", async () => {
    const reset = vi.fn();
    const { container, rerender } = render(<ResultsSummary count={2} noun="role"
      reset={<Button variant="link" onClick={reset}>Reset all</Button>} />);
    expect(container.textContent).toBe("2 roles · Reset all");
    await userEvent.click(screen.getByRole("button", { name: "Reset all" }));
    expect(reset).toHaveBeenCalledOnce();
    expect(container.textContent).toBe("2 roles · Reset all");
    rerender(<ResultsSummary count={2} noun="role" />);
    expect(container.textContent).toBe("2 roles");
    expect(screen.queryByRole("button")).toBeNull();
  });
});
