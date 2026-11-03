/* The error shape both capability dialogs write into.
 *
 * It lives apart from `CapabilitiesCard` because both dialogs are their own
 * modules and the card composes them: importing this from the card would be a
 * child importing its own parent, which `import/no-cycle` refuses. */

import { errorText } from "../../api/errorText";

/** A failed action, carried together with the verb that failed. Both dialogs
 *  write save, delete and test failures into one `error` slot, so a fixed
 *  heading on the strip that shows it would be wrong two times in three (a
 *  failed connection test would read "Could not save"). */
export type DialogError = { lead: string; detail: string };

export const failed = (lead: string, e: unknown): DialogError => ({
  lead,
  detail: errorText(e),
});
