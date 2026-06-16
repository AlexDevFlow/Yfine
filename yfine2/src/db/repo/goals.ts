/**
 * Goals: accumulate money inside a Source via real two-leg transfers
 * (refactor-analysis/budgets-goals-whims.md §B). close = consolidated refund
 * (KEEPS deposit movements — double-payout guard); delete = auto-reverse every
 * allocation. Bug B-3 fixed: status can't be flipped to completed/cancelled via
 * a plain update (use close/delete so money is refunded/reversed).
 */
import type { SqlExecutor } from "../types";
import { DomainError } from "../errors";
import { round2 } from "@/domain/money";
import { todayISO } from "@/lib/date";
import { ensureFundForCurrency, getSource } from "./sources";
import { createTransferPair, deleteMovementCascade } from "./transfers";

const now = () => new Date().toISOString();

export interface GoalRow {
  id: number;
  name: string;
  target_amount: number;
  currency: string;
  target_date: string | null;
  source_id: number;
  status: "active" | "completed" | "cancelled";
  note: string | null;
  linked_whim_id: number | null;
  created_at: string;
  updated_at: string;
}

export async function getGoal(db: SqlExecutor, id: number): Promise<GoalRow | null> {
  const r = await db.select<GoalRow>(`SELECT * FROM goals WHERE id = ?`, [id]);
  return r[0] ?? null;
}

async function allocatedSum(db: SqlExecutor, goalId: number): Promise<number> {
  const r = await db.select<{ total: number }>(`SELECT COALESCE(SUM(amount),0) total FROM goal_allocations WHERE goal_id = ?`, [goalId]);
  return round2(r[0]?.total ?? 0);
}

export interface NewGoal {
  name: string;
  target_amount: number;
  currency: string;
  target_date?: string | null;
  source_id?: number | null;
  note?: string | null;
  linked_whim_id?: number | null;
  fundLabel?: string;
}

export async function createGoal(db: SqlExecutor, data: NewGoal): Promise<number> {
  if (!(data.target_amount > 0)) throw new DomainError("invalid_amount");
  const currency = data.currency.trim().toUpperCase();

  let sourceId = data.source_id ?? null;
  if (sourceId == null) {
    sourceId = (await ensureFundForCurrency(db, currency, data.fundLabel ?? "Savings Fund")).id;
  } else {
    const s = await getSource(db, sourceId);
    if (!s) throw new DomainError("not_found");
    if (s.currency.toUpperCase() !== currency) throw new DomainError("currency_mismatch");
  }

  if (data.linked_whim_id != null) {
    const w = await db.select<{ id: number; currency: string }>(`SELECT id,currency FROM whims WHERE id = ?`, [data.linked_whim_id]);
    if (!w[0]) throw new DomainError("not_found");
    if (w[0].currency.toUpperCase() !== currency) throw new DomainError("currency_mismatch");
  }

  const ts = now();
  const rows = await db.select<{ id: number }>(
    `INSERT INTO goals (name,target_amount,currency,target_date,source_id,status,note,linked_whim_id,created_at,updated_at)
     VALUES (?,?,?,?,?,'active',?,?,?,?) RETURNING id`,
    [data.name, data.target_amount, currency, data.target_date ?? null, sourceId, data.note ?? null, data.linked_whim_id ?? null, ts, ts],
  );
  const goalId = rows[0].id;
  if (data.linked_whim_id != null) {
    await db.execute(`UPDATE whims SET linked_goal_id = ?, updated_at = ? WHERE id = ?`, [goalId, ts, data.linked_whim_id]);
  }
  return goalId;
}

export interface GoalPatch {
  name?: string;
  target_amount?: number;
  target_date?: string | null;
  note?: string | null;
  status?: "active" | "completed" | "cancelled";
}

export async function updateGoal(db: SqlExecutor, id: number, patch: GoalPatch): Promise<void> {
  const g = await getGoal(db, id);
  if (!g) throw new DomainError("not_found");
  // B-3 fix: never strand money — completion/cancellation must go through close/delete.
  if (patch.status && patch.status !== "active" && patch.status !== g.status) {
    throw new DomainError("use_close_or_delete");
  }
  if (patch.target_amount !== undefined && !(patch.target_amount > 0)) throw new DomainError("invalid_amount");
  const sets: string[] = [];
  const params: unknown[] = [];
  const set = (c: string, v: unknown) => (sets.push(`${c} = ?`), params.push(v));
  if (patch.name !== undefined) set("name", patch.name);
  if (patch.target_amount !== undefined) set("target_amount", patch.target_amount);
  if (patch.target_date !== undefined) set("target_date", patch.target_date);
  if (patch.note !== undefined) set("note", patch.note);
  if (patch.status !== undefined) set("status", patch.status);
  set("updated_at", now());
  await db.execute(`UPDATE goals SET ${sets.join(", ")} WHERE id = ?`, [...params, id]);
}

export interface AllocateInput {
  fromSourceId: number;
  amount: number;
  date?: string;
  note?: string | null;
}

export async function allocate(db: SqlExecutor, goalId: number, input: AllocateInput): Promise<void> {
  const g = await getGoal(db, goalId);
  if (!g) throw new DomainError("not_found");
  if (g.status !== "active") throw new DomainError("goal_not_active");
  if (!(input.amount > 0)) throw new DomainError("invalid_amount");
  if (input.fromSourceId === g.source_id) throw new DomainError("alloc_from_own_source");
  const from = await getSource(db, input.fromSourceId);
  if (!from) throw new DomainError("not_found");
  if (from.currency.toUpperCase() !== g.currency.toUpperCase()) throw new DomainError("currency_mismatch");

  const date = input.date ?? todayISO();
  const { inId } = await createTransferPair(db, {
    fromSourceId: input.fromSourceId,
    toSourceId: g.source_id,
    amount: input.amount,
    date,
    note: g.name,
  });
  await db.execute(
    `INSERT INTO goal_allocations (goal_id,movement_id,amount,date,created_at) VALUES (?,?,?,?,?)`,
    [goalId, inId, input.amount, date, now()],
  );
}

export interface AllocationRow {
  id: number;
  amount: number;
  date: string;
  created_at: string;
  from_source_name: string | null;
}

/** Allocation history for a goal (newest first) with the funding source name. */
export async function listAllocations(db: SqlExecutor, goalId: number): Promise<AllocationRow[]> {
  return db.select<AllocationRow>(
    `SELECT ga.id, ga.amount, ga.date, ga.created_at,
       (SELECT ps.name FROM movements pm LEFT JOIN sources ps ON pm.source_id = ps.id
        WHERE pm.id = (SELECT transfer_pair_id FROM movements WHERE id = ga.movement_id)) AS from_source_name
     FROM goal_allocations ga
     WHERE ga.goal_id = ? ORDER BY ga.date DESC, ga.id DESC`,
    [goalId],
  );
}

export async function deleteAllocation(db: SqlExecutor, allocationId: number): Promise<void> {
  const r = await db.select<{ movement_id: number }>(`SELECT movement_id FROM goal_allocations WHERE id = ?`, [allocationId]);
  if (!r[0]) return;
  // Reverses the transfer (both legs) and CASCADE-drops the allocation row.
  await deleteMovementCascade(db, r[0].movement_id);
  await db.execute(`DELETE FROM goal_allocations WHERE id = ?`, [allocationId]);
}

export async function deleteGoal(db: SqlExecutor, id: number): Promise<void> {
  const g = await getGoal(db, id);
  if (!g) return;
  const allocs = await db.select<{ id: number; movement_id: number }>(`SELECT id, movement_id FROM goal_allocations WHERE goal_id = ?`, [id]);
  for (const a of allocs) {
    await deleteMovementCascade(db, a.movement_id); // money returns to origin
  }
  await db.execute(`DELETE FROM goal_allocations WHERE goal_id = ?`, [id]);
  await db.execute(`UPDATE whims SET linked_goal_id = NULL WHERE linked_goal_id = ?`, [id]);
  await db.execute(`DELETE FROM goals WHERE id = ?`, [id]);
}

export async function closeGoal(db: SqlExecutor, id: number, toSourceId: number, date?: string): Promise<void> {
  const g = await getGoal(db, id);
  if (!g) throw new DomainError("not_found");
  if (g.status === "cancelled") throw new DomainError("goal_cancelled");
  const to = await getSource(db, toSourceId);
  if (!to) throw new DomainError("not_found");
  if (to.currency.toUpperCase() !== g.currency.toUpperCase()) throw new DomainError("currency_mismatch");

  const when = date ?? todayISO();
  const total = await allocatedSum(db, id);
  if (total > 0) {
    await createTransferPair(db, {
      fromSourceId: g.source_id,
      toSourceId,
      amount: total,
      date: when,
      note: `↩ ${g.name}`,
    });
  }
  // Keep the deposit movements (double-payout guard); drop only the tracking rows.
  await db.execute(`DELETE FROM goal_allocations WHERE goal_id = ?`, [id]);
  await db.execute(`UPDATE goals SET status = 'completed', updated_at = ? WHERE id = ?`, [now(), id]);
}

export interface EnrichedGoal extends GoalRow {
  source_name: string | null;
  is_fund: boolean;
  allocated: number;
  progress_pct: number;
}

export async function listGoals(
  db: SqlExecutor,
  opts: { status?: string; currency?: string } = {},
): Promise<EnrichedGoal[]> {
  const cond: string[] = [];
  const params: unknown[] = [];
  if (opts.status) {
    cond.push("g.status = ?");
    params.push(opts.status);
  }
  if (opts.currency) {
    cond.push("g.currency = ?");
    params.push(opts.currency);
  }
  const where = cond.length ? "WHERE " + cond.join(" AND ") : "";
  const rows = await db.select<GoalRow & { source_name: string | null; is_savings_fund: number }>(
    `SELECT g.*, s.name AS source_name, s.is_savings_fund FROM goals g LEFT JOIN sources s ON g.source_id = s.id ${where}`,
    params,
  );
  const enriched: EnrichedGoal[] = [];
  for (const r of rows) {
    const allocated = await allocatedSum(db, r.id);
    enriched.push({
      ...r,
      source_name: r.source_name,
      is_fund: r.is_savings_fund === 1,
      allocated,
      progress_pct: r.target_amount > 0 ? round2((allocated / r.target_amount) * 100) : 0,
    });
  }
  // active first, then target_date asc (nulls last), then id
  const statusRank = { active: 0, completed: 1, cancelled: 2 } as const;
  return enriched.sort((a, b) => {
    if (statusRank[a.status] !== statusRank[b.status]) return statusRank[a.status] - statusRank[b.status];
    if (a.target_date && b.target_date) return a.target_date < b.target_date ? -1 : a.target_date > b.target_date ? 1 : a.id - b.id;
    if (a.target_date) return -1;
    if (b.target_date) return 1;
    return a.id - b.id;
  });
}
