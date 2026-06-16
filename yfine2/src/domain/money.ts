/**
 * Money math. The on-disk schema stores amounts as SQLite FLOAT (a known
 * imprecision the legacy app lives with); we mirror its `round(x, 2)` at the
 * same boundaries so balances/history reproduce identical numbers.
 */

/** Round to 2 decimals, half away from zero, compensating binary float error. */
export function round2(n: number): number {
  if (!Number.isFinite(n)) return n;
  const sign = n < 0 ? -1 : 1;
  return (sign * Math.round((Math.abs(n) + Number.EPSILON) * 100)) / 100;
}

export type Direction = "in" | "out";

export interface BalanceMovement {
  direction: Direction;
  amount: number;
}

/**
 * Source balance = round(starting_balance + Σin − Σout, 2).
 * Derived, never stored. Zero-movement sources fall back to starting_balance.
 */
export function computeBalance(
  startingBalance: number,
  movements: readonly BalanceMovement[],
): number {
  let sum = startingBalance;
  for (const m of movements) {
    sum += m.direction === "in" ? m.amount : -m.amount;
  }
  return round2(sum);
}

/**
 * Net worth grouped per currency (NEVER summed across currencies — there is no
 * automatic FX conversion; that's an opt-in feature added later).
 */
export function netWorthByCurrency(
  entries: readonly { currency: string; balance: number }[],
): Record<string, number> {
  const out: Record<string, number> = {};
  for (const e of entries) {
    out[e.currency] = round2((out[e.currency] ?? 0) + e.balance);
  }
  return out;
}
