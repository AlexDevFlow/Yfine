/**
 * Sources repository. Faithful port of services/sources.py invariants
 * (refactor-analysis/sources-savings.md §A, §C, §D, §E):
 *  - balance is DERIVED (starting + Σin − Σout), never stored.
 *  - currency uppercased at the boundary.
 *  - yield schedule resynced on create, and on update ONLY when rate/period change.
 *  - exactly one savings fund per currency; funds never merge.
 *  - delete is blocked by an active goal; move/external/delete_all reject
 *    cross-currency and cascade manually (FK is also ON as a backstop).
 */
import type { SqlExecutor } from "../types";
import type { SourceRow } from "../schema-types";
import { DomainError } from "../errors";
import { round2 } from "@/domain/money";
import { resyncYieldSchedule } from "@/domain/yield";
import { todayISO } from "@/lib/date";

const COLS =
  "id,name,currency,starting_balance,exclude_from_stats,is_savings_fund,hidden_from_sources,yield_rate,yield_period_months,yield_next_date,yield_last_date,created_at,updated_at";

const now = () => new Date().toISOString();

export async function listSources(
  db: SqlExecutor,
  opts: { includeHidden?: boolean } = {},
): Promise<SourceRow[]> {
  const where = opts.includeHidden === false ? "WHERE hidden_from_sources = 0" : "";
  return db.select<SourceRow>(
    `SELECT ${COLS} FROM sources ${where} ORDER BY is_savings_fund ASC, name COLLATE NOCASE ASC`,
  );
}

export async function getSource(
  db: SqlExecutor,
  id: number,
): Promise<SourceRow | null> {
  const rows = await db.select<SourceRow>(`SELECT ${COLS} FROM sources WHERE id = ?`, [id]);
  return rows[0] ?? null;
}

const BALANCE_EXPR = `s.starting_balance + COALESCE((
    SELECT SUM(CASE m.direction WHEN 'in' THEN m.amount ELSE -m.amount END)
    FROM movements m WHERE m.source_id = s.id), 0)`;

export async function getBalance(db: SqlExecutor, id: number): Promise<number> {
  const rows = await db.select<{ bal: number }>(
    `SELECT ${BALANCE_EXPR} AS bal FROM sources s WHERE s.id = ?`,
    [id],
  );
  if (!rows[0]) throw new DomainError("not_found");
  return round2(rows[0].bal);
}

export async function getBalancesBatch(
  db: SqlExecutor,
): Promise<Map<number, number>> {
  const rows = await db.select<{ id: number; bal: number }>(
    `SELECT s.id AS id, ${BALANCE_EXPR} AS bal FROM sources s`,
  );
  const map = new Map<number, number>();
  for (const r of rows) map.set(r.id, round2(r.bal));
  return map;
}

export interface NewSource {
  name: string;
  currency: string;
  starting_balance?: number;
  exclude_from_stats?: boolean;
  yield_rate?: number;
  yield_period_months?: number;
}

export async function createSource(
  db: SqlExecutor,
  data: NewSource,
  today: string = todayISO(),
): Promise<SourceRow> {
  const currency = data.currency.trim().toUpperCase();
  const rate = data.yield_rate ?? 0;
  const period = data.yield_period_months ?? 12;
  const nextDate = resyncYieldSchedule(rate, period, null, today);
  const ts = now();
  const rows = await db.select<{ id: number }>(
    `INSERT INTO sources
      (name,currency,starting_balance,exclude_from_stats,is_savings_fund,hidden_from_sources,yield_rate,yield_period_months,yield_next_date,yield_last_date,created_at,updated_at)
     VALUES (?,?,?,?,0,0,?,?,?,NULL,?,?) RETURNING id`,
    [data.name, currency, data.starting_balance ?? 0, data.exclude_from_stats ? 1 : 0, rate, period, nextDate, ts, ts],
  );
  return (await getSource(db, rows[0].id))!;
}

export interface SourcePatch {
  name?: string;
  currency?: string;
  starting_balance?: number;
  exclude_from_stats?: boolean;
  yield_rate?: number;
  yield_period_months?: number;
}

export async function updateSource(
  db: SqlExecutor,
  id: number,
  patch: SourcePatch,
  today: string = todayISO(),
): Promise<SourceRow> {
  const cur = await getSource(db, id);
  if (!cur) throw new DomainError("not_found");

  const sets: string[] = [];
  const params: unknown[] = [];
  const set = (col: string, val: unknown) => {
    sets.push(`${col} = ?`);
    params.push(val);
  };

  if (patch.name !== undefined) set("name", patch.name);
  if (patch.currency !== undefined) set("currency", patch.currency.trim().toUpperCase());
  if (patch.starting_balance !== undefined) set("starting_balance", patch.starting_balance);
  if (patch.exclude_from_stats !== undefined)
    set("exclude_from_stats", patch.exclude_from_stats ? 1 : 0);
  if (patch.yield_rate !== undefined) set("yield_rate", patch.yield_rate);
  if (patch.yield_period_months !== undefined)
    set("yield_period_months", patch.yield_period_months);

  // §17: re-anchor the countdown ONLY when rate/period are in the payload.
  if (patch.yield_rate !== undefined || patch.yield_period_months !== undefined) {
    const rate = patch.yield_rate ?? cur.yield_rate;
    const period = patch.yield_period_months ?? cur.yield_period_months;
    set("yield_next_date", resyncYieldSchedule(rate, period, cur.yield_last_date, today));
  }

  set("updated_at", now());
  await db.execute(`UPDATE sources SET ${sets.join(", ")} WHERE id = ?`, [...params, id]);
  return (await getSource(db, id))!;
}

/** Find-or-create the single savings fund for a currency (§C-11). */
export async function ensureFundForCurrency(
  db: SqlExecutor,
  currency: string,
  fundLabel = "Savings Fund",
): Promise<SourceRow> {
  const cc = currency.trim().toUpperCase();
  const existing = await db.select<SourceRow>(
    `SELECT ${COLS} FROM sources WHERE is_savings_fund = 1 AND currency = ? LIMIT 1`,
    [cc],
  );
  if (existing[0]) return existing[0];
  const ts = now();
  const rows = await db.select<{ id: number }>(
    `INSERT INTO sources
      (name,currency,starting_balance,exclude_from_stats,is_savings_fund,hidden_from_sources,yield_rate,yield_period_months,yield_next_date,yield_last_date,created_at,updated_at)
     VALUES (?,?,0,0,1,0,0,12,NULL,NULL,?,?) RETURNING id`,
    [`${fundLabel} (${cc})`, cc, ts, ts],
  );
  return (await getSource(db, rows[0].id))!;
}

export async function setFundVisibility(
  db: SqlExecutor,
  id: number,
  hidden: boolean,
): Promise<void> {
  const s = await getSource(db, id);
  if (!s || s.is_savings_fund === 0) throw new DomainError("not_a_fund");
  await db.execute(`UPDATE sources SET hidden_from_sources = ?, updated_at = ? WHERE id = ?`, [
    hidden ? 1 : 0,
    now(),
    id,
  ]);
}

export async function mergeSources(
  db: SqlExecutor,
  fromId: number,
  toId: number,
): Promise<void> {
  const from = await getSource(db, fromId);
  const to = await getSource(db, toId);
  if (!from || !to) throw new DomainError("not_found");
  if (from.is_savings_fund || to.is_savings_fund) throw new DomainError("fund_not_mergeable");
  if (from.currency !== to.currency) throw new DomainError("cross_currency");

  await db.execute(`UPDATE movements SET source_id = ? WHERE source_id = ?`, [toId, fromId]);
  await db.execute(`UPDATE recurring_items SET source_id = ? WHERE source_id = ?`, [toId, fromId]);
  await db.execute(`UPDATE portfolios SET source_id = ? WHERE source_id = ?`, [toId, fromId]);
  await db.execute(`UPDATE sources SET starting_balance = ?, updated_at = ? WHERE id = ?`, [
    round2(to.starting_balance + from.starting_balance),
    now(),
    toId,
  ]);
  await db.execute(
    `INSERT INTO notifications (type,title,body,related_entity,is_read,created_at) VALUES ('info',?,?,?,0,?)`,
    ["Sources merged", `${from.name} merged into ${to.name}`, `source:${toId}`, now()],
  );
  await db.execute(`DELETE FROM sources WHERE id = ?`, [fromId]);
}

export type DeleteAction =
  | { kind: "delete_all" }
  | { kind: "move_to"; targetId: number }
  | { kind: "make_external" };

export async function deleteSource(
  db: SqlExecutor,
  id: number,
  action: DeleteAction,
): Promise<void> {
  const s = await getSource(db, id);
  if (!s) throw new DomainError("not_found");

  const activeGoals = await db.select<{ c: number }>(
    `SELECT COUNT(*) AS c FROM goals WHERE source_id = ? AND status = 'active'`,
    [id],
  );
  if ((activeGoals[0]?.c ?? 0) > 0) throw new DomainError("active_goal_blocks_delete");

  if (action.kind === "move_to") {
    const target = await getSource(db, action.targetId);
    if (!target) throw new DomainError("not_found");
    if (target.currency !== s.currency) throw new DomainError("cross_currency");
    await db.execute(`UPDATE movements SET source_id = ? WHERE source_id = ?`, [action.targetId, id]);
    await db.execute(`UPDATE recurring_items SET source_id = ? WHERE source_id = ?`, [action.targetId, id]);
    await db.execute(`UPDATE portfolios SET source_id = ? WHERE source_id = ?`, [action.targetId, id]);
    await db.execute(`UPDATE sources SET starting_balance = ?, updated_at = ? WHERE id = ?`, [
      round2(target.starting_balance + s.starting_balance),
      now(),
      action.targetId,
    ]);
    await db.execute(`DELETE FROM sources WHERE id = ?`, [id]);
    return;
  }

  if (action.kind === "make_external") {
    const ports = await db.select<{ c: number }>(
      `SELECT COUNT(*) AS c FROM portfolios WHERE source_id = ?`,
      [id],
    );
    if ((ports[0]?.c ?? 0) > 0) throw new DomainError("has_portfolios");
    await db.execute(`UPDATE movements SET source_id = NULL WHERE source_id = ?`, [id]);
    await db.execute(`DELETE FROM recurring_items WHERE source_id = ?`, [id]);
    await db.execute(`DELETE FROM sources WHERE id = ?`, [id]);
    return;
  }

  // delete_all — purge this source's movements AND their transfer partners.
  const movs = await db.select<{ id: number; transfer_pair_id: number | null }>(
    `SELECT id, transfer_pair_id FROM movements WHERE source_id = ?`,
    [id],
  );
  const ids = new Set<number>();
  for (const m of movs) {
    ids.add(m.id);
    if (m.transfer_pair_id != null) ids.add(m.transfer_pair_id);
  }
  if (ids.size) {
    const list = [...ids];
    const ph = list.map(() => "?").join(",");
    await db.execute(`DELETE FROM goal_allocations WHERE movement_id IN (${ph})`, list);
    await db.execute(`DELETE FROM movement_tag WHERE movement_id IN (${ph})`, list);
    await db.execute(`DELETE FROM movement_attachments WHERE movement_id IN (${ph})`, list);
    await db.execute(`DELETE FROM movements WHERE id IN (${ph})`, list);
  }

  const ports = await db.select<{ id: number }>(`SELECT id FROM portfolios WHERE source_id = ?`, [id]);
  for (const p of ports) {
    const holds = await db.select<{ id: number }>(`SELECT id FROM holdings WHERE portfolio_id = ?`, [p.id]);
    for (const h of holds) {
      await db.execute(`DELETE FROM holding_price_snapshots WHERE holding_id = ?`, [h.id]);
    }
    await db.execute(`DELETE FROM holdings WHERE portfolio_id = ?`, [p.id]);
  }
  await db.execute(`DELETE FROM portfolios WHERE source_id = ?`, [id]);
  await db.execute(`DELETE FROM recurring_items WHERE source_id = ?`, [id]);
  await db.execute(`DELETE FROM sources WHERE id = ?`, [id]);
}
