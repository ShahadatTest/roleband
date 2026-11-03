import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Badge } from "./Badge";

describe("Badge", () => {
  it("renders children with neutral/soft/md defaults", () => {
    render(<Badge>fresh</Badge>);
    const badge = screen.getByText("fresh");
    expect(badge).toHaveClass("ui-badge", "ui-badge-neutral", "ui-badge-soft", "ui-badge-md");
  });

  it("applies tone, variant, and size classes", () => {
    render(
      <Badge tone="danger" variant="outline" size="sm">
        closed
      </Badge>,
    );
    const badge = screen.getByText("closed");
    expect(badge).toHaveClass("ui-badge-danger", "ui-badge-outline", "ui-badge-sm");
    expect(badge).not.toHaveClass("ui-badge-neutral", "ui-badge-soft", "ui-badge-md");
  });

  it("covers every tone x variant combination without leaking other tones", () => {
    const tones = ["neutral", "info", "success", "warning", "danger", "accent"] as const;
    const variants = ["solid", "soft", "outline"] as const;
    for (const tone of tones) {
      for (const variant of variants) {
        const { unmount } = render(
          <Badge tone={tone} variant={variant}>
            {`${tone}-${variant}`}
          </Badge>,
        );
        const badge = screen.getByText(`${tone}-${variant}`);
        expect(badge).toHaveClass(`ui-badge-${tone}`, `ui-badge-${variant}`);
        for (const other of tones) {
          if (other !== tone) expect(badge).not.toHaveClass(`ui-badge-${other}`);
        }
        unmount();
      }
    }
  });

  it("forwards title for hover explanations", () => {
    render(<Badge title="Posting states a pay band">pay</Badge>);
    expect(screen.getByText("pay")).toHaveAttribute("title", "Posting states a pay band");
  });
});
