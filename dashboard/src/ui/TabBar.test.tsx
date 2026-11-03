import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { TabBar } from "./TabBar";

/* Contracts for the tab bar: the tablist pattern the component emits, and
 * the states its stylesheet promises. */

const css = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), "TabBar.css"),
  "utf8",
).replace(/\/\*[\s\S]*?\*\//g, "");

const TABS = [
  { id: "queue", label: "Review queue", badge: 100 },
  { id: "history", label: "Decided", badge: 9 },
  { id: "archive", label: "Archive" },
] as const;

function renderBar(value: "queue" | "history" | "archive" = "queue", onChange = vi.fn()) {
  render(
    <TabBar label="Review views" value={value} onChange={onChange} tabs={TABS} idPrefix="review" controls="review-panel" />,
  );
  return onChange;
}

describe("TabBar", () => {
  it("is a tablist of tabs with one selected and a roving tabindex", () => {
    renderBar("history");
    expect(screen.getByRole("tablist", { name: "Review views" })).toBeInTheDocument();
    const tabs = screen.getAllByRole("tab");
    expect(tabs).toHaveLength(3);
    expect(tabs.map((t) => t.getAttribute("aria-selected"))).toEqual(["false", "true", "false"]);
    expect(tabs.map((t) => t.tabIndex)).toEqual([-1, 0, -1]);
    for (const t of tabs) {
      expect(t).toHaveAttribute("aria-controls", "review-panel");
      expect(t.className).not.toMatch(/\bon\b|active|selected/);
    }
    expect(tabs[0]).toHaveAttribute("id", "review-tab-queue");
  });

  it("renders a badge in the tab's accessible name, so a count is part of the tab", () => {
    renderBar();
    expect(screen.getByRole("tab", { name: /Review queue\s*100/ })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Archive" })).toBeInTheDocument();
  });

  it("reports a click on another tab and ignores a click on the current one", () => {
    const onChange = renderBar("queue");
    fireEvent.click(screen.getByRole("tab", { name: /Decided/ }));
    expect(onChange).toHaveBeenCalledWith("history");
    fireEvent.click(screen.getByRole("tab", { name: /Review queue/ }));
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it("moves with the arrow keys, wrapping, and Home/End", () => {
    const onChange = renderBar("archive");
    const bar = screen.getByRole("tablist");
    fireEvent.keyDown(bar, { key: "ArrowRight" });
    expect(onChange).toHaveBeenLastCalledWith("queue");
    fireEvent.keyDown(bar, { key: "ArrowLeft" });
    expect(onChange).toHaveBeenLastCalledWith("history");
    fireEvent.keyDown(bar, { key: "Home" });
    expect(onChange).toHaveBeenLastCalledWith("queue");
    fireEvent.keyDown(bar, { key: "End" });
    expect(onChange).toHaveBeenLastCalledWith("archive");
  });

  it("sets a group apart with a rule that is not a tab, and says why a tab is locked", () => {
    render(
      <TabBar
        label="Steps"
        value="role"
        onChange={vi.fn()}
        idPrefix="walk"
        tabs={[
          { id: "role", label: "Role" },
          { id: "where", label: "Where" },
          { id: "interests", label: "Interests", groupStart: true, disabled: true, title: "Answer the first three to unlock this" },
          { id: "summary", label: "Summary", groupStart: true },
        ]}
      />,
    );
    const bar = screen.getByRole("tablist", { name: "Steps" });
    // The rules sit between runs of tabs and are invisible to the tablist.
    expect(screen.getAllByRole("tab")).toHaveLength(4);
    const order = [...bar.children].map((child) => child.getAttribute("role") ?? child.className);
    expect(order).toEqual(["tab", "tab", "ui-tabbar-rule", "tab", "ui-tabbar-rule", "tab"]);
    expect(bar.querySelectorAll(".ui-tabbar-rule[aria-hidden='true']")).toHaveLength(2);
    const locked = screen.getByRole("tab", { name: "Interests" });
    expect(locked).toBeDisabled();
    expect(locked).toHaveAttribute("title", "Answer the first three to unlock this");
  });

  describe("stylesheet contracts", () => {
    it("takes the lg rank of the control scale, never a literal height", () => {
      const tab = css.slice(css.indexOf(".ui-tab {"), css.indexOf("}", css.indexOf(".ui-tab {")));
      expect(tab).toMatch(/min-height:\s*var\(--app-control-lg\)/);
      expect(tab).toMatch(/padding:\s*0 var\(--app-control-lg-pad\)/);
      expect(tab).toMatch(/border-radius:\s*var\(--app-radius-md\)/);
      expect(tab).not.toMatch(/\d+px/);
    });

    it("declares its whole state set, keyed off aria-selected", () => {
      for (const rule of [
        ".ui-tab:not(:disabled):hover",
        ".ui-tab:not(:disabled):active",
        ".ui-tab:disabled",
        ".ui-tab:focus-visible",
        '.ui-tab[aria-selected="true"]',
      ]) {
        expect(css, `declares ${rule}`).toContain(rule);
      }
      expect(css).not.toMatch(/\.ui-tab\.(on|active|selected)/);
    });

    it("paints --app-* only", () => {
      const consumed = [...css.matchAll(/var\((--[a-z0-9-]+)/g)].map((m) => m[1]);
      expect(consumed.filter((t) => !t.startsWith("--app-"))).toEqual([]);
    });
  });
});
