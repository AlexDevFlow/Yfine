/**
 * Movement attachments — files stored on disk under $APPDATA/attachments via the
 * Tauri fs plugin (the DB keeps only metadata: filename, stored_name, mime,
 * size). Tauri-only; the browser preview has no filesystem. Schema unchanged
 * from the legacy app (movement_attachments).
 */
import { BaseDirectory, mkdir, readFile, remove, writeFile } from "@tauri-apps/plugin-fs";
import type { SqlExecutor } from "../types";

const DIR = "attachments";
const now = () => new Date().toISOString();

export interface AttachmentRow {
  id: number;
  movement_id: number;
  filename: string;
  stored_name: string;
  mime_type: string;
  size_bytes: number;
  created_at: string;
}

export async function listAttachments(db: SqlExecutor, movementId: number): Promise<AttachmentRow[]> {
  return db.select<AttachmentRow>(
    `SELECT id,movement_id,filename,stored_name,mime_type,size_bytes,created_at
     FROM movement_attachments WHERE movement_id = ? ORDER BY id`,
    [movementId],
  );
}

export async function addAttachment(
  db: SqlExecutor,
  movementId: number,
  file: { name: string; type: string; bytes: Uint8Array },
): Promise<number> {
  await mkdir(DIR, { baseDir: BaseDirectory.AppData, recursive: true });
  const safe = file.name.replace(/[^\w.\-]+/g, "_").slice(0, 80);
  const stored = `${movementId}_${Date.now()}_${safe}`;
  await writeFile(`${DIR}/${stored}`, file.bytes, { baseDir: BaseDirectory.AppData });
  const rows = await db.select<{ id: number }>(
    `INSERT INTO movement_attachments (movement_id,filename,stored_name,mime_type,size_bytes,created_at)
     VALUES (?,?,?,?,?,?) RETURNING id`,
    [movementId, file.name, stored, file.type || "application/octet-stream", file.bytes.length, now()],
  );
  return rows[0].id;
}

/** Read an attachment's bytes back from disk (for preview/download). */
export async function readAttachment(storedName: string): Promise<Uint8Array> {
  return readFile(`${DIR}/${storedName}`, { baseDir: BaseDirectory.AppData });
}

export async function deleteAttachment(db: SqlExecutor, att: Pick<AttachmentRow, "id" | "stored_name">): Promise<void> {
  await db.execute(`DELETE FROM movement_attachments WHERE id = ?`, [att.id]);
  try {
    await remove(`${DIR}/${att.stored_name}`, { baseDir: BaseDirectory.AppData });
  } catch {
    /* file already gone — metadata removal is what matters */
  }
}

/** Count of attachments per movement id (for list badges). */
export async function attachmentCounts(db: SqlExecutor): Promise<Map<number, number>> {
  const rows = await db.select<{ movement_id: number; c: number }>(
    `SELECT movement_id, COUNT(*) c FROM movement_attachments GROUP BY movement_id`,
  );
  return new Map(rows.map((r) => [r.movement_id, r.c]));
}
