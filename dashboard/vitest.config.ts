import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { copyCatalog } from "./scripts/copy/vite-plugin.mjs";

// Native bundler callbacks need objects from Node's own realm.
const nativeTests = ["src/test/bundle-gate.test.ts"];

export default defineConfig({
  plugins: [react(), copyCatalog()],
  test: {
    globals: false,
    projects: [
      {
        extends: true,
        test: { name: "native", pool: "forks", environment: "node", isolate: true, include: nativeTests },
      },
      {
        extends: true,
        test: {
          name: "ui",
          pool: "vmThreads",
          vmMemoryLimit: "512MB",
          isolate: true,
          environment: "jsdom",
          include: ["src/**/*.test.{ts,tsx}"],
          exclude: nativeTests,
          setupFiles: ["./src/test/setup.ts"],
        },
      },
    ],
  },
});
