import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { JobList } from "./JobList";

describe("JobList", () => {
  /* j and k walk the rows as bare letters. Held with Cmd or Ctrl they are
     someone else's: Cmd+K opens the command palette, and must not also move
     the focus a row. */
  it("walks rows on bare j and k, and ignores them with a modifier", async () => {
    render(
      <JobList>
        <button type="button" className="job-row">first</button>
        <button type="button" className="job-row">second</button>
      </JobList>,
    );
    const user = userEvent.setup();
    const first = screen.getByRole("button", { name: "first" });
    const second = screen.getByRole("button", { name: "second" });
    first.focus();

    await user.keyboard("{Meta>}j{/Meta}{Control>}j{/Control}{Alt>}j{/Alt}");
    expect(first).toHaveFocus();

    await user.keyboard("j");
    expect(second).toHaveFocus();
    await user.keyboard("{Meta>}k{/Meta}");
    expect(second).toHaveFocus();
    await user.keyboard("k");
    expect(first).toHaveFocus();
  });

  it("leaves j and k to a field inside the list", async () => {
    render(
      <JobList>
        <button type="button" className="job-row">first</button>
        <textarea aria-label="Note" className="job-row" />
      </JobList>,
    );
    const user = userEvent.setup();
    const note = screen.getByRole("textbox", { name: "Note" });
    note.focus();
    await user.keyboard("jk");
    expect(note).toHaveFocus();
    expect(note).toHaveValue("jk");
  });

  /* The column shows the short form; its sort button is named by the full
     words, so a screen reader never spells out "T C". */
  it("names the Base sort by what it shows and by its full words, with them on hover", async () => {
    const sorted: string[] = [];
    render(<JobList sortControl={{ sort: "base_pay", order: "desc", onSort: (k) => sorted.push(k) }}>{null}</JobList>);
    const sort = screen.getByRole("button", { name: "Sort by Base (Base salary), descending" });
    const visible = sort.querySelector('abbr [aria-hidden="true"]')?.textContent ?? "";
    expect(visible).toBe("Base");
    // A voice user says the words on screen, so the name has to contain them.
    expect(sort.getAttribute("aria-label")).toContain(visible);
    expect(sort.querySelector("abbr")).toHaveAttribute("title", "Base salary");
    await userEvent.setup().click(sort);
    expect(sorted).toEqual(["base_pay"]);
    // A column without a short form keeps its own name.
    expect(screen.getByRole("button", { name: "Sort by Location" }).querySelector("abbr")).toBeNull();
  });
});
