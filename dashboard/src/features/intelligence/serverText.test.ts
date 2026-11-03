// The AI screen says the server's codes itself: availability by
// state, where a test ran by origin, why a test shows no band, fit bands by key.
import { afterEach, describe, expect, it } from "vitest";
import type { IntelligenceTestResult } from "../../api";
import { activate } from "../../copy/activate";
import { availabilityText, fitBandName, originText, testReason } from "./serverText";

afterEach(() => activate("en"));

const base = {
  availability: { state: "available" as const, ok: true, detail: null },
  used_sample: true, prompt_version: "v1", model_id: "apple-fm", expected: null,
};

describe("the AI screen's server codes", () => {
  it("says why a test found no band, by the keys its outcome carries", () => {
    const prefiltered = { ...base, ok: true, prefiltered: true, raw: null, extracted: null } as IntelligenceTestResult;
    expect(testReason(prefiltered)).toMatch(/^No compensation found in the text/);
    const failed = {
      ...base, ok: false, failure_class: "timeout", latency_ms: 900, origin: "this_mac", left_device: false,
      answered_by: "omlx", route_reason: null, route_attempts: [],
    } as IntelligenceTestResult;
    expect(testReason(failed)).toBe("The model did not return a usable response (timeout).");
    const unavailable = { ...base, ok: false, availability: { state: "sdk_absent", ok: false, detail: "ImportError" } } as IntelligenceTestResult;
    expect(testReason(unavailable)).toMatch(/^The Apple Foundation Models SDK isn't installed/);
  });

  it("names origins and fit bands by code, the middle band as Fair", () => {
    expect(originText("cloud")).toBe("Sent to a cloud provider");
    expect(["strong", "good", "some", "weak"].map((k) => fitBandName(k as "some"))).toEqual(["Strong", "Good", "Fair", "Weak"]);
    expect(availabilityText("egress_not_permitted")).toMatch(/^Sending job text off this Mac is turned off/);
  });

  it("follows the active language, never the server's English", async () => {
    await activate("en-XA");
    expect(availabilityText("available")).toMatch(/^⟦Öñ-ðéṽîçé/);
    expect(fitBandName("some")).toMatch(/^⟦Ƒàîŕ/);
  });
});
