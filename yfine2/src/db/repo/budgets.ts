/**
 * Budgets: tag-based, single-currency, live-computed actuals + signed rollover
 * (refactor-analysis/budgets-goals-whims.md §A). Bug B-1 fixed: a budget with a
 * negative carried rollover (available <= 0) still reports "over" / fires the
 * overspend alert when there is real spending.
 */
import type { SqlExecutor } from "../types";
import { DomainError } from "../errors";
import { round2 } from "@/domain/money";
import { periodBounds, periodKey, shiftPeriod, type Period } from "@/domain/period";
import { daysBetween, todayISO } from "@/lib/date";
import { createNotification } from "./notifications";

const now = () => new Date().toISOString();
const MAX_ROLLOVER_PERIODS = 600;

export interface BudgetRow {
  id: number;
  tag_id: number;
  amount: number;
  currency: string;
  period: Period;
  direction: "in" | "out";
  rollover: number;
  alert_threshold_pct: number;
  active: number;
  start_date: string;
  last_alert_period: string | null;
  last_alert_level: number;
  created_at: string;
  updated_at: string;
}

async function actualFor(
  db: SqlExecutor,
  b: Pick<BudgetRow, "tag_id" | "direction" | "currency">,
  start: string,
  end: string,
): Promise<number> {
  const r = await db.select<{ total: number }>(
    `SELECT COALESCE(SUM(m.amount),0) AS total
     FROM movements m
     JOIN movement_tag mt ON mt.movement_id = m.id
     JOIN sources s ON m.source_id = s.id
     WHERE mt.tag_id = ? AND m.direction = ? AND m.date >= ? AND m.date <= ?
       AND m.transfer_pair_id IS NULL AND m.exclude_from_stats = 0 AND s.currency = ?`,
    [b.tag_id, b.direction, start, end, b.currency],
  );
  return round2(r[0]?.total ?? 0);
}

/** Signed rollover carried into the period containing `ref` (§A4). */
async function rolloverInto(db: SqlExecutor, b: BudgetRow, ref: string): Promise<number> {
  if (!b.rollover) return 0;
  const currentStart = periodBounds(b.period, ref)[0];
  let walkRef = periodBounds(b.period, b.start_date)[0];
  let ro = 0;
  let guard = 0;
  while (walkRef < currentStart && guard < MAX_ROLLOVER_PERIODS) {
    guard += 1;
    const [s, e] = periodBounds(b.period, walkRef);
    const actual = await actualFor(db, b, s, e);
    ro = round2(b.amount + ro - actual);
    walkRef = periodBounds(b.period, shiftPeriod(b.period, walkRef, 1))[0];
  }
  return ro;
}

export interface BudgetStatus {
  budget: BudgetRow;
  periodStart: string;
  periodEnd: string;
  periodKey: string;
  actual: number;
  rolloverIn: number;
  available: number;
  remaining: number;
  spentPct: number;
  status: "ok" | "warning" | "over";
  projected: number;
  daysRemaining: number;
}

export async function budgetStatus(db: SqlExecutor, b: BudgetRow, ref = todayISO()): Promise<BudgetStatus> {
  const [periodStart, periodEnd] = periodBounds(b.period, ref);
  const actual = await actualFor(db, b, periodStart, periodEnd);
  const rolloverIn = await rolloverInto(db, b, ref);
  const available = round2(b.amount + rolloverIn);
  const remaining = round2(available - actual);
  const spentPct = available > 0 ? round1((actual / available) * 100) : actual > 0 ? 100 : 0;

  // B-1 fix: "over" whenever real spending exceeds available, including available <= 0.
  const isOver = actual > 0 && actual > available;
  const status: BudgetStatus["status"] = isOver
    ? "over"
    : b.alert_threshold_pct > 0 && spentPct >= b.alert_threshold_pct
      ? "warning"
      : "ok";

  const totalDays = daysBetween(periodStart, periodEnd) + 1;
  const elapsed = Math.min(Math.max(daysBetween(periodStart, ref) + 1, 0), totalDays);
  const projected = elapsed > 0 ? round2((actual / elapsed) * totalDays) : 0;
  const daysRemaining = Math.max(0, totalDays - elapsed);

  return { budget: b, periodStart, periodEnd, periodKey: periodKey(b.period, ref), actual, rolloverIn, available, remaining, spentPct, status, projected, daysRemaining };
}

function round1(n: number): number {
  return Math.round(n * 10) / 10;
}

async function ensureTag(db: SqlExecutor, tagId: number): Promise<void> {
  const r = await db.select<{ c: number }>(`SELECT COUNT(*) c FROM tags WHERE id = ?`, [tagId]);
  if ((r[0]?.c ?? 0) === 0) throw new DomainError("unknown_tag");
}

async function rejectDuplicate(db: SqlExecutor, tagId: number, currency: string, excludeId?: number): Promise<void> {
  const rows = await db.select<{ id: number }>(
    `SELECT id FROM budgets WHERE tag_id = ? AND currency = ? AND active = 1${excludeId ? " AND id != ?" : ""}`,
    excludeId ? [tagId, currency, excludeId] : [tagId, currency],
  );
  if (rows.length) throw new DomainError("duplicate_budget");
}

export interface NewBudget {
  tag_id: number;
  amount: number;
  currency: string;
  period?: Period;
  direction?: "in" | "out";
  rollover?: boolean;
  alert_threshold_pct?: number;
  active?: boolean;
  start_date?: string;
}

export async function createBudget(db: SqlExecutor, data: NewBudget): Promise<number> {
  if (!(data.amount > 0)) throw new DomainError("invalid_amount");
  await ensureTag(db, data.tag_id);
  const currency = data.currency.trim().toUpperCase();
  const period = data.period ?? "monthly";
  const active = data.active === false ? 0 : 1;
  if (active) await rejectDuplicate(db, data.tag_id, currency);
  const startDate = data.start_date ?? periodBounds(period, todayISO())[0];
  const ts = now();
  const rows = await db.select<{ id: number }>(
    `INSERT INTO budgets (tag_id,amount,currency,period,direction,rollover,alert_threshold_pct,active,start_date,last_alert_period,last_alert_level,created_at,updated_at)
     VALUES (?,?,?,?,?,?,?,?,?,NULL,0,?,?) RETURNING id`,
    [data.tag_id, data.amount, currency, period, data.direction ?? "out", data.rollover ? 1 : 0, data.alert_threshold_pct ?? 80, active, startDate, ts, ts],
  );
  return rows[0].id;
}

export async function getBudget(db: SqlExecutor, id: number): Promise<BudgetRow | null> {
  const r = await db.select<BudgetRow>(`SELECT * FROM budgets WHERE id = ?`, [id]);
  return r[0] ?? null;
}

export type BudgetPatch = Partial<NewBudget>;

export async function updateBudget(db: SqlExecutor, id: number, patch: BudgetPatch): Promise<void> {
  const cur = await getBudget(db, id);
  if (!cur) throw new DomainError("not_found");
  if (patch.tag_id !== undefined) await ensureTag(db, patch.tag_id);
  if (patch.amount !== undefined && !(patch.amount > 0)) throw new DomainError("invalid_amount");

  const nextTag = patch.tag_id ?? cur.tag_id;
  const nextCcy = (patch.currency ?? cur.currency).trim().toUpperCase();
  const nextActive = patch.active !== undefined ? (patch.active ? 1 : 0) : cur.active;
  if (nextActive) await rejectDuplicate(db, nextTag, nextCcy, id);

  // §A9: reset alert bands when the shape changes
  const shapeChanged =
    (patch.amount !== undefined && patch.amount !== cur.amount) ||
    (patch.period !== undefined && patch.period !== cur.period) ||
    (patch.tag_id !== undefined && patch.tag_id !== cur.tag_id) ||
    (patch.currency !== undefined && nextCcy !== cur.currency) ||
    (patch.rollover !== undefined && (patch.rollover ? 1 : 0) !== cur.rollover) ||
    (patch.active !== undefined && nextActive !== cur.active);

  const sets: string[] = [];
  const params: unknown[] = [];
  const set = (c: string, v: unknown) => (sets.push(`${c} = ?`), params.push(v));
  if (patch.tag_id !== undefined) set("tag_id", patch.tag_id);
  if (patch.amount !== undefined) set("amount", patch.amount);
  if (patch.currency !== undefined) set("currency", nextCcy);
  if (patch.period !== undefined) set("period", patch.period);
  if (patch.direction !== undefined) set("direction", patch.direction);
  if (patch.rollover !== undefined) set("rollover", patch.rollover ? 1 : 0);
  if (patch.alert_threshold_pct !== undefined) set("alert_threshold_pct", patch.alert_threshold_pct);
  if (patch.active !== undefined) set("active", nextActive);
  if (patch.start_date !== undefined) set("start_date", patch.start_date);
  if (shapeChanged) {
    set("last_alert_period", null);
    set("last_alert_level", 0);
  }
  set("updated_at", now());
  await db.execute(`UPDATE budgets SET ${sets.join(", ")} WHERE id = ?`, [...params, id]);
}

export async function deleteBudget(db: SqlExecutor, id: number): Promise<void> {
  await db.execute(`DELETE FROM budgets WHERE id = ?`, [id]);
}

/** Called when a tag is deleted (§A11). */
export async function deleteBudgetsForTag(db: SqlExecutor, tagId: number): Promise<void> {
  await db.execute(`DELETE FROM budgets WHERE tag_id = ?`, [tagId]);
}

export async function listBudgetStatuses(db: SqlExecutor, offset = 0, today = todayISO()): Promise<BudgetStatus[]> {
  const budgets = await db.select<BudgetRow>(`SELECT * FROM budgets ORDER BY id`);
  const out: BudgetStatus[] = [];
  for (const b of budgets) {
    const ref = offset === 0 ? today : shiftPeriod(b.period, today, offset);
    out.push(await budgetStatus(db, b, ref));
  }
  const rank = { over: 0, warning: 1, ok: 2 };
  return out.sort((a, b) => rank[a.status] - rank[b.status] || b.spentPct - a.spentPct);
}

/** Idempotent threshold/overspend alerts (§A12, B-1 fixed). Returns count fired. */
export async function checkBudgetAlerts(db: SqlExecutor, today = todayISO()): Promise<number> {
  const budgets = await db.select<BudgetRow>(`SELECT * FROM budgets WHERE active = 1 AND alert_threshold_pct > 0`);
  let fired = 0;
  for (const b of budgets) {
    const [ps, pe] = periodBounds(b.period, today);
    if (today < ps || today > pe) continue;
    const st = await budgetStatus(db, b, today);
    const level = st.actual > 0 && st.actual > st.available ? 100 : st.spentPct >= b.alert_threshold_pct ? b.alert_threshold_pct : 0;
    const lastLevel = b.last_alert_period === st.periodKey ? b.last_alert_level : 0;
    if (level > lastLevel) {
      await createNotification(db, {
        type: level === 100 ? "warning" : "alert",
        title: level === 100 ? `Budget exceeded` : `Budget at ${level}%`,
        body: `${st.actual} / ${st.available} ${b.currency}`,
        related_entity: `budget:${b.id}`,
      });
      await db.execute(`UPDATE budgets SET last_alert_period = ?, last_alert_level = ?, updated_at = ? WHERE id = ?`, [st.periodKey, level, now(), b.id]);
      fired += 1;
    }
  }
  return fired;
}
