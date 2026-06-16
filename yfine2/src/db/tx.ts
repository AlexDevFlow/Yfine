/**
 * Re-entrant transaction helper. Wraps a unit of work in BEGIN/COMMIT (ROLLBACK
 * on throw) so multi-statement money operations are atomic — a mid-operation
 * failure can't leave an orphaned transfer leg or a half-applied change.
 *
 * Re-entrancy: nested withTx() calls (e.g. purchaseWhim → closeGoal → createTransferPair)
 * join the outermost transaction instead of issuing an illegal nested BEGIN.
 * Depth is tracked per-executor. Operations are awaited serially in this app, so
 * on the pooled plugin-sql backend the BEGIN/…/COMMIT land on one connection;
 * the in-memory test/preview backends are single-connection by construction.
 */
import type { SqlExecutor } from "./types";

const depth = new WeakMap<SqlExecutor, number>();

export async function withTx<T>(db: SqlExecutor, fn: () => Promise<T>): Promise<T> {
  if ((depth.get(db) ?? 0) > 0) return fn(); // already inside a transaction
  depth.set(db, 1);
  await db.execute("BEGIN");
  try {
    const result = await fn();
    await db.execute("COMMIT");
    return result;
  } catch (e) {
    try {
      await db.execute("ROLLBACK");
    } catch {
      /* ignore rollback errors */
    }
    throw e;
  } finally {
    depth.set(db, 0);
  }
}
