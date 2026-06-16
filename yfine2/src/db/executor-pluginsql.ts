/** Native SQLite executor backed by @tauri-apps/plugin-sql (the real app DB). */
import Database from "@tauri-apps/plugin-sql";
import type { SqlExecutor } from "./types";

export async function createPluginSqlExecutor(
  path = "sqlite:yfine.db",
): Promise<{ exec: SqlExecutor; db: Database }> {
  const db = await Database.load(path);
  const exec: SqlExecutor = {
    async execute(sql, params = []) {
      await db.execute(sql, params as unknown[]);
    },
    async select(sql, params = []) {
      return (await db.select(sql, params as unknown[])) as never;
    },
  };
  return { exec, db };
}
