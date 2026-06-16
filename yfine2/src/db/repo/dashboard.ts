/**
 * Dashboard aggregations. Faithful port of services/dashboard.py
 * (refactor-analysis/dashboard-search.md §3). Key invariants:
 *  - Net worth is PER CURRENCY, never summed across currencies, no FX.
 *  - ALL sources count toward net worth (funds, excluded, hidden).
 *  - Monthly in/out & comparison EXCLUDE transfers + exclude_from_stats.
 *  - Monthly savings counts is_savings_contribution in-legs (no double count).
 *  - Monthly comparison is ZERO-FILLED across the full range (fixes BUG-2).
 *  (Portfolio market value is added to net worth in Phase 8.)
 */
import type { SqlExecutor } from "../types";
import { netWorthByCurrency as aggregate, round2 } from "@/domain/money";
import { lastNMonths } from "@/lib/date";
import { getBalancesBatch, listSources } from "./sources";
import { totalValueByCurrency } from "./portfolios";

/** Net worth per currency = source cash balances + portfolio market value (no FX mixing). */
export async function netWorth(db: SqlExecutor): Promise<Record<string, number>> {
  const [list, balances, portfolioValue] = await Promise.all([
    listSources(db, { includeHidden: true }),
    getBalancesBatch(db),
    totalValueByCurrency(db),
  ]);
  const out = aggregate(
    list.map((s) => ({ currency: s.currency, balance: balances.get(s.id) ?? round2(s.starting_balance) })),
  );
  for (const [ccy, val] of Object.entries(portfolioValue)) {
    out[ccy] = round2((out[ccy] ?? 0) + val);
  }
  return out;
}

export interface MonthFlow {
  byCurrency: Record<string, { income: number; expense: number }>;
  externalIncome: number;
  externalExpense: number;
}

export async function monthlyFlow(db: SqlExecutor, start: string, end: string): Promise<MonthFlow> {
  const rows = await db.select<{ currency: string | null; direction: "in" | "out"; total: number }>(
    `SELECT s.currency AS currency, m.direction AS direction, SUM(m.amount) AS total
     FROM movements m LEFT JOIN sources s ON m.source_id = s.id
     WHERE m.date >= ? AND m.date <= ? AND m.transfer_pair_id IS NULL AND m.exclude_from_stats = 0
     GROUP BY s.currency, m.direction`,
    [start, end],
  );
  const out: MonthFlow = { byCurrency: {}, externalIncome: 0, externalExpense: 0 };
  for (const r of rows) {
    if (r.currency == null) {
      if (r.direction === "in") out.externalIncome = round2(r.total);
      else out.externalExpense = round2(r.total);
      continue;
    }
    const b = out.byCurrency[r.currency] ?? { income: 0, expense: 0 };
    if (r.direction === "in") b.income = round2(r.total);
    else b.expense = round2(r.total);
    out.byCurrency[r.currency] = b;
  }
  return out;
}

export async function monthlySavings(db: SqlExecutor, start: string, end: string): Promise<Record<string, number>> {
  const rows = await db.select<{ currency: string; total: number }>(
    `SELECT s.currency AS currency, SUM(m.amount) AS total
     FROM movements m JOIN sources s ON m.source_id = s.id
     WHERE m.is_savings_contribution = 1 AND m.date >= ? AND m.date <= ?
     GROUP BY s.currency`,
    [start, end],
  );
  const out: Record<string, number> = {};
  for (const r of rows) out[r.currency] = round2(r.total);
  return out;
}

export interface ComparisonPoint {
  month: string; // YYYY-MM
  income: number;
  expense: number;
}

/** Per-month income/expense for ONE currency, zero-filled across the range. */
export async function monthlyComparison(
  db: SqlExecutor,
  currency: string,
  months: number,
  today: string,
): Promise<ComparisonPoint[]> {
  const labels = lastNMonths(today, Math.max(2, Math.min(36, months)));
  const start = labels[0] + "-01";
  const rows = await db.select<{ ym: string; direction: "in" | "out"; total: number }>(
    `SELECT substr(m.date, 1, 7) AS ym, m.direction AS direction, SUM(m.amount) AS total
     FROM movements m JOIN sources s ON m.source_id = s.id
     WHERE s.currency = ? AND m.date >= ? AND m.transfer_pair_id IS NULL AND m.exclude_from_stats = 0
     GROUP BY ym, direction`,
    [currency, start],
  );
  const map = new Map<string, { income: number; expense: number }>();
  for (const l of labels) map.set(l, { income: 0, expense: 0 });
  for (const r of rows) {
    const e = map.get(r.ym);
    if (e) {
      if (r.direction === "in") e.income = round2(r.total);
      else e.expense = round2(r.total);
    }
  }
  return labels.map((l) => ({ month: l, ...map.get(l)! }));
}

export interface UpcomingRecurring {
  id: number;
  name: string;
  amount: number;
  direction: "in" | "out";
  currency: string;
  frequency: string;
  next_due_date: string;
  source_id: number | null;
}

export async function upcomingRecurring(
  db: SqlExecutor,
  today: string,
  limit = 5,
): Promise<UpcomingRecurring[]> {
  return db.select<UpcomingRecurring>(
    `SELECT id,name,amount,direction,currency,frequency,next_due_date,source_id
     FROM recurring_items
     WHERE end_date IS NULL OR end_date >= ?
     ORDER BY next_due_date ASC LIMIT ?`,
    [today, limit],
  );
}
