/**
 * Portfolios, holdings, daily price snapshots, valuation + history.
 * Faithful port of services/portfolios.py (refactor-analysis/portfolios-prices.md §3).
 * Key invariants: PnL is null (not 0) when cost basis is 0; total_value falls back
 * to cost_basis for unpriced holdings; one snapshot per (holding,date).
 * BUG-1 fixed: per-holding values are FX-converted to the portfolio base currency
 * before summing (mixed-currency totals were meaningless before).
 * BUG-2 fixed: history window starts at the first snapshot, not range start.
 */
import type { SqlExecutor } from "../types";
import { DomainError } from "../errors";
import { round2 } from "@/domain/money";
import { addDaysISO, todayISO } from "@/lib/date";
import { getSource } from "./sources";
import { convert } from "./exchange-rates";

const now = () => new Date().toISOString();

export interface PortfolioRow {
  id: number;
  name: string;
  kind: "crypto" | "stocks" | "mixed";
  base_currency: string;
  source_id: number;
  note: string | null;
  created_at: string;
  updated_at: string;
}

export interface HoldingRow {
  id: number;
  portfolio_id: number;
  asset_class: "crypto" | "stock";
  symbol: string;
  display_name: string | null;
  quantity: number;
  avg_cost: number;
  currency: string;
  last_price: number | null;
  last_price_at: string | null;
  manual_price: number;
  note: string | null;
  created_at: string;
  updated_at: string;
}

export interface EnrichedHolding extends HoldingRow {
  cost_basis: number;
  market_value: number | null;
  unrealized_pnl: number | null;
  unrealized_pnl_pct: number | null;
}

export function enrichHolding(h: HoldingRow): EnrichedHolding {
  const cost_basis = round2(h.quantity * h.avg_cost);
  const market_value = h.last_price != null ? round2(h.quantity * h.last_price) : null;
  let unrealized_pnl: number | null = null;
  let unrealized_pnl_pct: number | null = null;
  // PnL is meaningful only when we know the cost AND have a market price.
  if (cost_basis > 0 && market_value != null) {
    unrealized_pnl = round2(market_value - cost_basis);
    unrealized_pnl_pct = round2((unrealized_pnl / cost_basis) * 100);
  }
  return { ...h, cost_basis, market_value, unrealized_pnl, unrealized_pnl_pct };
}

// ---- portfolio CRUD ----

export async function listPortfolios(db: SqlExecutor): Promise<PortfolioRow[]> {
  return db.select<PortfolioRow>(`SELECT * FROM portfolios ORDER BY name COLLATE NOCASE`);
}
export async function getPortfolio(db: SqlExecutor, id: number): Promise<PortfolioRow | null> {
  return (await db.select<PortfolioRow>(`SELECT * FROM portfolios WHERE id = ?`, [id]))[0] ?? null;
}

export interface NewPortfolio {
  name: string;
  kind?: "crypto" | "stocks" | "mixed";
  base_currency?: string;
  source_id: number;
  note?: string | null;
}

export async function createPortfolio(db: SqlExecutor, data: NewPortfolio): Promise<number> {
  if (!(await getSource(db, data.source_id))) throw new DomainError("not_found");
  const ts = now();
  const rows = await db.select<{ id: number }>(
    `INSERT INTO portfolios (name,kind,base_currency,source_id,note,created_at,updated_at)
     VALUES (?,?,?,?,?,?,?) RETURNING id`,
    [data.name, data.kind ?? "mixed", (data.base_currency ?? "EUR").trim().toUpperCase(), data.source_id, data.note ?? null, ts, ts],
  );
  return rows[0].id;
}

export async function updatePortfolio(db: SqlExecutor, id: number, patch: Partial<NewPortfolio>): Promise<void> {
  if (!(await getPortfolio(db, id))) throw new DomainError("not_found");
  if (patch.source_id != null && !(await getSource(db, patch.source_id))) throw new DomainError("not_found");
  const sets: string[] = [];
  const params: unknown[] = [];
  const set = (c: string, v: unknown) => (sets.push(`${c} = ?`), params.push(v));
  if (patch.name !== undefined) set("name", patch.name);
  if (patch.kind !== undefined) set("kind", patch.kind);
  if (patch.base_currency !== undefined) set("base_currency", patch.base_currency.trim().toUpperCase());
  if (patch.source_id !== undefined) set("source_id", patch.source_id);
  if (patch.note !== undefined) set("note", patch.note);
  set("updated_at", now());
  await db.execute(`UPDATE portfolios SET ${sets.join(", ")} WHERE id = ?`, [...params, id]);
}

export async function deletePortfolio(db: SqlExecutor, id: number): Promise<void> {
  const holdings = await db.select<{ id: number }>(`SELECT id FROM holdings WHERE portfolio_id = ?`, [id]);
  for (const h of holdings) await db.execute(`DELETE FROM holding_price_snapshots WHERE holding_id = ?`, [h.id]);
  await db.execute(`DELETE FROM holdings WHERE portfolio_id = ?`, [id]);
  await db.execute(`DELETE FROM portfolios WHERE id = ?`, [id]);
}

// ---- snapshots ----

export async function upsertSnapshot(db: SqlExecutor, holding: HoldingRow, date = todayISO()): Promise<void> {
  if (holding.last_price == null) return;
  const existing = await db.select<{ id: number; price: number }>(
    `SELECT id, price FROM holding_price_snapshots WHERE holding_id = ? AND date = ?`,
    [holding.id, date],
  );
  if (existing[0]) {
    if (existing[0].price !== holding.last_price) {
      await db.execute(`UPDATE holding_price_snapshots SET price = ? WHERE id = ?`, [holding.last_price, existing[0].id]);
    }
    return;
  }
  await db.execute(
    `INSERT INTO holding_price_snapshots (holding_id,date,price,created_at) VALUES (?,?,?,?)`,
    [holding.id, date, holding.last_price, now()],
  );
}

// ---- holding CRUD ----

export async function getHolding(db: SqlExecutor, id: number): Promise<HoldingRow | null> {
  return (await db.select<HoldingRow>(`SELECT * FROM holdings WHERE id = ?`, [id]))[0] ?? null;
}

export interface NewHolding {
  portfolio_id: number;
  asset_class: "crypto" | "stock";
  symbol: string;
  display_name?: string | null;
  quantity?: number;
  avg_cost?: number;
  currency?: string;
  last_price?: number | null;
  manual_price?: boolean;
  note?: string | null;
}

export async function createHolding(db: SqlExecutor, data: NewHolding): Promise<number> {
  const symbol = data.symbol.trim().toUpperCase();
  if (!symbol || symbol.length > 32) throw new DomainError("invalid_amount"); // reuse: bad input
  if (!(await getPortfolio(db, data.portfolio_id))) throw new DomainError("not_found");
  const ts = now();
  const manual = data.manual_price ? 1 : 0;
  const lastPrice = data.last_price ?? null;
  const rows = await db.select<{ id: number }>(
    `INSERT INTO holdings (portfolio_id,asset_class,symbol,display_name,quantity,avg_cost,currency,last_price,last_price_at,manual_price,note,created_at,updated_at)
     VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id`,
    [data.portfolio_id, data.asset_class, symbol, data.display_name ?? null, data.quantity ?? 0, data.avg_cost ?? 0, (data.currency ?? "EUR").trim().toUpperCase(), lastPrice, lastPrice != null ? ts : null, manual, data.note ?? null, ts, ts],
  );
  const id = rows[0].id;
  if (manual && lastPrice != null) {
    await upsertSnapshot(db, (await getHolding(db, id))!);
  }
  return id;
}

export interface HoldingPatch {
  symbol?: string;
  display_name?: string | null;
  quantity?: number;
  avg_cost?: number;
  currency?: string;
  last_price?: number | null;
  manual_price?: boolean;
  note?: string | null;
}

export async function updateHolding(db: SqlExecutor, id: number, patch: HoldingPatch): Promise<void> {
  const h = await getHolding(db, id);
  if (!h) throw new DomainError("not_found");
  const sets: string[] = [];
  const params: unknown[] = [];
  const set = (c: string, v: unknown) => (sets.push(`${c} = ?`), params.push(v));
  if (patch.symbol !== undefined) set("symbol", patch.symbol.trim().toUpperCase());
  if (patch.display_name !== undefined) set("display_name", patch.display_name);
  if (patch.quantity !== undefined) set("quantity", patch.quantity);
  if (patch.avg_cost !== undefined) set("avg_cost", patch.avg_cost);
  if (patch.currency !== undefined) set("currency", patch.currency.trim().toUpperCase());
  if (patch.note !== undefined) set("note", patch.note);

  const turningManualOff = patch.manual_price === false && h.manual_price === 1;
  if (patch.manual_price !== undefined) set("manual_price", patch.manual_price ? 1 : 0);
  if (turningManualOff) {
    // clear the manual price so the next auto-refresh takes over
    set("last_price", null);
    set("last_price_at", null);
  } else if (patch.last_price !== undefined) {
    set("last_price", patch.last_price);
    set("last_price_at", patch.last_price != null ? now() : null);
  }
  set("updated_at", now());
  await db.execute(`UPDATE holdings SET ${sets.join(", ")} WHERE id = ?`, [...params, id]);

  // snapshot only when manual + a price is set + last_price was in the payload
  const after = (await getHolding(db, id))!;
  if (after.manual_price === 1 && after.last_price != null && patch.last_price !== undefined) {
    await upsertSnapshot(db, after);
  }
}

export async function deleteHolding(db: SqlExecutor, id: number): Promise<void> {
  await db.execute(`DELETE FROM holding_price_snapshots WHERE holding_id = ?`, [id]);
  await db.execute(`DELETE FROM holdings WHERE id = ?`, [id]);
}

// ---- valuation (FX-correct) ----

async function convOr(db: SqlExecutor, amount: number, from: string, to: string): Promise<number> {
  if (from.toUpperCase() === to.toUpperCase()) return amount;
  const c = await convert(db, amount, from, to);
  return c ?? amount; // best-effort: if no rate, contribute the native figure
}

export interface PortfolioSummary {
  portfolio: PortfolioRow;
  source_name: string | null;
  holdings: EnrichedHolding[];
  holdings_count: number;
  total_cost: number;
  total_value: number;
  total_pnl: number | null;
  total_pnl_pct: number | null;
  /** True when a holding currency couldn't be converted to base (rate missing). */
  has_unconverted: boolean;
}

export async function summarizePortfolio(db: SqlExecutor, id: number): Promise<PortfolioSummary> {
  const p = await getPortfolio(db, id);
  if (!p) throw new DomainError("not_found");
  const holdingRows = await db.select<HoldingRow>(
    `SELECT * FROM holdings WHERE portfolio_id = ? ORDER BY asset_class, symbol COLLATE NOCASE`,
    [id],
  );
  const base = p.base_currency;
  const src = await getSource(db, p.source_id);

  let totalCost = 0;
  let totalValue = 0;
  let totalPnl = 0;
  let pnlSeen = false;
  let hasUnconverted = false;
  const holdings: EnrichedHolding[] = [];

  for (const row of holdingRows) {
    const h = enrichHolding(row);
    holdings.push(h);
    if (h.currency.toUpperCase() !== base.toUpperCase()) {
      const rate = await convert(db, 1, h.currency, base);
      if (rate == null) hasUnconverted = true;
    }
    totalCost = round2(totalCost + (await convOr(db, h.cost_basis, h.currency, base)));
    const valNative = h.market_value ?? h.cost_basis;
    totalValue = round2(totalValue + (await convOr(db, valNative, h.currency, base)));
    if (h.unrealized_pnl != null) {
      totalPnl = round2(totalPnl + (await convOr(db, h.unrealized_pnl, h.currency, base)));
      pnlSeen = true;
    }
  }

  const total_pnl = totalCost > 0 && pnlSeen ? totalPnl : null;
  const total_pnl_pct = total_pnl != null && totalCost > 0 ? round2((total_pnl / totalCost) * 100) : null;

  return {
    portfolio: p,
    source_name: src?.name ?? null,
    holdings,
    holdings_count: holdings.length,
    total_cost: totalCost,
    total_value: totalValue,
    total_pnl,
    total_pnl_pct,
    has_unconverted: hasUnconverted,
  };
}

/** Net portfolio market value per base currency (for dashboard net worth). */
export async function totalValueByCurrency(db: SqlExecutor): Promise<Record<string, number>> {
  const portfolios = await listPortfolios(db);
  const out: Record<string, number> = {};
  for (const p of portfolios) {
    const s = await summarizePortfolio(db, p.id);
    if (s.total_value) out[p.base_currency] = round2((out[p.base_currency] ?? 0) + s.total_value);
  }
  return out;
}

// ---- history (consolidated walk; BUG-2 window fixed) ----

export interface ValuePoint {
  date: string;
  value: number;
}

export async function portfolioValueHistory(db: SqlExecutor, id: number, rangeDays = 30): Promise<ValuePoint[]> {
  const holdingRows = await db.select<HoldingRow>(`SELECT * FROM holdings WHERE portfolio_id = ?`, [id]);
  const p = await getPortfolio(db, id);
  if (!p || holdingRows.length === 0) return [];
  const base = p.base_currency;
  const today = todayISO();
  const rangeStart = addDaysISO(today, -rangeDays);

  // snapshots per holding, sorted ascending
  const snaps = new Map<number, { date: string; price: number }[]>();
  let firstSnapshot = today;
  for (const h of holdingRows) {
    const rows = await db.select<{ date: string; price: number }>(
      `SELECT date, price FROM holding_price_snapshots WHERE holding_id = ? ORDER BY date ASC`,
      [h.id],
    );
    snaps.set(h.id, rows);
    if (rows[0] && rows[0].date < firstSnapshot) firstSnapshot = rows[0].date;
  }
  // BUG-2 fix: window starts at the first real snapshot, not the full range start.
  const windowStart = rangeStart > firstSnapshot ? rangeStart : firstSnapshot;

  const points: ValuePoint[] = [];
  for (let d = windowStart; d <= today; d = addDaysISO(d, 1)) {
    let value = 0;
    for (const h of holdingRows) {
      const series = snaps.get(h.id)!;
      let price = h.avg_cost; // fallback
      for (const s of series) {
        if (s.date <= d) price = s.price;
        else break;
      }
      value = round2(value + (await convOr(db, round2(h.quantity * price), h.currency, base)));
    }
    points.push({ date: d, value });
  }
  return points;
}

// ---- prices (opt-in; network providers are a later enhancement) ----

export async function arePricesEnabled(db: SqlExecutor): Promise<boolean> {
  const r = await db.select<{ portfolio_prices_enabled: number }>(`SELECT portfolio_prices_enabled FROM settings WHERE id = 1`);
  return (r[0]?.portfolio_prices_enabled ?? 0) === 1;
}

/** No-op when disabled. Live providers (CoinGecko/yfinance) land in a later phase. */
export async function refreshAllHoldings(db: SqlExecutor): Promise<{ updated: number; enabled: boolean }> {
  const enabled = await arePricesEnabled(db);
  return { updated: 0, enabled };
}
