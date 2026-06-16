/**
 * Drift-tolerant schema migration for Yfine.
 *
 * The legacy Python app's schema drifted over time (create_all builds the full
 * current schema, while migrations only ADD columns; some user DBs are older or
 * come from a divergent lineage with extra tables like `net_worth_snapshots`).
 * To open ANY real `yfine.db` unchanged, this runner is purely ADDITIVE:
 *
 *   1. PRAGMA foreign_keys=ON  (the legacy app enforces FK on every connection,
 *      so all ON DELETE CASCADE/SET NULL/RESTRICT semantics are live).
 *   2. Create any missing CORE table/index (schema.sql is all IF NOT EXISTS).
 *   3. Auto-heal: for every core table that exists, ADD COLUMN any expected
 *      column it's missing (older DBs), backfilling existing rows with the
 *      curated heal-default. Re-assert expected indexes.
 *   4. Stamp alembic_version with the head only when empty (schema.sql).
 *
 * It NEVER drops or alters existing tables/columns, so plugin tables
 * (`seller_items`) and divergent tables (`net_worth_snapshots`) are preserved.
 */
import type { SqlExecutor } from "./types";
import expectedSchema from "../../db/expected-schema.json";
import schemaSql from "../../db/schema.sql?raw";

interface ExpectedColumn {
  name: string;
  type: string;
  notnull: boolean;
  pk: number;
  heal_default: string | null;
}
interface ExpectedIndex {
  name: string;
  unique: boolean;
  origin: string;
  columns: string[];
  sql: string | null;
}
interface ExpectedTable {
  columns: ExpectedColumn[];
  indexes: ExpectedIndex[];
}

const EXPECTED = expectedSchema as {
  head: string;
  tables: Record<string, ExpectedTable>;
};

export const SCHEMA_HEAD = EXPECTED.head;

/** Split a multi-statement SQL script into individual executable statements. */
export function splitStatements(sql: string): string[] {
  const noComments = sql
    .split("\n")
    .filter((line) => !line.trim().startsWith("--"))
    .join("\n");
  return noComments
    .split(";")
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

function withIfNotExists(indexSql: string): string {
  return indexSql
    .replace(/^CREATE INDEX /i, "CREATE INDEX IF NOT EXISTS ")
    .replace(/^CREATE UNIQUE INDEX /i, "CREATE UNIQUE INDEX IF NOT EXISTS ");
}

/** Run the additive migration. Safe to run repeatedly (idempotent). */
export async function migrate(db: SqlExecutor): Promise<void> {
  await db.execute("PRAGMA foreign_keys=ON");

  // 1 + 2: create any missing core tables / indexes / version stamp.
  for (const stmt of splitStatements(schemaSql)) {
    // PRAGMA already issued above; skip the duplicate from the file.
    if (/^PRAGMA\s+foreign_keys/i.test(stmt)) continue;
    await db.execute(stmt);
  }

  // 3: auto-heal columns + indexes on tables that already existed.
  for (const [table, def] of Object.entries(EXPECTED.tables)) {
    const info = await db.select<{ name: string }>(
      `PRAGMA table_info(${table})`,
    );
    if (info.length === 0) continue; // schema.sql should have created it
    const have = new Set(info.map((r) => r.name));

    for (const col of def.columns) {
      if (have.has(col.name)) continue;
      if (col.notnull && col.heal_default == null) {
        throw new Error(
          `cannot heal NOT NULL column ${table}.${col.name} without a default`,
        );
      }
      const parts = [`ALTER TABLE ${table} ADD COLUMN ${col.name} ${col.type}`];
      if (col.heal_default != null) parts.push(`DEFAULT ${col.heal_default}`);
      if (col.notnull) parts.push("NOT NULL");
      await db.execute(parts.join(" "));
    }

    for (const idx of def.indexes) {
      // origin 'c' = explicitly CREATEd index (has sql); 'pk'/'u' are auto.
      if (idx.origin === "c" && idx.sql) {
        await db.execute(withIfNotExists(idx.sql));
      }
    }
  }
}
