import { LEVEL_NOT_PLACED_OPTION, UNSTATED_LEVEL } from "../../../copy/vocabulary";
import { BAND_LABEL } from "../../../format";

/** A Pay row's level in words: a rung, or "Level not placed" for the roles
 *  whose level we cannot place, which the server counts under their own key,
 *  never under the Mid their sort default says. */
export function levelLabel(key: string): string {
  return key === UNSTATED_LEVEL ? LEVEL_NOT_PLACED_OPTION() : BAND_LABEL[key] ?? key;
}
