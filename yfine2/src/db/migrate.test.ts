import { describe, it, expect } from "vitest";
import Database from "better-sqlite3";
import { copyFileSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { migrate, SCHEMA_HEAD, splitStatements } from "./migrate";
import type { SqlExecutor } from "./types";

function wrap(db: Database.Database): SqlExecutor {
  return {
    async execute(sql, params = []) {
      db.prepare(sql).run(...(params as unknown[]));
    },
    async select(sql, params = []) {
      return db.prepare(sql).all(...(params as unknown[])) as never;
    },
  };
}

const CORE_TABLES = [
  "sources", "tags", "movements", "movement_tag", "movement_attachments",
  "recurring_items", "notifications", "settings", "whims", "savings",
  "saving_tag", "exchange_rates", "portfolios", "holdings",
  "holding_price_snapshots", "goals", "goal_allocations", "budgets",
];

function tableNames(db: Database.Database): Set<string> {
  return new Set(
    db.prepare("SELECT name FROM sqlite_master WHERE type='table'").all().map((r) => (r as { name: string }).name),
  );
}
function columnNames(db: Database.Database, t: string): Set<string> {
  return new Set(
    db.prepare(`PRAGMA table_info(${t})`).all().map((r) => (r as { name: string }).name),
  );
}

// Random-free unique temp path (Date.now/Math.random unavailable in some envs;
// the test process pid + a counter is enough for isolation).
let counter = 0;
function tmpDb(label: string): string {
  counter += 1;
  return join(tmpdir(), `yfine2_test_${process.pid}_${counter}_${label}.db`);
}

describe("schema migration", () => {
  it("splits the schema script into clean statements", () => {
    const stmts = splitStatements("-- c\nCREATE TABLE a(x);\n\nCREATE TABLE b(y);\n");
    expect(stmts).toEqual(["CREATE TABLE a(x)", "CREATE TABLE b(y)"]);
  });

  it("creates the full canonical schema on a fresh DB and stamps the head", async () => {
    const db = new Database(tmpDb("fresh"));
    await migrate(wrap(db));

    const tables = tableNames(db);
    for (const t of CORE_TABLES) expect(tables, `missing ${t}`).toContain(t);
    expect(tables).toContain("alembic_version");

    // FK enforcement on
    expect((db.pragma("foreign_keys") as { foreign_keys: number }[])[0].foreign_keys).toBe(1);

    // newest columns present
    expect(columnNames(db, "settings")).toContain("saved_views_json");
    expect(columnNames(db, "settings")).toContain("movement_templates_json");
    expect(columnNames(db, "sources")).toContain("yield_rate");

    // head stamped
    const stamp = db.prepare("SELECT version_num FROM alembic_version").get() as { version_num: string };
    expect(stamp.version_num).toBe(SCHEMA_HEAD);

    // idempotent: running again is a no-op and doesn't throw
    await migrate(wrap(db));
    db.close();
  });

  it("opens a REAL older user DB unchanged: heals missing columns, preserves data + extra tables", async () => {
    const backup = join(process.cwd(), "..", "backups", "yfine_20260522_185323.db");
    if (!existsSync(backup)) {
      // backup not present in this checkout — skip rather than fail spuriously
      console.warn("skip: real backup not found at", backup);
      return;
    }
    const copy = tmpDb("real_may22");
    copyFileSync(backup, copy);
    const db = new Database(copy);

    // capture pre-migration state
    const before = tableNames(db);
    expect(before.has("net_worth_snapshots")).toBe(true); // divergent table
    expect(before.has("seller_items")).toBe(true); // plugin table
    expect(before.has("budgets")).toBe(false); // older lineage: no budgets yet
    const srcCountBefore = (db.prepare("SELECT count(*) c FROM sources").get() as { c: number }).c;
    const movCountBefore = (db.prepare("SELECT count(*) c FROM movements").get() as { c: number }).c;
    const stampBefore = (db.prepare("SELECT version_num FROM alembic_version").get() as { version_num: string }).version_num;

    await migrate(wrap(db));

    const after = tableNames(db);
    // all core tables now present (budgets auto-created)
    for (const t of CORE_TABLES) expect(after, `missing ${t}`).toContain(t);
    // older columns auto-healed
    expect(columnNames(db, "sources")).toContain("yield_rate");
    expect(columnNames(db, "settings")).toContain("saved_views_json");
    expect(columnNames(db, "settings")).toContain("movement_templates_json");
    // unknown tables preserved untouched
    expect(after.has("net_worth_snapshots")).toBe(true);
    expect(after.has("seller_items")).toBe(true);
    // data preserved exactly
    expect((db.prepare("SELECT count(*) c FROM sources").get() as { c: number }).c).toBe(srcCountBefore);
    expect((db.prepare("SELECT count(*) c FROM movements").get() as { c: number }).c).toBe(movCountBefore);
    // existing alembic stamp is NOT overwritten (migrate only stamps when empty)
    expect((db.prepare("SELECT version_num FROM alembic_version").get() as { version_num: string }).version_num).toBe(stampBefore);
    // healed-in settings columns are usable: read the singleton row's new column
    const s = db.prepare("SELECT saved_views_json FROM settings WHERE id=1").get() as { saved_views_json: string } | undefined;
    if (s) expect(s.saved_views_json).toBe("[]");

    db.close();
  });
});
