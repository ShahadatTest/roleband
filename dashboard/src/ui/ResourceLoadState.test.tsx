import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { ResourceLoadState } from "./ResourceLoadState";

it("says a failed load in the person's words, with Try again", () => {
  render(<ResourceLoadState error={new Error("500 Internal Server Error")} failed="Couldn't load companies" onRetry={vi.fn()} />);
  const alert = screen.getByRole("alert");
  expect(alert).toHaveTextContent("Couldn't load companies");
  expect(alert).toHaveTextContent("Couldn't get it just now.");
  // The developer's words, never shown: "The API request failed. Check the service".
  expect(alert).not.toHaveTextContent(/API|service|500/);
  expect(screen.getByRole("button", { name: "Try again" })).toBeVisible();
});

it("says a thing that is gone as gone, with no Try again that cannot help", () => {
  render(<ResourceLoadState error={new Error("404")} failed="Couldn't load this role" onRetry={vi.fn()} gone="This role no longer exists." />);
  expect(screen.getByRole("alert")).toHaveTextContent("This role no longer exists.");
  expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
});
