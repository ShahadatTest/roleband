import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Content, Diagnostic } from "./Content";
import { Msg } from "./Msg";
import { activate } from "../copy/activate";
import type { Message } from "../copy/runtime";

// Two orders of one sentence, as two languages would write it.
const english = (a: { link: string; count: number }) => `Open ${a.link} to see ${a.count} roles.`;
const reordered = (a: { link: string; count: number }) => `${a.count} roles: see them in ${a.link}.`;

describe("Msg", () => {
  it("formats numeric elements with the selected region", async () => {
    await activate("en", {region:"es-ES"});
    try {
      const {container} = render(<Msg of={english} elems={{link:<a href="/saved">Saved</a>,count:1234567}} />);
      expect(container.textContent).toBe("Open Saved to see 1.234.567 roles.");
    } finally { await activate("en"); }
  });
  it("keeps the sentence whole and puts the element where the message says", () => {
    const { container, rerender } = render(<Msg of={english} args={{ count: 3 }} elems={{ link: <a href="/saved">Saved</a> }} />);
    expect(container.textContent).toBe("Open Saved to see 3 roles.");
    expect(screen.getByRole("link", { name: "Saved" })).toBeInTheDocument();
    rerender(<Msg of={reordered} args={{ count: 3 }} elems={{ link: <a href="/saved">Saved</a> }} />);
    expect(container.textContent).toBe("3 roles: see them in Saved.");
    expect(container.innerHTML).not.toMatch(/[]/);
  });
});

// Compile-time negative controls: a dropped/duplicated action or a selector
// replaced by a private-use token must fail TypeScript, not change the branch.
function typeContracts() {
  const selected = english as Message<{link:string;count:number},"count">;
  // @ts-expect-error missing required link
  const missing = <Msg of={english} args={{count:1}} elems={{}} />;
  // @ts-expect-error unknown element slot
  const unknown = <Msg of={english} args={{count:1}} elems={{link:<a href="/saved">Saved</a>,extra:<a href="/saved">Saved</a>}} />;
  // @ts-expect-error selector is data, not an element slot
  const selector = <Msg of={selected} elems={{link:<a href="/saved">Saved</a>,count:<b>1</b>}} />;
  // @ts-expect-error link supplied twice
  const duplicate = <Msg of={english} args={{count:1,link:"Saved"}} elems={{link:<a href="/saved">Saved</a>}} />;
  return [missing,unknown,selector,duplicate];
}
void typeContracts;

describe("Content and Diagnostic", () => {
  it("mark text RoleBand did not write so nothing translates it", () => {
    render(
      <p>
        <Content text="Stripe" lang="en" /> <Diagnostic text="lossy: 3 rows dropped" />
      </p>,
    );
    const name = screen.getByText("Stripe");
    expect(name).toHaveAttribute("translate", "no");
    expect(name).toHaveAttribute("lang", "en");
    expect(name).toHaveAttribute("dir", "auto");
    expect(screen.getByText("lossy: 3 rows dropped")).toHaveAttribute("data-copy", "diagnostic");
  });
});
