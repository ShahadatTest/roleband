import type { ReactNode } from "react";
import { sharedResultsCompany, sharedResultsOfCompany, sharedResultsOfRole, sharedResultsRole } from "../copy/gen/shared";
import { number } from "../copy/format";
import { Msg } from "../ui/Msg";

/* What a summary can count. One whole message per noun and shape, so the
   language orders "197 of 219 roles" itself; the numbers are elements placed
   by <Msg>. A noun is added here with its two messages. */
const SAY = {
  role: { count: sharedResultsRole, of: sharedResultsOfRole },
  company: { count: sharedResultsCompany, of: sharedResultsOfCompany },
} as const;

/** A measured count, not a query controller. Callers own reset semantics. */
export function ResultsSummary({ count, total, noun, prefix, meta, reset }: {
  count: number;
  /** Omit while the denominator is unknown; zero is an exact denominator. */
  total?: number | null;
  noun: keyof typeof SAY;
  prefix?: ReactNode;
  meta?: ReactNode;
  reset?: ReactNode;
}) {
  const n = <strong>{number(count)}</strong>;
  return (
    <div className="results-count" data-selection="chrome">
      {prefix != null && <>{prefix}{" "}</>}
      {total != null ? (
        <Msg of={SAY[noun].of} args={{ total }} elems={{ n, t: <strong>{number(total)}</strong> }} />
      ) : (
        <Msg of={SAY[noun].count} args={{ count }} elems={{ n }} />
      )}
      {meta}
      {reset && (
        <>
          {" "}<span className="results-sep" aria-hidden="true">·</span>{" "}
          {reset}
        </>
      )}
    </div>
  );
}
