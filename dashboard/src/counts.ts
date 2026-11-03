/** A large count as a round number: exact below 1,000, then to the hundred,
    then to the thousand. Always down, so a "12,000+" never overstates, and
    every screen that rounds one count says the same number. Its own module,
    not `format.ts` or `labels.ts`: only lazy screens round a count, and the
    welcome's chunk importing either reshapes the startup chunks and grows the
    shell. */
export function roundCount(n: number): number {
  const step = n >= 10_000 ? 1_000 : n >= 1_000 ? 100 : 1;
  return Math.floor(n / step) * step;
}
