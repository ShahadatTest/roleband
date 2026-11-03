import { act, renderHook } from "@testing-library/react";
import { expect, it } from "vitest";
import { useRoleSaves } from "./useRoleSaves";

/* The one writer for a role's saved state. Two hooks stand for two
   surfaces (the Radar and Compare): what orders their writes is the role, not
   the surface, and the order outlives the surface that started it. */

function server() {
  const state = { saved: new Map<number, boolean>(), sent: [] as boolean[], waiting: [] as (() => void)[] };
  const send = (id: number, on: boolean) => () => {
    state.sent.push(on);
    return new Promise<void>((resolve) => state.waiting.push(() => { state.saved.set(id, on); resolve(); }));
  };
  return { state, send };
}

it("orders one role's writes across surfaces, even after the first surface is gone", async () => {
  const { state, send } = server();
  const radar = renderHook(() => useRoleSaves());
  const compare = renderHook(() => useRoleSaves());
  const shown: boolean[] = [];

  let first!: Promise<unknown>;
  act(() => {
    first = radar.result.current({ jobId: 7, was: false, next: true, show: (on) => shown.push(on), send: send(7, true) });
  });
  radar.unmount(); // navigating away does not cancel or reorder the write
  let second!: Promise<unknown>;
  act(() => {
    second = compare.result.current({ jobId: 7, was: true, next: false, show: (on) => shown.push(on), send: send(7, false) });
  });
  await act(async () => {});
  expect(state.sent).toEqual([true]);

  await act(async () => state.waiting[0]());
  await act(async () => {});
  expect(state.sent).toEqual([true, false]);
  await act(async () => state.waiting[1]());

  await expect(first).resolves.toBe("saved");
  await expect(second).resolves.toBe("saved");
  expect(state.saved.get(7)).toBe(false);
  expect(shown).toEqual([true, false]);
});

it("never makes two roles wait on each other", async () => {
  const { state, send } = server();
  const { result } = renderHook(() => useRoleSaves());
  act(() => {
    void result.current({ jobId: 1, was: false, next: true, show: () => {}, send: send(1, true) });
    void result.current({ jobId: 2, was: false, next: true, show: () => {}, send: send(2, true) });
  });
  await act(async () => {});
  expect(state.sent).toEqual([true, true]);
});
