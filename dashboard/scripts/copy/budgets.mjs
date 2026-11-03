/* Each lazy language has its own reviewed raw/gzip ceiling. A shell reduction
 * cannot conceal growth in a language that an English reader never downloads. */
import {gzipSync} from 'node:zlib';
export function budgetProblems(code,content,budget) {
  if(!budget?.why || !Number.isInteger(budget.bytes) || !Number.isInteger(budget.gzip))return [`${code}: declare bytes, gzip and why`];
  const raw=Buffer.byteLength(content), gzip=gzipSync(content).length;
  return [raw>budget.bytes?`${code}: raw ${raw} > ${budget.bytes}`:null,gzip>budget.gzip?`${code}: gzip ${gzip} > ${budget.gzip}`:null].filter(Boolean);
}
