export type UxMode = "dev" | "build" | "preview";

/** Where a test server proxies `/api` unless VITE_API_TARGET names another target.
 *  Specs mock the API and the guard aborts what none claimed, but WebKit can
 *  release a request a spec parked and never answered after its test ends; at a
 *  dead port it is refused instead of reaching an API running on this machine. */
const DEAD_API_TARGET = "http://127.0.0.1:9";

function positiveInteger(value: string, name: string, maximum = Number.MAX_SAFE_INTEGER): number {
  const number = Number(value);
  if (!/^\d+$/.test(value) || !Number.isSafeInteger(number) || number < 1 || number > maximum) {
    throw new Error(`${name} must be an integer between 1 and ${maximum}`);
  }
  return number;
}

export function uxProfile(env: NodeJS.ProcessEnv = process.env) {
  const mode = env.ROLEBAND_UX_MODE ?? (env.CI ? "build" : "dev");
  if (mode !== "dev" && mode !== "build" && mode !== "preview") {
    throw new Error("ROLEBAND_UX_MODE must be dev, build or preview");
  }
  const port = positiveInteger(env.ROLEBAND_UX_PORT ?? "5173", "ROLEBAND_UX_PORT", 65535);
  const workers = env.ROLEBAND_UX_WORKERS === undefined
    ? (env.CI ? 2 : undefined)
    : positiveInteger(env.ROLEBAND_UX_WORKERS, "ROLEBAND_UX_WORKERS");
  const preview = `npm run preview -- --host 127.0.0.1 --port ${port} --strictPort`;
  return {
    mode: mode as UxMode,
    port,
    baseURL: `http://127.0.0.1:${port}`,
    workers,
    forbidOnly: !!env.CI || mode !== "dev",
    outputDir: env.ROLEBAND_UX_OUTPUT_DIR ?? "test-results",
    apiTarget: env.VITE_API_TARGET ?? DEAD_API_TARGET,
    command: mode === "dev"
      ? `npm run dev -- --host 127.0.0.1 --port ${port} --strictPort`
      : mode === "build" ? `npm run build && ${preview}` : preview,
  };
}
