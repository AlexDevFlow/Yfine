/**
 * Source periodic yield/interest accrual — idempotent, compounding, with
 * missed-period catch-up. Faithful port of services/sources.py accrual.
 * Invariants (see refactor-analysis/sources-savings.md §D):
 *  - active iff rate > 0 AND period > 0; otherwise next_date = null (skipped).
 *  - next_date = (last_date ?? today) + period months.
 *  - catch up every missed period in one pass (cap 600); never credit a date
 *    twice (break when last_date === next_date).
 *  - interest = round2(cashBalance * rate/100); post a movement ONLY when > 0
 *    (a source in the red is never charged), but ALWAYS advance the schedule.
 *  - interest compounds: each posted credit is visible to the next iteration.
 */
import { addMonthsISO } from "@/lib/date";
import { round2 } from "./money";

const MAX_ITERATIONS = 600;

export interface YieldState {
  yield_rate: number;
  yield_period_months: number;
  yield_last_date: string | null;
  yield_next_date: string | null;
}

/** Recompute next accrual date when the schedule is (re)anchored. */
export function resyncYieldSchedule(
  rate: number,
  periodMonths: number,
  lastDate: string | null,
  today: string,
): string | null {
  if (rate > 0 && periodMonths > 0) {
    return addMonthsISO(lastDate ?? today, periodMonths);
  }
  return null;
}

export interface YieldAccrualPort {
  /** Current cash balance of the source (excludes portfolio value). */
  getBalance(sourceId: number): Promise<number>;
  /** Post an `in` interest movement dated `dateISO`. */
  postInterest(
    sourceId: number,
    amount: number,
    dateISO: string,
    note: string,
  ): Promise<void>;
}

export interface AccrualResult {
  created: number;
  yield_last_date: string | null;
  yield_next_date: string | null;
}

/**
 * Accrue all due periods for one source up to `today`. Returns the number of
 * interest movements created and the advanced schedule (caller persists it).
 */
export async function accrueSource(
  source: { id: number } & YieldState,
  port: YieldAccrualPort,
  today: string,
  makeNote: (rate: number, period: number) => string,
): Promise<AccrualResult> {
  let last = source.yield_last_date;
  let next = source.yield_next_date;
  let created = 0;

  if (!(source.yield_rate > 0) || !next) {
    return { created, yield_last_date: last, yield_next_date: next };
  }

  let guard = 0;
  while (next && next <= today && guard < MAX_ITERATIONS) {
    guard += 1;
    if (last === next) break; // idempotency: already credited this date
    const balance = await port.getBalance(source.id);
    const interest = round2((balance * source.yield_rate) / 100);
    const accrualDate = next;
    if (interest > 0) {
      await port.postInterest(
        source.id,
        interest,
        accrualDate,
        makeNote(source.yield_rate, source.yield_period_months),
      );
      created += 1;
    }
    last = accrualDate;
    next = addMonthsISO(accrualDate, source.yield_period_months);
  }

  return { created, yield_last_date: last, yield_next_date: next };
}
