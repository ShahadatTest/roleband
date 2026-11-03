/* A followed company whose careers page is gone from the address RoleBand reads,
 * because it moved to another board or took a new name. The Coverage
 * notice for it is the one place the person can answer, so its row carries the
 * answers. Pure: which row is one, and the words for what was found. */

import type { MovedBoard } from "../../../api";
import {
  notificationsModelFoundItRolebandSawAt,
  notificationsModelFoundItRolebandSawAt2,
  notificationsModelOfThemRoles,
  notificationsModelRoles,
  notificationsModelSOwnCareersPageLinks,
  notificationsModelThatPageLists,
} from "../../../copy/gen/notifications";

export interface MovedPage {
  /** The company's slug, which the answers are addressed to. */
  company: string;
  /** The name the notice uses. */
  display: string;
}

/** The company a Coverage row is about, when its careers page is gone. */
export function movedPageOf(
  category: string,
  meta: Record<string, unknown> | null | undefined,
): MovedPage | null {
  if (category !== "coverage" || !meta || meta.cause !== "board_missing") return null;
  const company = typeof meta.company === "string" ? meta.company : null;
  if (!company) return null;
  const display = typeof meta.display === "string" && meta.display ? meta.display : company;
  return { company, display };
}

const roles = (count: number) => notificationsModelRoles({ count: count, count2: count });

/** What RoleBand found, said as the evidence it found it by. */
export function foundSentence(board: MovedBoard, display: string): string {
  if (board.found_by === "address") {
    return notificationsModelThatPageLists({ choice: (board.roles === null) ? "yes" : "no", roles: (board.roles === null) ? "" : String(roles(board.roles)) });
  }
  if (board.found_by === "page") {
    return notificationsModelSOwnCareersPageLinks({ choice: (board.roles === null) ? "yes" : "no", display: (board.roles === null) ? String(display) : "", display2: (board.roles === null) ? "" : String(display), roles: (board.roles === null) ? "" : String(roles(board.roles)) });
  }
  // Guessed from the name: the overlap is the reason to believe it.
  // "of them" needs the total said first; without one the count stands alone.
  if (board.roles === null) return notificationsModelFoundItRolebandSawAt({ shared: String(roles(board.shared)), display: String(display) });
  const seen = notificationsModelOfThemRoles({ count: board.shared, shared: (board.shared === 1) ? "" : board.shared });
  return notificationsModelFoundItRolebandSawAt2({ roles: String(roles(board.roles)), seen: String(seen), display: String(display) });
}
