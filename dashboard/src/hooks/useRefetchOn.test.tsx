import { renderHook } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { useRefetchOn } from "./useAsyncResource";

/* An epoch a screen re-reads on: the mount already fetched, so only a change
   after it may refetch (a positive value at mount is not a change). */

it("never refetches for the value it mounted with, even a positive one", () => {
  const refresh = vi.fn(async () => {});
  const { rerender } = renderHook(({ v }) => useRefetchOn(v, refresh), { initialProps: { v: 3 } });
  rerender({ v: 3 });
  expect(refresh).not.toHaveBeenCalled();
});

it("refetches in place once per change, through the refresh of that render", () => {
  const first = vi.fn(async () => {});
  const second = vi.fn(async () => {});
  const { rerender } = renderHook(({ v, r }) => useRefetchOn(v, r), { initialProps: { v: 0, r: first } });
  rerender({ v: 1, r: second });
  expect(first).not.toHaveBeenCalled();
  expect(second).toHaveBeenCalledTimes(1);
  expect(second).toHaveBeenCalledWith({ preserveData: true });
  rerender({ v: 1, r: second });
  expect(second).toHaveBeenCalledTimes(1);
  rerender({ v: 2, r: second });
  expect(second).toHaveBeenCalledTimes(2);
});
