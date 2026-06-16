/**
 * The single transfer-pair primitive reused by transfers, savings deposits, and
 * goal allocations (the legacy app duplicated this in 4 places). A transfer is
 * two movements — an OUT leg on the from-source and an IN leg on the to-source —
 * mutually linked by transfer_pair_id, sharing date + note, with tags copied to
 * BOTH legs. Cross-currency keeps an independent `toAmount` on the IN leg.
 */
import type { SqlExecutor } from "../types";

const now = () => new Date().toISOString();

export interface TransferPairInput {
  fromSourceId: number | null;
  toSourceId: number | null;
  amount: number; // OUT-leg amount (in the from-source's currency)
  date: string;
  note?: string | null;
  tagIds?: number[];
  /** IN-leg amount for cross-currency transfers; defaults to `amount`. */
  toAmount?: number | null;
  /** Flags the IN leg as a savings-page deposit (counts toward "saved"). */
  isSavingsContribution?: boolean;
}

async function insertLeg(
  db: SqlExecutor,
  sourceId: number | null,
  amount: number,
  direction: "in" | "out",
  date: string,
  note: string | null,
  isSavingsContribution: boolean,
): Promise<number> {
  const ts = now();
  const rows = await db.select<{ id: number }>(
    `INSERT INTO movements
       (source_id,amount,direction,date,note,transfer_pair_id,exclude_from_stats,is_savings_contribution,created_at,updated_at)
     VALUES (?,?,?,?,?,NULL,0,?,?,?) RETURNING id`,
    [sourceId, amount, direction, date, note ?? null, isSavingsContribution ? 1 : 0, ts, ts],
  );
  return rows[0].id;
}

async function copyTags(db: SqlExecutor, movementId: number, tagIds: number[]) {
  for (const tagId of tagIds) {
    await db.execute(
      `INSERT OR IGNORE INTO movement_tag (movement_id, tag_id) VALUES (?, ?)`,
      [movementId, tagId],
    );
  }
}

export interface TransferPair {
  outId: number;
  inId: number;
}

export async function createTransferPair(
  db: SqlExecutor,
  input: TransferPairInput,
): Promise<TransferPair> {
  const note = input.note ?? null;
  const tagIds = input.tagIds ?? [];
  const inAmount = input.toAmount ?? input.amount;

  const outId = await insertLeg(db, input.fromSourceId, input.amount, "out", input.date, note, false);
  const inId = await insertLeg(
    db,
    input.toSourceId,
    inAmount,
    "in",
    input.date,
    note,
    input.isSavingsContribution ?? false,
  );

  await db.execute(`UPDATE movements SET transfer_pair_id = ? WHERE id = ?`, [inId, outId]);
  await db.execute(`UPDATE movements SET transfer_pair_id = ? WHERE id = ?`, [outId, inId]);

  if (tagIds.length) {
    await copyTags(db, outId, tagIds);
    await copyTags(db, inId, tagIds);
  }

  return { outId, inId };
}

/**
 * Delete a movement and, if it's part of a transfer, its partner leg too —
 * plus tag links, attachments, and goal allocations for both. (FK CASCADE is a
 * backstop; the explicit purge also defends against SQLite rowid reuse.)
 */
export async function deleteMovementCascade(
  db: SqlExecutor,
  id: number,
): Promise<void> {
  const rows = await db.select<{ id: number; transfer_pair_id: number | null }>(
    `SELECT id, transfer_pair_id FROM movements WHERE id = ?`,
    [id],
  );
  if (!rows[0]) return;
  const ids = new Set<number>([id]);
  if (rows[0].transfer_pair_id != null) ids.add(rows[0].transfer_pair_id);
  const list = [...ids];
  const ph = list.map(() => "?").join(",");
  await db.execute(`DELETE FROM goal_allocations WHERE movement_id IN (${ph})`, list);
  await db.execute(`DELETE FROM movement_tag WHERE movement_id IN (${ph})`, list);
  await db.execute(`DELETE FROM movement_attachments WHERE movement_id IN (${ph})`, list);
  await db.execute(`DELETE FROM movements WHERE id IN (${ph})`, list);
}
