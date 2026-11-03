import { afterEach, describe, expect, it, vi } from "vitest";
import { setCompanyNames } from "../format";
import { msg } from "../test/msg";
import { errorText } from "./errorText";
import { ApiError, getJSON } from "./transport";

/* Every way a request fails becomes a code, and a person reads the catalog's
 * words for it, never the English the server or the browser wrote
 * (docs/copy.md). */

afterEach(() => vi.unstubAllGlobals());

const answer = (status: number, body: unknown, json = true) =>
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
    new Response(json ? JSON.stringify(body) : String(body), { status, headers: json ? { "Content-Type": "application/json" } : {} }),
  ));

async function failure(): Promise<ApiError> {
  try {
    await getJSON("/api/anything");
  } catch (caught) {
    return caught as ApiError;
  }
  throw new Error("expected a failure");
}

describe("the transport's six failure paths", () => {
  it("a coded error keeps its code, params and status; its English stays for logs", async () => {
    answer(409, { detail: { code: "scheduling-unavailable", params: { companies: ["apple"] }, message: "paused: apple" } });
    const error = await failure();
    expect([error.status, error.code, error.params, error.message]).toEqual([409, "scheduling-unavailable", { companies: ["apple"] }, "paused: apple"]);
  });

  it("FastAPI's 422 list is invalid input", async () => {
    answer(422, { detail: [{ loc: ["body", "days"], msg: "Input should be a valid integer", type: "int_type" }] });
    expect((await failure()).code).toBe("invalid-input");
  });

  it("bare English from before codes is unknown; a 5xx is server", async () => {
    answer(404, { detail: "job not found" });
    expect((await failure()).code).toBe("unknown");
    answer(500, { detail: "Traceback (most recent call last)" });
    expect((await failure()).code).toBe("server");
  });

  it("a body that is not JSON is server", async () => {
    answer(502, "<html>Bad Gateway</html>", false);
    expect((await failure()).code).toBe("server");
  });

  it("no answer at all is offline; a cancelled request is aborted", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    expect((await failure()).code).toBe("offline");
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new DOMException("The operation was aborted.", "AbortError")));
    expect((await failure()).code).toBe("aborted");
  });

  it("a 2xx that cannot be read is server", async () => {
    answer(200, "{not json", false);
    expect((await failure()).code).toBe("server");
  });
});

describe("errorText", () => {
  it("says the catalog's words for a code, naming companies from their slugs", () => {
    expect(errorText(new ApiError("job not found", 404, "job-not-found"))).toBe(msg("error-job-not-found"));
    expect(errorText(new ApiError("Failed to fetch", 0, "offline"))).toBe(msg("error-offline"));
    // As at boot (main.tsx), the display names are read before anything renders.
    setCompanyNames({ "jane-street": "Jane Street" });
    const text = errorText(new ApiError("paused", 409, "scheduling-unavailable", { companies: ["jane-street", "openai"] }));
    expect(text).toMatch(/Jane Street/);
    expect(text).not.toMatch(/jane-street/);
  });

  it("an unexplained failure says the screen's own sentence; without one, the generic line", () => {
    const crash = new ApiError("Traceback: KeyError 'x'", 500, "server");
    expect(errorText(crash, "Couldn't save it. Try again.")).toBe("Couldn't save it. Try again.");
    expect(errorText(crash)).toBe(msg("error-server"));
    expect(errorText(new Error("TypeError: undefined is not a function"))).toBe(msg("error-generic"));
  });

  it("never returns the English it was given", () => {
    for (const code of ["server", "unknown", "invalid-input", "job-not-found", "offline"] as const) {
      expect(errorText(new ApiError("SECRET ENGLISH", 400, code))).not.toMatch(/SECRET/);
      expect(errorText(new ApiError("SECRET ENGLISH", 400, code), "Fallback.")).not.toMatch(/SECRET/);
    }
  });
});

it.each(["future-code", "constructor", "toString", "__proto__", null, 12])("an unknown or malformed code %s has a total fallback", async (code) => {
  answer(409, { detail: { code, params: { companies: {}, company: [null] } } });
  const error = await failure();
  expect(errorText(error, "screen fallback")).toBe("screen fallback");
  expect(errorText(error)).toBe(msg("error-generic"));
});
it("malformed parameters never crash a known error renderer", async () => {
  answer(409, { detail: { code: "scheduling-unavailable", params: { companies: {} } } });
  expect(() => errorText(new ApiError("log",409,"scheduling-unavailable",{}))).not.toThrow();
  const error = await failure();
  expect(() => errorText(error)).not.toThrow();
});
