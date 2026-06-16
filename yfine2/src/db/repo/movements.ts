/**
 * Movements repository: plain in/out movements, two-leg transfers, bulk ops,
 * filtering/listing. Faithful port of services/movements.py (see
 * refactor-analysis/movements.md §2) with the two confirmed bugs designed OUT:
 *  - BUG-1: transfer edits reject from===to (same-source self-transfer).
 *  - BUG-2: plain updateMovement refuses to touch a transfer leg (would desync).
 */
import type { SqlExecutor } from "../types";
import type { MovementRow } from "../schema-types";
import { DomainError } from "../errors";
import { getSource } from "./sources";
import { createTransferPair, deleteMovementCascade, type TransferPair } from "./transfers";

const now = () => new Date().toISOString();
const MAX_NOTE = 1000;

function cleanNote(note: string | null | undefined): string | null {
  if (note == null) return null;
  const trimmed = note.trim();
  if (!trimmed) return null;
  if (trimmed.length > MAX_NOTE) throw new DomainError("note_too_long");
  return trimmed;
}

export async function getMovement(db: SqlExecutor, id: number): Promise<MovementRow | null> {
  const rows = await db.select<MovementRow>(`SELECT * FROM movements WHERE id = ?`, [id]);
  return rows[0] ?? null;
}

async function setTags(db: SqlExecutor, movementId: number, tagIds: number[]) {
  await db.execute(`DELETE FROM movement_tag WHERE movement_id = ?`, [movementId]);
  for (const tagId of tagIds) {
    await db.execute(`INSERT OR IGNORE INTO movement_tag (movement_id, tag_id) VALUES (?, ?)`, [movementId, tagId]);
  }
}

// ---- plain movements ----------------------------------------------------

export interface NewMovement {
  source_id?: number | null;
  amount: number;
  direction: "in" | "out";
  date: string;
  note?: string | null;
  tagIds?: number[];
  exclude_from_stats?: boolean;
}

export async function createMovement(db: SqlExecutor, data: NewMovement): Promise<number> {
  if (!(data.amount > 0)) throw new DomainError("invalid_amount");
  if (data.source_id != null && !(await getSource(db, data.source_id)))
    throw new DomainError("not_found");
  const note = cleanNote(data.note);
  const ts = now();
  const rows = await db.select<{ id: number }>(
    `INSERT INTO movements
       (source_id,amount,direction,date,note,transfer_pair_id,exclude_from_stats,is_savings_contribution,created_at,updated_at)
     VALUES (?,?,?,?,?,NULL,?,0,?,?) RETURNING id`,
    [data.source_id ?? null, data.amount, data.direction, data.date, note, data.exclude_from_stats ? 1 : 0, ts, ts],
  );
  if (data.tagIds) await setTags(db, rows[0].id, data.tagIds);
  return rows[0].id;
}

export interface MovementPatch {
  source_id?: number | null;
  amount?: number;
  direction?: "in" | "out";
  date?: string;
  note?: string | null;
  exclude_from_stats?: boolean;
  tagIds?: number[];
}

export async function updateMovement(db: SqlExecutor, id: number, patch: MovementPatch): Promise<void> {
  const m = await getMovement(db, id);
  if (!m) throw new DomainError("not_found");
  // BUG-2 fix: never edit a transfer leg through the plain path — it desyncs the pair.
  if (m.transfer_pair_id != null) throw new DomainError("is_transfer_leg");

  const sets: string[] = [];
  const params: unknown[] = [];
  const set = (c: string, v: unknown) => {
    sets.push(`${c} = ?`);
    params.push(v);
  };
  if (patch.amount !== undefined) {
    if (!(patch.amount > 0)) throw new DomainError("invalid_amount");
    set("amount", patch.amount);
  }
  if (patch.direction !== undefined) set("direction", patch.direction);
  if (patch.date !== undefined) set("date", patch.date);
  if (patch.note !== undefined) set("note", cleanNote(patch.note));
  if (patch.exclude_from_stats !== undefined) set("exclude_from_stats", patch.exclude_from_stats ? 1 : 0);
  if (patch.source_id !== undefined) {
    if (patch.source_id != null && !(await getSource(db, patch.source_id))) throw new DomainError("not_found");
    set("source_id", patch.source_id);
  }
  set("updated_at", now());
  await db.execute(`UPDATE movements SET ${sets.join(", ")} WHERE id = ?`, [...params, id]);
  if (patch.tagIds !== undefined) await setTags(db, id, patch.tagIds);
}

export async function deleteMovement(db: SqlExecutor, id: number): Promise<void> {
  await deleteMovementCascade(db, id);
}

export async function toggleExclude(db: SqlExecutor, id: number): Promise<void> {
  const m = await getMovement(db, id);
  if (!m) throw new DomainError("not_found");
  await db.execute(`UPDATE movements SET exclude_from_stats = ?, updated_at = ? WHERE id = ?`, [
    m.exclude_from_stats ? 0 : 1,
    now(),
    id,
  ]);
}

// ---- transfers ----------------------------------------------------------

export interface NewTransfer {
  fromSourceId: number;
  toSourceId: number;
  amount: number;
  date: string;
  note?: string | null;
  tagIds?: number[];
  toAmount?: number | null;
}

export async function createTransfer(db: SqlExecutor, t: NewTransfer): Promise<TransferPair> {
  if (t.fromSourceId === t.toSourceId) throw new DomainError("same_source");
  if (!(t.amount > 0)) throw new DomainError("invalid_amount");
  if (t.toAmount != null && !(t.toAmount > 0)) throw new DomainError("invalid_amount");
  const from = await getSource(db, t.fromSourceId);
  const to = await getSource(db, t.toSourceId);
  if (!from || !to) throw new DomainError("not_found");
  return createTransferPair(db, {
    fromSourceId: t.fromSourceId,
    toSourceId: t.toSourceId,
    amount: t.amount,
    date: t.date,
    note: cleanNote(t.note),
    tagIds: t.tagIds ?? [],
    toAmount: t.toAmount ?? null,
  });
}

export interface TransferPatch {
  fromSourceId?: number;
  toSourceId?: number;
  amount?: number;
  toAmount?: number | null;
  date?: string;
  note?: string | null;
  tagIds?: number[];
}

/** Edit a transfer via its OUT-leg id. Keeps both legs in sync (§2.2 / §14). */
export async function updateTransfer(db: SqlExecutor, outLegId: number, patch: TransferPatch): Promise<void> {
  const out = await getMovement(db, outLegId);
  if (!out) throw new DomainError("not_found");
  if (out.transfer_pair_id == null) throw new DomainError("not_a_transfer");
  const inLeg = await getMovement(db, out.transfer_pair_id);
  if (!inLeg) throw new DomainError("not_found");

  const newFrom = patch.fromSourceId ?? out.source_id!;
  const newTo = patch.toSourceId ?? inLeg.source_id!;
  // BUG-1 fix: a transfer's two legs must sit on different sources.
  if (newFrom === newTo) throw new DomainError("same_source");
  const fromSrc = await getSource(db, newFrom);
  const toSrc = await getSource(db, newTo);
  if (!fromSrc || !toSrc) throw new DomainError("not_found");
  const sameCcy = fromSrc.currency === toSrc.currency;

  const outSets: string[] = [];
  const outParams: unknown[] = [];
  const inSets: string[] = [];
  const inParams: unknown[] = [];
  const oset = (c: string, v: unknown) => (outSets.push(`${c} = ?`), outParams.push(v));
  const iset = (c: string, v: unknown) => (inSets.push(`${c} = ?`), inParams.push(v));

  if (patch.fromSourceId !== undefined) oset("source_id", newFrom);
  if (patch.toSourceId !== undefined) iset("source_id", newTo);
  if (patch.date !== undefined) {
    oset("date", patch.date);
    iset("date", patch.date);
  }
  if (patch.note !== undefined) {
    const n = cleanNote(patch.note);
    oset("note", n);
    iset("note", n);
  }
  if (patch.amount !== undefined) {
    if (!(patch.amount > 0)) throw new DomainError("invalid_amount");
    oset("amount", patch.amount);
    // mirror onto IN only for same-currency transfers without an explicit toAmount
    if (patch.toAmount == null && sameCcy) iset("amount", patch.amount);
  }
  if (patch.toAmount !== undefined && patch.toAmount != null) {
    if (!(patch.toAmount > 0)) throw new DomainError("invalid_amount");
    iset("amount", patch.toAmount);
  }

  oset("updated_at", now());
  iset("updated_at", now());
  await db.execute(`UPDATE movements SET ${outSets.join(", ")} WHERE id = ?`, [...outParams, out.id]);
  await db.execute(`UPDATE movements SET ${inSets.join(", ")} WHERE id = ?`, [...inParams, inLeg.id]);

  if (patch.tagIds !== undefined) {
    await setTags(db, out.id, patch.tagIds);
    await setTags(db, inLeg.id, patch.tagIds);
  }
}

// ---- bulk ops -----------------------------------------------------------

export async function bulkDelete(
  db: SqlExecutor,
  ids: number[],
): Promise<{ affected: number; skipped: number[] }> {
  const removed = new Set<number>();
  const skipped: number[] = [];
  let affected = 0;
  for (const id of ids) {
    if (removed.has(id)) continue; // partner already deleted with its sibling
    const m = await getMovement(db, id);
    if (!m) {
      skipped.push(id);
      continue;
    }
    await deleteMovementCascade(db, id);
    affected += 1;
    removed.add(id);
    if (m.transfer_pair_id != null) removed.add(m.transfer_pair_id);
  }
  return { affected, skipped };
}

export type TagMode = "add" | "remove" | "replace";

export async function bulkSetTags(
  db: SqlExecutor,
  ids: number[],
  tagIds: number[],
  mode: TagMode,
): Promise<{ affected: number }> {
  if (tagIds.length) {
    const ph = tagIds.map(() => "?").join(",");
    const found = await db.select<{ c: number }>(`SELECT COUNT(*) c FROM tags WHERE id IN (${ph})`, tagIds);
    if ((found[0]?.c ?? 0) !== new Set(tagIds).size) throw new DomainError("unknown_tag");
  }

  // expand to transfer partners so both legs stay in sync
  const targets = new Set<number>();
  let affected = 0;
  for (const id of ids) {
    const m = await getMovement(db, id);
    if (!m) continue;
    affected += 1;
    targets.add(m.id);
    if (m.transfer_pair_id != null) targets.add(m.transfer_pair_id);
  }

  for (const t of targets) {
    if (mode === "replace") {
      await setTags(db, t, tagIds);
    } else if (mode === "add") {
      for (const tagId of tagIds)
        await db.execute(`INSERT OR IGNORE INTO movement_tag (movement_id, tag_id) VALUES (?, ?)`, [t, tagId]);
    } else {
      if (tagIds.length) {
        const ph = tagIds.map(() => "?").join(",");
        await db.execute(`DELETE FROM movement_tag WHERE movement_id = ? AND tag_id IN (${ph})`, [t, ...tagIds]);
      }
    }
    await db.execute(`UPDATE movements SET updated_at = ? WHERE id = ?`, [now(), t]);
  }
  return { affected };
}

export async function bulkSetSource(
  db: SqlExecutor,
  ids: number[],
  sourceId: number | null,
): Promise<{ affected: number; skipped: number[] }> {
  if (sourceId != null && !(await getSource(db, sourceId))) throw new DomainError("not_found");
  const skipped: number[] = [];
  let affected = 0;
  for (const id of ids) {
    const m = await getMovement(db, id);
    if (!m) {
      skipped.push(id);
      continue;
    }
    if (m.transfer_pair_id != null) {
      skipped.push(id); // can't reassign a transfer leg's source here
      continue;
    }
    await db.execute(`UPDATE movements SET source_id = ?, updated_at = ? WHERE id = ?`, [sourceId, now(), id]);
    affected += 1;
  }
  return { affected, skipped };
}

// ---- listing / filtering ------------------------------------------------

export interface MovementFilters {
  sourceId?: number | null;
  tagIds?: number[];
  tagMatch?: "or" | "and";
  direction?: "in" | "out";
  dateFrom?: string;
  dateTo?: string;
  amountMin?: number;
  amountMax?: number;
  q?: string;
  excludeTransferIn?: boolean;
}

export interface EnrichedMovement extends MovementRow {
  source_name: string | null;
  source_currency: string | null;
  partner_source_name: string | null;
  partner_source_id: number | null;
  partner_amount: number | null;
  tags: { id: number; name: string; color: string | null }[];
}

function buildFilter(f: MovementFilters): { where: string; params: unknown[] } {
  const cond: string[] = [];
  const params: unknown[] = [];
  if (f.dateFrom && f.dateTo && f.dateFrom > f.dateTo) throw new DomainError("invalid_range");
  if (f.amountMin != null && f.amountMax != null && f.amountMin > f.amountMax)
    throw new DomainError("invalid_range");

  if (f.sourceId !== undefined) {
    if (f.sourceId === null) cond.push("m.source_id IS NULL");
    else {
      cond.push("m.source_id = ?");
      params.push(f.sourceId);
    }
  }
  if (f.direction) {
    cond.push("m.direction = ?");
    params.push(f.direction);
  }
  if (f.dateFrom) {
    cond.push("m.date >= ?");
    params.push(f.dateFrom);
  }
  if (f.dateTo) {
    cond.push("m.date <= ?");
    params.push(f.dateTo);
  }
  if (f.amountMin != null) {
    cond.push("m.amount >= ?");
    params.push(f.amountMin);
  }
  if (f.amountMax != null) {
    cond.push("m.amount <= ?");
    params.push(f.amountMax);
  }
  if (f.q && f.q.trim()) {
    const esc = f.q.trim().replace(/([\\%_])/g, "\\$1");
    cond.push("m.note LIKE ? ESCAPE '\\'");
    params.push(`%${esc}%`);
  }
  if (f.excludeTransferIn) cond.push("(m.transfer_pair_id IS NULL OR m.direction != 'in')");
  if (f.tagIds && f.tagIds.length) {
    const ph = f.tagIds.map(() => "?").join(",");
    if (f.tagMatch === "and") {
      cond.push(
        `m.id IN (SELECT movement_id FROM movement_tag WHERE tag_id IN (${ph}) GROUP BY movement_id HAVING COUNT(DISTINCT tag_id) = ?)`,
      );
      params.push(...f.tagIds, f.tagIds.length);
    } else {
      cond.push(`m.id IN (SELECT movement_id FROM movement_tag WHERE tag_id IN (${ph}))`);
      params.push(...f.tagIds);
    }
  }
  return { where: cond.length ? "WHERE " + cond.join(" AND ") : "", params };
}

export async function countMovements(db: SqlExecutor, f: MovementFilters): Promise<number> {
  const { where, params } = buildFilter(f);
  const rows = await db.select<{ c: number }>(`SELECT COUNT(*) c FROM movements m ${where}`, params);
  return rows[0]?.c ?? 0;
}

export async function listMovements(
  db: SqlExecutor,
  f: MovementFilters = {},
  opts: { limit?: number; offset?: number } = {},
): Promise<EnrichedMovement[]> {
  const { where, params } = buildFilter(f);
  const limit = opts.limit ?? 50;
  const offset = opts.offset ?? 0;
  const rows = await db.select<MovementRow & {
    source_name: string | null;
    source_currency: string | null;
    partner_source_name: string | null;
    partner_source_id: number | null;
    partner_amount: number | null;
  }>(
    `SELECT m.*, s.name AS source_name, s.currency AS source_currency,
       (SELECT ps.name FROM movements pm LEFT JOIN sources ps ON pm.source_id = ps.id WHERE pm.id = m.transfer_pair_id) AS partner_source_name,
       (SELECT pm.source_id FROM movements pm WHERE pm.id = m.transfer_pair_id) AS partner_source_id,
       (SELECT pm.amount FROM movements pm WHERE pm.id = m.transfer_pair_id) AS partner_amount
     FROM movements m LEFT JOIN sources s ON m.source_id = s.id
     ${where}
     ORDER BY m.date DESC, m.id DESC
     LIMIT ? OFFSET ?`,
    [...params, limit, offset],
  );

  const byId = new Map<number, EnrichedMovement>();
  for (const r of rows) byId.set(r.id, { ...r, tags: [] });

  if (rows.length) {
    const ids = rows.map((r) => r.id);
    const ph = ids.map(() => "?").join(",");
    const tagRows = await db.select<{ movement_id: number; id: number; name: string; color: string | null }>(
      `SELECT mt.movement_id, t.id, t.name, t.color
       FROM movement_tag mt JOIN tags t ON t.id = mt.tag_id
       WHERE mt.movement_id IN (${ph}) ORDER BY t.name COLLATE NOCASE`,
      ids,
    );
    for (const tr of tagRows) {
      byId.get(tr.movement_id)?.tags.push({ id: tr.id, name: tr.name, color: tr.color });
    }
  }

  return rows.map((r) => byId.get(r.id)!);
}
