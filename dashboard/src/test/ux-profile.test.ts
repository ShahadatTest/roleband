// @vitest-environment node
import { describe, expect, it } from "vitest";
import { uxProfile } from "../../tests/ux/runProfile";

describe("browser execution profiles", () => {
  it("runs a local built app with strict collection and the local worker default", () => {
    const profile = uxProfile({ ROLEBAND_UX_MODE: "build", ROLEBAND_UX_PORT: "5187" });
    expect(profile.command).toBe("npm run build && npm run preview -- --host 127.0.0.1 --port 5187 --strictPort");
    expect(profile.baseURL).toBe("http://127.0.0.1:5187");
    expect(profile.forbidOnly).toBe(true);
    expect(profile.workers).toBeUndefined();
  });

  it("previews a prepared build without rebuilding it", () => {
    const profile = uxProfile({ ROLEBAND_UX_MODE: "preview", ROLEBAND_UX_OUTPUT_DIR: "/tmp/isolated-results" });
    expect(profile.command).toBe("npm run preview -- --host 127.0.0.1 --port 5173 --strictPort");
    expect(profile.forbidOnly).toBe(true);
    expect(profile.outputDir).toBe("/tmp/isolated-results");
  });

  it("keeps the hosted CI default and accepts an explicit local worker budget", () => {
    expect(uxProfile({ CI: "1" }).workers).toBe(2);
    expect(uxProfile({ CI: "1", ROLEBAND_UX_WORKERS: "6" }).workers).toBe(6);
    expect(uxProfile({ CI: "1", ROLEBAND_UX_WORKERS: "6" }).mode).toBe("build");
    expect(uxProfile({}).command).toBe("npm run dev -- --host 127.0.0.1 --port 5173 --strictPort");
  });

  it.each(["0", "-1", "1.5", "NaN", "", "4; echo unsafe"])("refuses invalid workers %j", (value) => {
    expect(() => uxProfile({ ROLEBAND_UX_WORKERS: value })).toThrow("ROLEBAND_UX_WORKERS");
  });

  it.each(["0", "65536", "5173 --host example.com"])("refuses invalid port %j", (value) => {
    expect(() => uxProfile({ ROLEBAND_UX_PORT: value })).toThrow("ROLEBAND_UX_PORT");
  });

  it.each(["dev", "build", "preview"])("never proxies a %s test server to a live API unless told to", (mode) => {
    expect(uxProfile({ ROLEBAND_UX_MODE: mode }).apiTarget).toBe("http://127.0.0.1:9");
    expect(uxProfile({ ROLEBAND_UX_MODE: mode, VITE_API_TARGET: "http://127.0.0.1:8011" }).apiTarget)
      .toBe("http://127.0.0.1:8011");
  });

  it("refuses an unknown serving mode", () => {
    expect(() => uxProfile({ ROLEBAND_UX_MODE: "reuse" })).toThrow("ROLEBAND_UX_MODE");
  });
});
