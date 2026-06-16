import type { SqlExecutor } from "../types";

export type NotificationType = "info" | "alert" | "warning";

export interface NotificationRow {
  id: number;
  type: NotificationType;
  title: string;
  body: string;
  related_entity: string | null;
  is_read: number;
  created_at: string;
}

const now = () => new Date().toISOString();

export async function createNotification(
  db: SqlExecutor,
  n: { type: NotificationType; title: string; body: string; related_entity?: string | null },
): Promise<void> {
  await db.execute(
    `INSERT INTO notifications (type,title,body,related_entity,is_read,created_at) VALUES (?,?,?,?,0,?)`,
    [n.type, n.title, n.body, n.related_entity ?? null, now()],
  );
}

/** True if an UNREAD notification exists for this exact related_entity. */
export async function hasUnread(db: SqlExecutor, relatedEntity: string): Promise<boolean> {
  const r = await db.select<{ c: number }>(
    `SELECT COUNT(*) c FROM notifications WHERE related_entity = ? AND is_read = 0`,
    [relatedEntity],
  );
  return (r[0]?.c ?? 0) > 0;
}

export async function listNotifications(
  db: SqlExecutor,
  opts: { limit?: number; unreadOnly?: boolean } = {},
): Promise<NotificationRow[]> {
  const where = opts.unreadOnly ? "WHERE is_read = 0" : "";
  return db.select<NotificationRow>(
    `SELECT id,type,title,body,related_entity,is_read,created_at FROM notifications ${where} ORDER BY created_at DESC, id DESC LIMIT ?`,
    [opts.limit ?? 100],
  );
}

export async function unreadCount(db: SqlExecutor): Promise<number> {
  const r = await db.select<{ c: number }>(`SELECT COUNT(*) c FROM notifications WHERE is_read = 0`);
  return r[0]?.c ?? 0;
}

export async function markRead(db: SqlExecutor, id: number): Promise<void> {
  await db.execute(`UPDATE notifications SET is_read = 1 WHERE id = ?`, [id]);
}

export async function markAllRead(db: SqlExecutor): Promise<void> {
  await db.execute(`UPDATE notifications SET is_read = 1 WHERE is_read = 0`);
}

export async function deleteNotification(db: SqlExecutor, id: number): Promise<void> {
  await db.execute(`DELETE FROM notifications WHERE id = ?`, [id]);
}
