/**
 * Minimal async SQL executor abstraction so the same migration / query code runs
 * against both `@tauri-apps/plugin-sql` (in the app) and `better-sqlite3` (in
 * tests) without leaking either driver into the domain layer.
 */
export interface SqlExecutor {
  /** Run a statement that returns no rows (DDL, INSERT/UPDATE/DELETE, PRAGMA set). */
  execute(sql: string, params?: unknown[]): Promise<void>;
  /** Run a query and return all rows. */
  select<T = Record<string, unknown>>(sql: string, params?: unknown[]): Promise<T[]>;
}
