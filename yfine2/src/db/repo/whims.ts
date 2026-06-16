/**
 * Whims: priority wishlist (refactor-analysis/budgets-goals-whims.md §C).
 * purchase can drain a linked "save-for" goal into the purchase source first.
 * Bug B-2 fixed: currency comparisons are normalized (.toUpperCase()) throughout,
 * so a manually-linked goal with differently-cased currency can't spuriously block.
 */
import type { SqlExecutor } from "../types";
import { DomainError } from "../errors";
import { getSource } from "./sources";
import { closeGoal, createGoal, getGoal } from "./goals";
import { createNotification } from "./notifications";

const now = () => new Date().toISOString();

export interface WhimRow {
  id: number;
  name: string;
  amount: number;
  currency: string;
  priority: "low" | "medium" | "high";
  source_id: number | null;
  status: "pending" | "purchased" | "dismissed";
  note: string | null;
  url: string | null;
  purchased_at: string | null;
  linked_goal_id: number | null;
  created_at: string;
  updated_at: string;
}

export async function getWhim(db: SqlExecutor, id: number): Promise<WhimRow | null> {
  const r = await db.select<WhimRow>(`SELECT * FROM whims WHERE id = ?`, [id]);
  return r[0] ?? null;
}

export interface NewWhim {
  name: string;
  amount: number;
  currency: string;
  priority?: "low" | "medium" | "high";
  source_id?: number | null;
  note?: string | null;
  url?: string | null;
}

export async function createWhim(db: SqlExecutor, data: NewWhim): Promise<number> {
  if (!(data.amount > 0)) throw new DomainError("invalid_amount");
  const ts = now();
  const rows = await db.select<{ id: number }>(
    `INSERT INTO whims (name,amount,currency,priority,source_id,status,note,url,purchased_at,linked_goal_id,created_at,updated_at)
     VALUES (?,?,?,?,?, 'pending', ?,?, NULL, NULL, ?,?) RETURNING id`,
    [data.name, data.amount, data.currency.trim().toUpperCase(), data.priority ?? "medium", data.source_id ?? null, data.note ?? null, data.url ?? null, ts, ts],
  );
  return rows[0].id;
}

export type WhimPatch = Partial<NewWhim>;

export async function updateWhim(db: SqlExecutor, id: number, patch: WhimPatch): Promise<void> {
  const w = await getWhim(db, id);
  if (!w) throw new DomainError("not_found");
  if (patch.amount !== undefined && !(patch.amount > 0)) throw new DomainError("invalid_amount");
  const sets: string[] = [];
  const params: unknown[] = [];
  const set = (c: string, v: unknown) => (sets.push(`${c} = ?`), params.push(v));
  if (patch.name !== undefined) set("name", patch.name);
  if (patch.amount !== undefined) set("amount", patch.amount);
  if (patch.currency !== undefined) set("currency", patch.currency.trim().toUpperCase());
  if (patch.priority !== undefined) set("priority", patch.priority);
  if (patch.source_id !== undefined) set("source_id", patch.source_id);
  if (patch.note !== undefined) set("note", patch.note);
  if (patch.url !== undefined) set("url", patch.url);
  set("updated_at", now());
  await db.execute(`UPDATE whims SET ${sets.join(", ")} WHERE id = ?`, [...params, id]);
}

export async function purchaseWhim(
  db: SqlExecutor,
  id: number,
  input: { sourceId: number; note?: string | null; tagIds?: number[]; amount?: number },
): Promise<void> {
  const whim = await getWhim(db, id);
  if (!whim) throw new DomainError("not_found");
  if (whim.status === "purchased") throw new DomainError("whim_already_purchased");
  const source = await getSource(db, input.sourceId);
  if (!source) throw new DomainError("not_found");
  if (source.currency.toUpperCase() !== whim.currency.toUpperCase()) throw new DomainError("currency_mismatch");

  // The actual price paid may differ from the wishlisted amount — honor an
  // override and record it on the whim so its history matches reality.
  const price = input.amount != null && input.amount > 0 ? input.amount : whim.amount;

  // Save-for-then-buy: drain a still-funded linked goal into the purchase source.
  if (whim.linked_goal_id != null) {
    const goal = await getGoal(db, whim.linked_goal_id);
    if (goal && goal.status !== "cancelled") {
      const allocs = await db.select<{ c: number }>(`SELECT COUNT(*) c FROM goal_allocations WHERE goal_id = ?`, [goal.id]);
      if ((allocs[0]?.c ?? 0) > 0) {
        await closeGoal(db, goal.id, input.sourceId); // refunds saved money into the source
      }
    }
  }

  const ts = now();
  const mv = await db.select<{ id: number }>(
    `INSERT INTO movements (source_id,amount,direction,date,note,transfer_pair_id,exclude_from_stats,is_savings_contribution,created_at,updated_at)
     VALUES (?,?, 'out', ?, ?, NULL, 0, 0, ?, ?) RETURNING id`,
    [input.sourceId, price, ts.slice(0, 10), input.note || whim.name, ts, ts],
  );
  for (const tagId of input.tagIds ?? []) {
    await db.execute(`INSERT OR IGNORE INTO movement_tag (movement_id,tag_id) VALUES (?,?)`, [mv[0].id, tagId]);
  }
  await db.execute(`UPDATE whims SET status = 'purchased', amount = ?, purchased_at = ?, updated_at = ? WHERE id = ?`, [price, ts, ts, id]);
  await createNotification(db, { type: "info", title: `Purchased: ${whim.name}`, body: `−${price} ${whim.currency}`, related_entity: `whim:${id}` });
}

export async function dismissWhim(db: SqlExecutor, id: number): Promise<void> {
  await db.execute(`UPDATE whims SET status = 'dismissed', updated_at = ? WHERE id = ?`, [now(), id]);
}

export async function restoreWhim(db: SqlExecutor, id: number): Promise<void> {
  const w = await getWhim(db, id);
  if (!w) throw new DomainError("not_found");
  if (w.status !== "dismissed") throw new DomainError("not_dismissed");
  await db.execute(`UPDATE whims SET status = 'pending', updated_at = ? WHERE id = ?`, [now(), id]);
}

export async function deleteWhim(db: SqlExecutor, id: number): Promise<void> {
  await db.execute(`UPDATE goals SET linked_whim_id = NULL WHERE linked_whim_id = ?`, [id]);
  await db.execute(`DELETE FROM whims WHERE id = ?`, [id]);
}

/** Create (or return the existing) linked goal for a pending whim. Idempotent. */
export async function startSavingForWhim(db: SqlExecutor, id: number): Promise<number> {
  const w = await getWhim(db, id);
  if (!w) throw new DomainError("not_found");
  if (w.status !== "pending") throw new DomainError("not_pending");
  if (w.linked_goal_id != null) {
    const g = await getGoal(db, w.linked_goal_id);
    if (g) return g.id; // already saving — no duplicate goal
  }
  return createGoal(db, {
    name: w.name,
    target_amount: w.amount,
    currency: w.currency,
    note: w.note,
    linked_whim_id: id,
  });
}

export interface EnrichedWhim extends WhimRow {
  source_name: string | null;
  linked_goal_allocated: number | null;
  linked_goal_target: number | null;
  linked_goal_status: string | null;
}

export async function listWhims(
  db: SqlExecutor,
  opts: { status?: string; priority?: string } = {},
): Promise<EnrichedWhim[]> {
  const cond: string[] = [];
  const params: unknown[] = [];
  if (opts.status) {
    cond.push("w.status = ?");
    params.push(opts.status);
  }
  if (opts.priority) {
    cond.push("w.priority = ?");
    params.push(opts.priority);
  }
  const where = cond.length ? "WHERE " + cond.join(" AND ") : "";
  const rows = await db.select<WhimRow & { source_name: string | null }>(
    `SELECT w.*, s.name AS source_name FROM whims w LEFT JOIN sources s ON w.source_id = s.id ${where} ORDER BY w.created_at DESC, w.id DESC`,
    params,
  );
  const out: EnrichedWhim[] = [];
  for (const w of rows) {
    let allocated: number | null = null;
    let target: number | null = null;
    let status: string | null = null;
    if (w.linked_goal_id != null) {
      const g = await db.select<{ target_amount: number; status: string }>(`SELECT target_amount,status FROM goals WHERE id = ?`, [w.linked_goal_id]);
      if (g[0]) {
        const a = await db.select<{ total: number }>(`SELECT COALESCE(SUM(amount),0) total FROM goal_allocations WHERE goal_id = ?`, [w.linked_goal_id]);
        allocated = Math.round((a[0]?.total ?? 0) * 100) / 100;
        target = g[0].target_amount;
        status = g[0].status;
      }
    }
    out.push({ ...w, linked_goal_allocated: allocated, linked_goal_target: target, linked_goal_status: status });
  }
  return out;
}
