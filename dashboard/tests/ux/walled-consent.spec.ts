/* Walled companies follow only with the user's consent.

   A company whose source limits automated collection — robots.txt disallows
   the route RoleBand requests — is followed through its own dialog, and a
   follow from before consent existed is kept but not scanned until the user
   answers. DeepMind is added to the shared register fixture here, followed and
   unconsented, the state a real install is in after the upgrade. */

import { expect, test } from "./fixtures";
import { companyDiscovery, installSettingsRoutes } from "./settingsHarness";

const deepmind = {
  slug: "google-deepmind", display: "Google DeepMind", careers_url: "https://deepmind.google/careers",
  sectors: ["ai"], aliases: [], connector_state: "family" as const,
  parked_reason: null, selectable: true, tracked: true, enabled: true,
  visible: true, builtin: false, curated: false, directory: false, wall: "robots" as const, consented: false, status: "active",
};

test.beforeEach(async ({ page }) => {
  await installSettingsRoutes(page);
  await page.route("/api/companies/discovery", (route) =>
    route.fulfill({ json: { ...companyDiscovery, companies: [...companyDiscovery.companies, deepmind] } }));
});

test("a walled company waiting for consent is named, and Review records the words shown", async ({ page }) => {
  const writes: { follow: string[]; consents: { slug: string; text: string; locale:string }[] }[] = [];
  await page.route("/api/companies/selection", async (route) => {
    const body = route.request().postDataJSON();
    writes.push(body);
    await route.fulfill({
      json: {
        ...companyDiscovery,
        companies: [...companyDiscovery.companies, { ...deepmind, consented: true }],
      },
    });
  });
  await page.goto("/settings/companies");

  const strip = page.getByRole("region", { name: "Companies needing attention" });
  await expect(strip).toContainText("1 followed company waits for your consent");
  await expect(page.getByRole("region", { name: "AI", exact: true }).getByText("Needs consent")).toBeVisible();

  await strip.getByRole("button", { name: "Review Google DeepMind" }).click();
  const ask = page.getByRole("dialog", { name: "Follow Google DeepMind?" });
  // The consent wording, spelled out: it is the text a user agrees to and the
  // text counsel reads, so a change to it must be deliberate enough to change
  // this line too.
  await expect(ask.locator("p")).toHaveText([
    "Its careers site limits automated collection.",
    "By following, you choose to collect Google DeepMind's public job listings. "
      + "You can unfollow at any time, and collection stops.",
  ]);
  // The safe answer holds focus: Enter on the fresh dialog consents to nothing.
  await expect(ask.getByRole("button", { name: "Cancel" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(ask).toBeHidden();
  expect(writes).toEqual([]);

  await strip.getByRole("button", { name: "Review Google DeepMind" }).click();
  const heading = await ask.getByRole("heading").innerText();
  const paragraphs = await ask.locator("p").allInnerTexts();
  const shown = [heading, ...paragraphs].join("\n\n");
  // "The words shown" must be ALL the words shown: nothing in the dialog may
  // sit outside the heading and paragraphs the consent records, beyond the
  // two answers themselves.
  const buttons = await ask.getByRole("button").allInnerTexts();
  const everything = (await ask.innerText()).replace(/\s+/g, " ").trim();
  expect(everything).toBe([heading, ...paragraphs, ...buttons].join(" ").replace(/\s+/g, " ").trim());
  await ask.getByRole("button", { name: "Follow Google DeepMind" }).click();

  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0].follow).toEqual(["google-deepmind"]);
  expect(writes[0].consents).toEqual([{ slug: "google-deepmind", text: shown,locale:"en" }]);
  await expect(strip).toBeHidden();
});

/* Consent is asked once per company. The backend keeps `consented` true after an
   unfollow and after the register changes; given that, following again writes
   the follow with no dialog and no new consent. The unconsented case is the
   negative control: the same click asks. */
async function followUnfollowedDeepmind(page: import("@playwright/test").Page, consented: boolean) {
  const unfollowed = { ...deepmind, enabled: false, consented };
  await page.route("/api/companies/discovery", (route) =>
    route.fulfill({ json: { ...companyDiscovery, companies: [...companyDiscovery.companies, unfollowed] } }));
  const writes: { follow: string[]; consents?: unknown[] }[] = [];
  await page.route("/api/companies/selection", async (route) => {
    writes.push(route.request().postDataJSON());
    await route.fulfill({
      json: { ...companyDiscovery, companies: [...companyDiscovery.companies, { ...unfollowed, enabled: true, consented: true }] },
    });
  });
  await page.goto("/settings/companies");
  await page.getByRole("region", { name: "AI", exact: true })
    .getByRole("checkbox", { name: "Google DeepMind", exact: true }).click();
  return { writes, ask: page.getByRole("dialog", { name: "Follow Google DeepMind?" }) };
}

test("following a company again after unfollowing it never asks a second time", async ({ page }) => {
  const { writes, ask } = await followUnfollowedDeepmind(page, true);
  await expect.poll(() => writes.length).toBe(1);
  await expect(ask).toHaveCount(0);
  expect(writes[0].follow).toEqual(["google-deepmind"]);
  expect(writes[0].consents ?? []).toEqual([]);
});

test("following a walled company the user never answered for still asks", async ({ page }) => {
  const { writes, ask } = await followUnfollowedDeepmind(page, false);
  await expect(ask).toBeVisible();
  expect(writes).toEqual([]);
});

test("a Spanish confirmation submits its displayed wording and language together",async({page})=>{
  await page.addInitScript(()=>localStorage.setItem("roleband.locale",JSON.stringify({language:"es",region:"es-ES"})));
  await page.route("/api/settings/locale",route=>route.fulfill({json:{language:"es",region:"es-ES"}}));
  const writes: {consents:{slug:string;text:string;locale:string}[]}[]=[];
  await page.route("/api/companies/selection",async route=>{
    writes.push(route.request().postDataJSON());
    await route.fulfill({json:{...companyDiscovery,companies:[...companyDiscovery.companies,{...deepmind,consented:true}]}});
  });
  await page.goto("/settings/companies");
  await expect(page.locator("html")).toHaveAttribute("lang","es");
  // The stable attention surface scopes a company-named action across languages.
  await page.locator(".ledger-attention").getByRole("button",{name:/Google DeepMind/}).click();
  const ask=page.getByRole("dialog");
  const heading=await ask.getByRole("heading").innerText();
  expect(heading).not.toBe("Follow Google DeepMind?");
  const shown=[heading,...await ask.locator("p").allInnerTexts()].join("\n\n");
  expect(shown).toContain("Its careers site limits automated collection.");
  await ask.getByRole("button",{name:/Google DeepMind/}).click();
  await expect.poll(()=>writes.length).toBe(1);
  expect(writes[0].consents).toEqual([{slug:"google-deepmind",text:shown,locale:"es"}]);
});
