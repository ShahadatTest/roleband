// Half of the deliberate cycle. See README.md in this directory.
import { second } from "./second";

export function first(): number {
  return second() + 1;
}
