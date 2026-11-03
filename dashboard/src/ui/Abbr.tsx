import "./Abbr.css";

/** A short form in a column, row or chip too narrow for the full words
 *  (Est. TC). The eye reads the short form and gets the full words on hover;
 *  a screen reader hears only the full words, since `title` on its own is
 *  read unevenly and an abbreviation spoken letter by letter means nothing. */
export function Abbr({ short, full }: { short: string; full: string }) {
  return (
    <abbr className="ui-abbr" title={full}>
      <span aria-hidden="true">{short}</span>
      <span className="sr-only">{full}</span>
    </abbr>
  );
}
