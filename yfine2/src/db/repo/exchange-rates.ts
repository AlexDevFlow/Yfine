/**
 * Exchange rates: one row per directed pair (unique). Provides the FX-conversion
 * seam the portfolio totals need (fixes the mixed-currency BUG-1). Rate semantics:
 * 1 `from` = rate × `to`.
 */
import type { SqlExecutor } from "../types";
import { round2 } from "@/domain/money";

const now = () => new Date().toISOString();

export interface ExchangeRateRow {
  id: number;
  from_currency: string;
  to_currency: string;
  rate: number;
  updated_at: string;
}

export async function listRates(db: SqlExecutor): Promise<ExchangeRateRow[]> {
  return db.select<ExchangeRateRow>(`SELECT * FROM exchange_rates ORDER BY from_currency, to_currency`);
}

/** Rate to convert `from` → `to`, or null if unknown. Tries the inverse pair. */
export async function getRate(db: SqlExecutor, from: string, to: string): Promise<number | null> {
  const f = from.trim().toUpperCase();
  const t = to.trim().toUpperCase();
  if (f === t) return 1;
  const direct = await db.select<{ rate: number }>(
    `SELECT rate FROM exchange_rates WHERE from_currency = ? AND to_currency = ?`,
    [f, t],
  );
  if (direct[0]) return direct[0].rate;
  const inverse = await db.select<{ rate: number }>(
    `SELECT rate FROM exchange_rates WHERE from_currency = ? AND to_currency = ?`,
    [t, f],
  );
  if (inverse[0] && inverse[0].rate !== 0) return 1 / inverse[0].rate;
  return null;
}

/** Convert an amount, or null when no rate is available. */
export async function convert(db: SqlExecutor, amount: number, from: string, to: string): Promise<number | null> {
  const rate = await getRate(db, from, to);
  return rate == null ? null : round2(amount * rate);
}

export async function upsertRate(db: SqlExecutor, from: string, to: string, rate: number): Promise<void> {
  const f = from.trim().toUpperCase();
  const t = to.trim().toUpperCase();
  const existing = await db.select<{ id: number }>(
    `SELECT id FROM exchange_rates WHERE from_currency = ? AND to_currency = ?`,
    [f, t],
  );
  if (existing[0]) {
    await db.execute(`UPDATE exchange_rates SET rate = ?, updated_at = ? WHERE id = ?`, [rate, now(), existing[0].id]);
  } else {
    await db.execute(
      `INSERT INTO exchange_rates (from_currency,to_currency,rate,updated_at) VALUES (?,?,?,?)`,
      [f, t, rate, now()],
    );
  }
}
