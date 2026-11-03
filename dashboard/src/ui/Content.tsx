/* Text RoleBand did not write (docs/copy.md): a company's
 * name, a role's title, an employer's heading, a city. Shown as written and
 * never translated: `translate="no"` tells browser translation and the
 * pseudo-locale check alike, `lang` says what language it is in where known,
 * and `dir="auto"` keeps a Latin name from reordering a right-to-left sentence.
 *
 * It takes a string, never children, so it cannot wrap copy by accident. */
export function Content({
  text,
  lang,
  className,
  highlight,
}: {
  text: string;
  lang?: string;
  className?: string;
  /** A search's match inside the text, marked where it falls. */
  highlight?: string;
}) {
  const at = highlight ? text.toLocaleLowerCase().indexOf(highlight.toLocaleLowerCase()) : -1;
  return (
    <span translate="no" lang={lang} dir="auto" data-copy="content" className={className}>
      {at < 0 ? text : (
        <>
          {text.slice(0, at)}
          <mark>{text.slice(at, at + (highlight ?? "").length)}</mark>
          {text.slice(at + (highlight ?? "").length)}
        </>
      )}
    </span>
  );
}

/** Engineering text shown only behind the diagnostics toggle: run notes,
 *  drift messages, raw counters. English, untranslated, and out of the
 *  product language's rules. */
export function Diagnostic({ text, className }: { text: string; className?: string }) {
  return (
    <span translate="no" lang="en" dir="ltr" data-copy="diagnostic" className={className}>
      {text}
    </span>
  );
}
