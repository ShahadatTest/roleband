import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { FilterSelect, FilterSelectOption } from "./FilterSelect";

const OPTIONS: FilterSelectOption[] = [
  { value: "google", label: "Google", count: 12 },
  { value: "anthropic", label: "Anthropic", count: 7 },
  { value: "netflix", label: "Netflix", count: 3 },
];

function Controlled({
  multiple = true,
  searchable = false,
  initial = [] as string[],
  spy,
}: {
  multiple?: boolean;
  searchable?: boolean;
  initial?: string[];
  spy?: (next: string[]) => void;
}) {
  const [selected, setSelected] = useState<string[]>(initial);
  return (
    <FilterSelect
      label="Company"
      options={OPTIONS}
      selected={selected}
      onChange={(next) => {
        spy?.(next);
        setSelected(next);
      }}
      multiple={multiple}
      searchable={searchable}
    />
  );
}

describe("FilterSelect", () => {
  it("opens a popover listing options with counts", async () => {
    render(<Controlled />);
    const trigger = screen.getByRole("button", { name: "Filter by company" });
    expect(trigger).toHaveAttribute("aria-expanded", "false");

    await userEvent.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    const listbox = screen.getByRole("listbox", { name: "Company options" });
    expect(listbox).toHaveAttribute("aria-multiselectable", "true");
    expect(screen.getAllByRole("option")).toHaveLength(3);
    expect(screen.getByRole("option", { name: /Google\s*12/ })).toBeInTheDocument();
  });

  it("multi-select toggles values without closing and reflects count on the trigger", async () => {
    const spy = vi.fn();
    render(<Controlled spy={spy} />);
    const trigger = screen.getByRole("button", { name: "Filter by company" });
    await userEvent.click(trigger);

    await userEvent.click(screen.getByRole("option", { name: /Google/ }));
    expect(spy).toHaveBeenLastCalledWith(["google"]);
    // Stays open for further picks.
    expect(screen.getByRole("listbox")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("option", { name: /Netflix/ }));
    expect(spy).toHaveBeenLastCalledWith(["google", "netflix"]);
    expect(screen.getByRole("option", { name: /Google/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(trigger).toHaveTextContent("Company · 2");

    // Toggling a selected value removes it.
    await userEvent.click(screen.getByRole("option", { name: /Google/ }));
    expect(spy).toHaveBeenLastCalledWith(["netflix"]);
  });

  it("single select replaces the selection and closes the popover", async () => {
    const spy = vi.fn();
    render(<Controlled multiple={false} initial={["google"]} spy={spy} />);
    await userEvent.click(screen.getByRole("button", { name: "Filter by company" }));
    await userEvent.click(screen.getByRole("option", { name: /Anthropic/ }));
    expect(spy).toHaveBeenLastCalledWith(["anthropic"]);
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("supports keyboard: arrows move the active option, Enter toggles it", async () => {
    const spy = vi.fn();
    render(<Controlled spy={spy} />);
    await userEvent.click(screen.getByRole("button", { name: "Filter by company" }));
    const listbox = screen.getByRole("listbox");

    fireEvent.keyDown(listbox, { key: "ArrowDown" });
    fireEvent.keyDown(listbox, { key: "ArrowDown" });
    expect(listbox).toHaveAttribute(
      "aria-activedescendant",
      screen.getByRole("option", { name: /Netflix/ }).id,
    );
    fireEvent.keyDown(listbox, { key: "ArrowUp" });
    fireEvent.keyDown(listbox, { key: "Enter" });
    expect(spy).toHaveBeenLastCalledWith(["anthropic"]);
  });

  it("takes the keyboard where focus lands: the list itself, with no option a tab stop", async () => {
    const spy = vi.fn();
    render(<Controlled spy={spy} />);
    await userEvent.click(screen.getByRole("button", { name: "Filter by company" }));
    const listbox = screen.getByRole("listbox");
    expect(listbox).toHaveFocus();
    expect(screen.getAllByRole("option").every((option) => option.tabIndex === -1)).toBe(true);

    await userEvent.keyboard("{ArrowDown}{ArrowDown}");
    expect(listbox).toHaveAttribute("aria-activedescendant", screen.getByRole("option", { name: /Netflix/ }).id);
    await userEvent.keyboard("{Enter}");
    expect(spy).toHaveBeenLastCalledWith(["netflix"]);
  });

  it("with a search box, the box is a combobox naming the active option while the person types", async () => {
    render(<Controlled searchable />);
    await userEvent.click(screen.getByRole("button", { name: "Filter by company" }));
    const combobox = screen.getByRole("combobox");
    const listbox = screen.getByRole("listbox");
    expect(combobox).toHaveFocus();
    expect(combobox).toHaveAttribute("aria-controls", listbox.id);

    await userEvent.keyboard("{ArrowDown}");
    expect(combobox).toHaveAttribute("aria-activedescendant", screen.getByRole("option", { name: /Anthropic/ }).id);
    expect(listbox).not.toHaveAttribute("aria-activedescendant");
    await userEvent.keyboard("net");
    expect(combobox).toHaveAttribute("aria-activedescendant", screen.getByRole("option", { name: /Netflix/ }).id);
  });

  it("search narrows options and shows empty text when nothing matches", async () => {
    render(<Controlled searchable />);
    await userEvent.click(screen.getByRole("button", { name: "Filter by company" }));
    const search = screen.getByRole("combobox", { name: "Search company" });
    await userEvent.type(search, "net");
    expect(screen.getAllByRole("option")).toHaveLength(1);
    expect(screen.getByRole("option", { name: /Netflix/ })).toBeInTheDocument();

    await userEvent.clear(search);
    await userEvent.type(search, "zzz");
    expect(screen.queryAllByRole("option")).toHaveLength(0);
    expect(screen.getByText("No options match.")).toBeInTheDocument();
  });

  it("Clear empties the selection", async () => {
    const spy = vi.fn();
    render(<Controlled initial={["google", "netflix"]} spy={spy} />);
    await userEvent.click(screen.getByRole("button", { name: "Filter by company" }));
    await userEvent.click(screen.getByRole("button", { name: "Clear" }));
    expect(spy).toHaveBeenLastCalledWith([]);
  });

  it("renderOption customizes rows", async () => {
    render(
      <FilterSelect
        label="Level"
        options={OPTIONS}
        selected={[]}
        onChange={() => {}}
        renderOption={(o, isSelected) => (
          <em>
            {o.label}
            {isSelected ? " (on)" : ""}
          </em>
        )}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Filter by level" }));
    expect(screen.getByRole("option", { name: "Google" }).querySelector("em")).not.toBeNull();
  });
});
