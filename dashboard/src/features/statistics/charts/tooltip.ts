/* The one way a statistics chart builds its tooltip.
 *
 * ECharts writes a formatter's string into the tooltip's innerHTML, and what a
 * tooltip names (a company, a skill, a cluster) is text RoleBand did not
 * write. So the catalog messages are plain words, every string handed in here
 * is escaped, and the markup and colour classes are this file's alone. */

const ENTITY: Record<string, string> = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

/** Text as HTML that shows it as written: the escaping of echarts'
 *  `format.encodeHTML` (`tooltip.test.tsx` holds them equal). Kept here
 *  because importing echarts would pull the charting runtime, which loads
 *  lazily (`ui/EChart`), into the statistics chunk. */
export const encodeHTML = (text: string): string => text.replace(/[&<>"']/g, (c) => ENTITY[c]);

/** A tinted part of a line: today's openings and closings, in the bars' own
 *  colours. */
export type TooltipTone = "new" | "closed";
const TONE_CLASS: Record<TooltipTone, string> = { new: "chart-tip-new", closed: "chart-tip-closed" };

export type TooltipPart = string | { text: string; tone: TooltipTone };
/** A line is plain text, or parts, some tinted. */
export type TooltipLine = string | readonly TooltipPart[];

const part = (p: TooltipPart): string =>
  typeof p === "string" ? encodeHTML(p) : /* not copy: markup */ `<span class="${TONE_CLASS[p.tone]}">${encodeHTML(p.text)}</span>`;

/** The tooltip: the title in bold, then one line each. An empty line is left
 *  out. */
export function tooltipHtml(title: string, lines: readonly TooltipLine[] = []): string {
  const body = lines.map((line) => (typeof line === "string" ? encodeHTML(line) : line.map(part).join(""))).filter(Boolean);
  return [/* not copy: markup */ `<strong>${encodeHTML(title)}</strong>`, ...body].join("<br/>");
}

const OPEN = "\uE000";
const CLOSE = "\uE001";
const TOKEN = /\uE000(\d+)\uE001/;

/** A line with tinted parts inside one message, kept whole so a translation
 *  orders them: the message is called with a token per part and split on the
 *  tokens, as `ui/Msg` places elements. */
export function withParts<K extends string>(
  message: (args: Record<K, string>) => string,
  parts: Record<K, TooltipPart>,
): TooltipPart[] {
  const names = Object.keys(parts) as K[];
  const tokens = Object.fromEntries(names.map((name, i) => [name, `${OPEN}${i}${CLOSE}`])) as Record<K, string>;
  return message(tokens)
    .split(TOKEN)
    .flatMap((piece, i) => (i % 2 ? [parts[names[Number(piece)]]] : piece ? [piece] : []));
}
