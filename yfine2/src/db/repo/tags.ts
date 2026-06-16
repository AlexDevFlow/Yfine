import type { SqlExecutor } from "../types";
import type { TagRow } from "../schema-types";
import { DomainError } from "../errors";

const now = () => new Date().toISOString();

export async function listTags(db: SqlExecutor): Promise<TagRow[]> {
  return db.select<TagRow>(
    `SELECT id,name,color,created_at,updated_at FROM tags ORDER BY name COLLATE NOCASE`,
  );
}

export interface TagWithUsage extends TagRow {
  /** Number of movements carrying this tag. */
  movement_count: number;
  /** Number of budgets scoped to this tag. */
  budget_count: number;
}

/** Tags with their usage counts — powers the Tags page (delete weighs these). */
export async function listTagsWithUsage(db: SqlExecutor): Promise<TagWithUsage[]> {
  return db.select<TagWithUsage>(
    `SELECT t.id, t.name, t.color, t.created_at, t.updated_at,
       (SELECT COUNT(*) FROM movement_tag mt WHERE mt.tag_id = t.id) AS movement_count,
       (SELECT COUNT(*) FROM budgets b WHERE b.tag_id = t.id) AS budget_count
     FROM tags t ORDER BY t.name COLLATE NOCASE`,
  );
}

/** Normalize/validate a hex color (matches the legacy schema: #RGB, #RRGGBB, #RRGGBBAA). */
function normalizeColor(color?: string | null): string | null {
  if (color == null) return null;
  const c = color.trim();
  if (!c) return null;
  if (!/^#([0-9a-f]{3}|[0-9a-f]{6}|[0-9a-f]{8})$/i.test(c)) throw new DomainError("invalid_color");
  return c.toLowerCase();
}

async function rejectDuplicateName(db: SqlExecutor, name: string, excludeId?: number): Promise<void> {
  const rows = await db.select<{ id: number }>(
    `SELECT id FROM tags WHERE name = ? COLLATE NOCASE${excludeId ? " AND id != ?" : ""}`,
    excludeId ? [name, excludeId] : [name],
  );
  if (rows.length) throw new DomainError("duplicate_tag");
}

export interface NewTag {
  name: string;
  color?: string | null;
}

export async function createTag(db: SqlExecutor, data: NewTag): Promise<number> {
  const name = data.name.trim();
  if (!name) throw new DomainError("tag_name_required");
  const color = normalizeColor(data.color);
  await rejectDuplicateName(db, name);
  const ts = now();
  const rows = await db.select<{ id: number }>(
    `INSERT INTO tags (name,color,created_at,updated_at) VALUES (?,?,?,?) RETURNING id`,
    [name, color, ts, ts],
  );
  return rows[0].id;
}

export interface TagPatch {
  name?: string;
  color?: string | null;
}

export async function updateTag(db: SqlExecutor, id: number, patch: TagPatch): Promise<void> {
  const cur = await db.select<{ id: number }>(`SELECT id FROM tags WHERE id = ?`, [id]);
  if (!cur.length) throw new DomainError("not_found");

  const sets: string[] = [];
  const params: unknown[] = [];
  if (patch.name !== undefined) {
    const name = patch.name.trim();
    if (!name) throw new DomainError("tag_name_required");
    await rejectDuplicateName(db, name, id);
    sets.push("name = ?");
    params.push(name);
  }
  if (patch.color !== undefined) {
    sets.push("color = ?");
    params.push(normalizeColor(patch.color));
  }
  if (!sets.length) return;
  sets.push("updated_at = ?");
  params.push(now(), id);
  await db.execute(`UPDATE tags SET ${sets.join(", ")} WHERE id = ?`, params);
}

/**
 * Delete a tag. `movement_tag` links drop via ON DELETE CASCADE, but `budgets`
 * has no cascade on its tag FK — so remove dependent budgets first or the
 * delete would hit a FOREIGN KEY constraint (mirrors the legacy service).
 */
export async function deleteTag(db: SqlExecutor, id: number): Promise<void> {
  await db.execute(`DELETE FROM budgets WHERE tag_id = ?`, [id]);
  await db.execute(`DELETE FROM tags WHERE id = ?`, [id]);
}

/**
 * Merge `fromId` into `intoId`: re-point every tagged movement to the target tag
 * (deduping links), drop the source tag's budgets, then delete the source tag.
 * Run inside a transaction by the caller.
 */
export async function mergeTags(db: SqlExecutor, fromId: number, intoId: number): Promise<void> {
  if (fromId === intoId) throw new DomainError("same_source");
  const exists = await db.select<{ id: number }>(`SELECT id FROM tags WHERE id IN (?, ?)`, [fromId, intoId]);
  if (exists.length < 2) throw new DomainError("not_found");
  await db.execute(
    `INSERT OR IGNORE INTO movement_tag (movement_id, tag_id) SELECT movement_id, ? FROM movement_tag WHERE tag_id = ?`,
    [intoId, fromId],
  );
  await db.execute(`DELETE FROM movement_tag WHERE tag_id = ?`, [fromId]);
  await db.execute(`DELETE FROM budgets WHERE tag_id = ?`, [fromId]);
  await db.execute(`DELETE FROM tags WHERE id = ?`, [fromId]);
}
