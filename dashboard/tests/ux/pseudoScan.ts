import type { Page } from "./fixtures";

/* The pseudo locale's scan (docs/copy.md, section 7).
 *
 * Under `en-XA` every catalog message is accented and bracketed (⟦…⟧), so any
 * text left plain is text the catalog does not hold. A screen passes when all
 * it shows, and every accessible name, label and placeholder it carries, is
 * said, is a formatted figure ($650K, 12%), or is marked as third-party text
 * (`ui/Content`, `data-copy`). */

/** Boot straight into the pseudo locale: a pseudo locale is a device-only
 *  check, and it wins over the account's choice while it is chosen. */
export async function bootPseudo(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem("roleband.copy-check", "1");
    localStorage.setItem("roleband.locale", JSON.stringify({ language: "en-XA", region: null }));
  });
  await page.route("/api/settings/locale", (route) => route.fulfill({ json: { language: "en", region: null } }));
}

/** Every text and attribute under `selector` that the pseudo locale leaves plain. */
export async function unbracketed(page: Page, selector = "main"): Promise<string[]> {
  return page.evaluate((sel) => {
    const out: string[] = [];
    // A sentence with elements inside it (`<Msg>`) splits into text nodes: the
    // brackets sit on its first and last, and a middle one is said when the
    // pseudo locale accented every letter in it.
    const said = (t: string) => {
      let rest = "", depth = 0, start = 0;
      for (let i=0;i<t.length;i++) {
        if(t[i]==="⟦") {if(depth===0){rest+=t.slice(start,i);start=i+1;}depth++;}
        else if(t[i]==="⟧") {if(depth>0){depth--;if(depth===0)start=i+1;}else {rest+=t.slice(start,i);start=i+1;}}
      }
      rest += t.slice(start);
      if(depth===0 && start>0 && t[start-1]!=="⟧") rest=t;
      // Split rich sentences have accented fragments between their elements.
      // Non-Latin literal copy and plain suffixes must still fail this scan.
      return !/\p{L}/u.test(rest.replace(/[àƀçðéƒĝĥîĵķļɱñöþǫŕšţûṽŵẋýžÀßÇÐÉƑĜĤÎĴĶĻṀÑÖÞǪŔŠŢÛṼŴẊÝŽ]/g, ""));
    };
    const figure = /^[\p{Sc}\d\s.,:–+%−KMB-]+$/u;
    const roots = document.querySelectorAll(sel);
    // No match is scanned as the whole page, never as nothing.
    for (const root of roots.length > 0 ? [...roots] : [document.body]) {
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
      for (let n = walker.nextNode(); n; n = walker.nextNode()) {
        const text = (n.textContent ?? "").trim();
        const el = n.parentElement;
        if (!text || !/\p{L}/u.test(text) || !el?.offsetParent || figure.test(text)) continue;
        if (el.closest("[aria-hidden='true'], [data-copy='content'], [data-copy='diagnostic'], [data-copy='glyph'], textarea[data-copy='code'], pre[data-copy='code']") || said(text)) continue;
        out.push(text);
      }
      for (const el of root.querySelectorAll("[aria-label], [title], [placeholder]")) {
        // A name RoleBand did not write (`data-copy="content"`, e.g. a company switch).
        if (el.closest("[data-copy='content'], [data-copy='diagnostic'], [data-copy='glyph']")) continue;
        for (const attr of ["aria-label", "title", "placeholder"]) {
          const value = el.getAttribute(attr);
          const repeatedContent = [...el.querySelectorAll("[data-copy='content']")].some(child=>value===child.textContent?.trim());
          // A tooltip that repeats the element's own (third-party) text adds no copy.
          if (!value || !/\p{L}/u.test(value) || said(value) || repeatedContent) continue;
          out.push(`${attr}=${value}`);
        }
      }
    }
    return out;
  }, selector);
}
