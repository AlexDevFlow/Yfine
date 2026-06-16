/**
 * Browser-preview executor backed by sql.js (WASM SQLite, in-memory). Lets
 * `pnpm dev` run the full app in a browser without the Tauri runtime. Not used
 * in the packaged app — that uses the native plugin-sql executor.
 */
import initSqlJs, { type Database as SqlJsDatabase } from "sql.js";
import wasmUrl from "sql.js/dist/sql-wasm.wasm?url";
import type { SqlExecutor } from "./types";

let sqlPromise: ReturnType<typeof initSqlJs> | null = null;

export async function createSqlJsExecutor(): Promise<{
  exec: SqlExecutor;
  raw: SqlJsDatabase;
}> {
  if (!sqlPromise) sqlPromise = initSqlJs({ locateFile: () => wasmUrl });
  const SQL = await sqlPromise;
  const raw = new SQL.Database();
  const exec: SqlExecutor = {
    async execute(sql, params = []) {
      raw.run(sql, params as never);
    },
    async select(sql, params = []) {
      const stmt = raw.prepare(sql);
      try {
        stmt.bind(params as never);
        const out: unknown[] = [];
        while (stmt.step()) out.push(stmt.getAsObject());
        return out as never;
      } finally {
        stmt.free();
      }
    },
  };
  return { exec, raw };
}
