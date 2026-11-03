import { afterEach, expect, it, vi } from "vitest";
import { activate, adopt, saveChoice } from "./activate";
import { LOADERS } from "./gen/index";
import { activeKey, choice, intentRevision, storedChoice, STORAGE_KEY } from "./runtime";
const deferred = <T,>() => { let resolve!: (v: T) => void; const promise = new Promise<T>((r) => { resolve = r; }); return { promise, resolve }; };
afterEach(async () => { vi.restoreAllMocks(); await activate("en"); localStorage.clear(); });
it("keeps the requested region even when its effective value does not change", async () => {
  await activate("en"); const before = activeKey();
  await saveChoice({ language: "en", region: navigator.language }, vi.fn().mockResolvedValue({}));
  expect(activeKey()).toBe(before); expect(choice().region).toBe(navigator.language);
  await saveChoice({ language: "en", region: null }, vi.fn().mockResolvedValue({}));
  expect(choice().region).toBeNull();
});
it("a slower loader cannot replace a later intent", async () => {
  const pending = deferred<{ default: [] }>(); vi.spyOn(LOADERS, "es").mockReturnValue(pending.promise);
  const first = activate("es"); await activate("en", { region: "en-GB" });
  pending.resolve({ default: [] }); await first;
  expect(choice()).toEqual({ language: "en", region: "en-GB" });
});
it("a newer save completes without waiting for an obsolete loader",async()=>{
  const pending=deferred<{default:[]}>();vi.spyOn(LOADERS,"es").mockReturnValue(pending.promise);
  const first=saveChoice({language:"es",region:null},vi.fn());
  const second=saveChoice({language:"en",region:"en-GB"},vi.fn().mockResolvedValue({}));
  try {
    await vi.waitFor(()=>expect(choice()).toEqual({language:"en",region:"en-GB"}),{timeout:250,interval:10});
  } finally {pending.resolve({default:[]});await Promise.all([first,second]);}
});
it("a late account read cannot undo a user save", async () => {
  const readRevision = intentRevision();
  await saveChoice({ language: "en", region: "en-GB" }, vi.fn().mockResolvedValue({}));
  await adopt({ language: "es", region: null }, readRevision);
  expect(choice().language).toBe("en"); expect(choice().region).toBe("en-GB");
});
it("rejects invalid regions before loading, saving or mutating the last good choice", async () => {
  const save = vi.fn(); const before = choice();
  await expect(saveChoice({ language: "es", region: "en-12-34" }, save)).rejects.toThrow(RangeError);
  expect(save).not.toHaveBeenCalled(); expect(choice()).toBe(before);
  localStorage.setItem(STORAGE_KEY, JSON.stringify({ language: "en", region: "en-12-34" }));
  expect(storedChoice()).toBeNull();
});
it("load and account-save failures preserve the active choice", async () => {
  const before = choice(); const save = vi.fn().mockRejectedValue(new Error("offline"));
  await expect(saveChoice({ language: "en", region: "en-GB" }, save)).rejects.toThrow("offline");
  expect(choice()).toBe(before);
  vi.spyOn(LOADERS, "es").mockRejectedValue(new Error("missing chunk"));
  save.mockClear(); await expect(saveChoice({ language: "es", region: null }, save)).rejects.toThrow("missing chunk");
  expect(save).not.toHaveBeenCalled(); expect(choice()).toBe(before);
});
it("a denied device cache does not prevent an in-session switch", async () => {
  vi.spyOn(Storage.prototype,"setItem").mockImplementation(()=>{throw new Error("denied");});
  await activate("es");expect(choice().language).toBe("es");
});
it("writes stay ordered across remounts and a failed write does not poison the queue", async () => {
  const pending=deferred<unknown>(), save=vi.fn().mockReturnValueOnce(pending.promise).mockResolvedValueOnce({});
  const first=saveChoice({language:"en",region:"en-GB"},save);
  await Promise.resolve();await Promise.resolve();
  const second=saveChoice({language:"en",region:"en-US"},save);
  pending.resolve({});await Promise.all([first,second]);
  expect(choice().region).toBe("en-US");
  expect(save.mock.calls[save.mock.calls.length - 1]?.[0]).toEqual({language:"en",region:"en-US"});
});
