/**
 * Single shared database connection. In the packaged app this is native SQLite
 * (plugin-sql) opening the real yfine.db; in a browser dev preview it's an
 * in-memory sql.js DB seeded with sample data. Either way the schema is brought
 * up to date by the drift-tolerant migrate() before first use.
 */
import type { SqlExecutor } from "./types";
import { migrate } from "./migrate";
import { runScheduler } from "./repo/scheduler";
import { isTauri } from "@/lib/tauri";
import { todayISO } from "@/lib/date";

let dbPromise: Promise<SqlExecutor> | null = null;

export function getDb(): Promise<SqlExecutor> {
  if (!dbPromise) dbPromise = init();
  return dbPromise;
}

/** True when running on the in-memory preview DB (no persistence). */
export const isPreviewDb = !isTauri();

async function init(): Promise<SqlExecutor> {
  let exec: SqlExecutor;
  if (isTauri()) {
    const { createPluginSqlExecutor } = await import("./executor-pluginsql");
    exec = (await createPluginSqlExecutor()).exec;
    // Use a rollback journal (not WAL): committed data always lives in yfine.db
    // itself, so the Rust encrypt-on-close reads a complete database (no lost
    // transactions stranded in an uncheckpointed -wal). Also makes BEGIN/COMMIT
    // give real atomicity on the single working connection.
    await exec.execute("PRAGMA journal_mode=DELETE");
    await migrate(exec);
  } else {
    const { createSqlJsExecutor } = await import("./executor-sqljs");
    const { seedPreview } = await import("./seed");
    exec = (await createSqlJsExecutor()).exec;
    await migrate(exec);
    await seedPreview(exec);
  }
  // Startup reconciliation: apply due recurring items + accrue yields (idempotent).
  try {
    await runScheduler(exec, todayISO());
  } catch {
    /* never block app boot on the scheduler */
  }
  return exec;
}
