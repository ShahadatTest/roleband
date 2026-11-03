import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SettingsDesignSystemRoot } from "./SettingsDesignSystemRoot";

const HERE = dirname(fileURLToPath(import.meta.url));

describe("Settings design-system boundary", () => {
  it("marks the route, and leaves the body alone", () => {
    const view = render(
      <SettingsDesignSystemRoot>
        <h1>Settings test</h1>
      </SettingsDesignSystemRoot>,
    );

    expect(screen.getByRole("main")).toHaveAttribute("data-design-system", "settings");

    /* No body marker: a portal carries its paint in the sheet that owns it,
     * which also works on the routes that are not Settings — the ScopeGuide
     * drawer opens from Profile.
     *
     * Global state set on mount is worth a standing test even when it is
     * absence: a marker creeping back in would be invisible without this
     * line. */
    expect(document.body).not.toHaveAttribute("data-settings-design-system");

    view.unmount();
    expect(document.body).not.toHaveAttribute("data-settings-design-system");
  });

  /* Companies and Intelligence consume the same --app-* namespace, worn with
   * the register material (design/materials/register-material.css); their
   * screen contracts live in
   * features/companies/register.test.ts and intelligence-scope.test.ts. */
  it("keeps Settings-owned styles on the dedicated token namespace", () => {
    const settingsCss = readFileSync(join(HERE, "..", "design", "settings.css"), "utf8");
    const scheduleCss = readFileSync(
      join(HERE, "..", "features", "settings", "ScheduleSection.css"),
      "utf8",
    );
    const componentVariables = new Set(["--band-size", "--band-start", "--dial-size", "--gate-delay", "--pos"]);
    const consumedTokens = [...`${settingsCss}\n${scheduleCss}`.matchAll(/var\((--[\w-]+)/g)]
      .map((match) => match[1])
      .filter((token) => !componentVariables.has(token));

    expect(consumedTokens.length).toBeGreaterThan(0);
    expect(consumedTokens.every((token) => token.startsWith("--app-"))).toBe(true);
  });

  /* No quarantine assertion: there is one vocabulary and no second sheet to
     quarantine from, so aliasing two namespaces cannot happen, and the
     assertion above — that Settings-owned CSS consumes --app-* and
     nothing else — is the whole contract. */
});
