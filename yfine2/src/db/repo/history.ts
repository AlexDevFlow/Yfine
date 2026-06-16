/**
 * Time-series helpers for the dashboard net-worth chart and the per-source
 * sparklines. Cash-only (no FX mixing, no portfolio market-value history):
 * balance(date) = starting_balance + running sum of signed movements up to date.
 * Same-currency transfer legs cancel (out −amt, in +amt), so they don't move
 * net worth — exactly like getBalancesBatch.
 */
import type { SqlExecutor } from "../types";
import { round2 } from "@/domain/money";

export interface HistoryPoint {
  date: string; // YYYY-MM-DD
  value: number;
}

function cumulative(start: number, deltas: { date: string; delta: number }[]): HistoryPoint[] {
  let acc = round2(start);
  const out: HistoryPoint[] = [];
  for (const d of deltas) {
    acc = round2(acc + d.delta);
    out.push({ date: d.date, value: acc });
  }
  return out;
}

/** Net-worth-over-time for one currency (all that currency's sources combined). */
export async function netWorthHistory(db: SqlExecutor, currency: string): Promise<HistoryPoint[]> {
  const startRow = await db.select<{ s: number }>(
    `SELECT COALESCE(SUM(starting_balance),0) s FROM sources WHERE currency = ?`,
    [currency],
  );
  const start = startRow[0]?.s ?? 0;
  const deltas = await db.select<{ date: string; delta: number }>(
    `SELECT m.date AS date,
        SUM(CASE WHEN m.direction='in' THEN m.amount ELSE -m.amount END) AS delta
     FROM movements m JOIN sources s ON m.source_id = s.id
     WHERE s.currency = ?
     GROUP BY m.date ORDER BY m.date ASC`,
    [currency],
  );
  const series = cumulative(start, deltas);
  // Lead with the opening balance so a flat start is visible.
  if (series.length && start !== series[0].value) {
    series.unshift({ date: series[0].date, value: round2(start) });
  }
  return series;
}

/** Running balance for a single source over time. */
export async function sourceBalanceHistory(db: SqlExecutor, sourceId: number): Promise<HistoryPoint[]> {
  const startRow = await db.select<{ s: number }>(
    `SELECT COALESCE(starting_balance,0) s FROM sources WHERE id = ?`,
    [sourceId],
  );
  const start = startRow[0]?.s ?? 0;
  const deltas = await db.select<{ date: string; delta: number }>(
    `SELECT date,
        SUM(CASE WHEN direction='in' THEN amount ELSE -amount END) AS delta
     FROM movements WHERE source_id = ?
     GROUP BY date ORDER BY date ASC`,
    [sourceId],
  );
  return cumulative(start, deltas);
}

/** Movement count per source id (both transfer legs counted). */
export async function movementCounts(db: SqlExecutor): Promise<Map<number, number>> {
  const rows = await db.select<{ source_id: number | null; c: number }>(
    `SELECT source_id, COUNT(*) c FROM movements WHERE source_id IS NOT NULL GROUP BY source_id`,
  );
  return new Map(rows.map((r) => [r.source_id as number, r.c]));
}
