import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Button } from "../ui";
import { PageHeader } from "./PageHeader";

describe("PageHeader", () => {
  it("renders one page heading with optional metadata and an independent action", async () => {
    const action = vi.fn();
    const { container, rerender } = render(<PageHeader title="Saved"
      meta={<p>Keep roles for later.</p>} actions={<Button onClick={action}>Compare saved</Button>} />);
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    const title = screen.getByRole("heading", { level: 1, name: "Saved" });
    expect(title.parentElement).toHaveTextContent("Keep roles for later.");
    expect(within(title.parentElement!).queryByRole("button")).toBeNull();
    expect(container.firstElementChild).toHaveClass("page-hero");
    await userEvent.click(screen.getByRole("button", { name: "Compare saved" }));
    expect(action).toHaveBeenCalledOnce();
    rerender(<PageHeader title="Compare" />);
    expect(screen.getByRole("heading", { level: 1, name: "Compare" })).toBeVisible();
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.queryByText("Keep roles for later.")).toBeNull();
  });
});
