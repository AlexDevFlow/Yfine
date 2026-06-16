/**
 * Test-only helper: an in-memory better-sqlite3 database wrapped as a
 * SqlExecutor and migrated to the canonical schema. Used by repository tests so
 * the same SQL the app runs is exercised against a real SQLite engine.
 */
import Database from "better-sqlite3";
import type { SqlExecutor } from "@/db/types";
import { migrate } from "@/db/migrate";

export function rawExecutor(raw: Database.Database): SqlExecutor {
  return {
    async execute(sql, params = []) {
      raw.prepare(sql).run(...(params as unknown[]));
    },
    async select(sql, params = []) {
      return raw.prepare(sql).all(...(params as unknown[])) as never;
    },
  };
}

export async function makeMemDb(): Promise<{
  raw: Database.Database;
  db: SqlExecutor;
}> {
  const raw = new Database(":memory:");
  const db = rawExecutor(raw);
  await migrate(db);
  return { raw, db };
}

const TS = "2026-01-01T00:00:00";

export async function addMovement(
  db: SqlExecutor,
  sourceId: number | null,
  direction: "in" | "out",
  amount: number,
  date = "2026-01-01",
): Promise<void> {
  await db.execute(
    `INSERT INTO movements (source_id,amount,direction,date,exclude_from_stats,is_savings_contribution,created_at,updated_at)
     VALUES (?,?,?,?,0,0,?,?)`,
    [sourceId, amount, direction, date, TS, TS],
  );
}
