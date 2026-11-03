import { render } from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { useBodyAttribute } from "./useBodyAttribute";

function Wearer({ name = "data-material", value = "register" }: { name?: string; value?: string }) {
  useBodyAttribute(name, value);
  return null;
}

afterEach(() => {
  document.body.removeAttribute("data-material");
  document.body.removeAttribute("data-other");
});

describe("useBodyAttribute", () => {
  it.each([null, "", "original"])("restores the original value %s after StrictMode remounting", (original) => {
    if (original !== null) document.body.setAttribute("data-material", original);
    const { unmount } = render(<StrictMode><Wearer /></StrictMode>);
    expect(document.body).toHaveAttribute("data-material", "register");
    unmount();
    expect(document.body.getAttribute("data-material")).toBe(original);
  });

  it.each([true, false])("overlapping identical wearers survive either cleanup order: first=%s", (oldestFirst) => {
    document.body.setAttribute("data-material", "original");
    const first = render(<Wearer />);
    const second = render(<Wearer />);
    (oldestFirst ? first : second).unmount();
    expect(document.body).toHaveAttribute("data-material", "register");
    (oldestFirst ? second : first).unmount();
    expect(document.body).toHaveAttribute("data-material", "original");
  });

  it("removing a middle owner cannot resurrect it after the newest leaves", () => {
    const first = render(<Wearer value="first" />);
    const middle = render(<Wearer value="middle" />);
    const last = render(<Wearer value="last" />);
    middle.unmount();
    expect(document.body).toHaveAttribute("data-material", "last");
    last.unmount();
    expect(document.body).toHaveAttribute("data-material", "first");
    first.unmount();
    expect(document.body).not.toHaveAttribute("data-material");
  });

  it("updates values and names without leaking the old attribute", () => {
    const { rerender, unmount } = render(<Wearer value="first" />);
    rerender(<Wearer value="second" />);
    expect(document.body).toHaveAttribute("data-material", "second");
    rerender(<Wearer name="data-other" value="third" />);
    expect(document.body).not.toHaveAttribute("data-material");
    expect(document.body).toHaveAttribute("data-other", "third");
    unmount();
    expect(document.body).not.toHaveAttribute("data-other");
  });

  it("does not erase a value written later by an external owner", () => {
    const { unmount } = render(<Wearer />);
    document.body.setAttribute("data-material", "external");
    unmount();
    expect(document.body).toHaveAttribute("data-material", "external");
  });
});
