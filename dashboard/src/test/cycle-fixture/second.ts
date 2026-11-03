// The other half of the deliberate cycle. See README.md in this directory.
import { first } from "./first";

export function second(): number {
  return typeof first === "function" ? 1 : 0;
}
