import { Fragment, type ReactNode } from "react";
import { F } from "../copy/runtime";

/* A sentence with elements inside it, kept whole (docs/copy.md, Ownership).
 *
 * The message is called with a private-use token in place of each element, so
 * the translated sentence decides where the element goes; the string is then
 * split on the tokens and the elements put back. A sentence split across JSX
 * elements around `{expr}` cannot be reordered by a translator; this can. */

const OPEN = "";
const CLOSE = "";
const TOKEN = /(\d+)/;

type Message = (a: never) => string;
type Arguments<Fn extends Message> = Parameters<Fn>[0];
type SlotKeys<Fn extends Message> = Exclude<keyof Arguments<Fn>, Fn extends { readonly __copySelectors?: infer S } ? S : never>;
type Props<Fn extends Message, E extends Partial<Record<SlotKeys<Fn>, ReactNode>>> = {
  of: Fn;
  elems: E & Record<Exclude<keyof E, SlotKeys<Fn>>, never>;
} & (Exclude<keyof Arguments<Fn>, keyof E> extends never
  ? { args?: Record<string, never> }
  : { args: Omit<Arguments<Fn>, keyof E> });

/** Required parameters are supplied exactly once, as data or rich elements. */
export function Msg<Fn extends Message, E extends Partial<Record<SlotKeys<Fn>, ReactNode>>>({ of, args, elems }: Props<Fn,E>) {
  const names = Object.keys(elems);
  const tokens = Object.fromEntries(names.map((name, i) => [name, `${OPEN}${i}${CLOSE}`]));
  const parts = (of as unknown as (a: Record<string, unknown>) => string)({ ...args, ...tokens }).split(TOKEN);
  return (
    <>
      {parts.map((part, i) =>
        i % 2 === 1 ? <Fragment key={i}>{typeof elems[names[Number(part)] as keyof E] === "number" ? F(elems[names[Number(part)] as keyof E]) : elems[names[Number(part)] as keyof E] as ReactNode}</Fragment> : part ? <Fragment key={i}>{part}</Fragment> : null,
      )}
    </>
  );
}
