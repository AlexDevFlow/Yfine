import { describe, it, expect } from "vitest";
import { makeMemDb } from "@/test/sqlite";
import { createSource } from "./repo/sources";
import { createMovement, createTransfer } from "./repo/movements";
import { exportAll, importAll, exportArchive, exportJson, importFile } from "./backup";
import type { SqlExecutor } from "./types";

async function seed(db: SqlExecutor) {
  const a = await createSource(db, { name: "Checking", currency: "EUR", starting_balance: 1000 });
  const b = await createSource(db, { name: "Savings", currency: "EUR", starting_balance: 0 });
  await db.execute(`INSERT INTO tags (name,color,created_at,updated_at) VALUES ('Food','#fff','t','t')`);
  await createMovement(db, { source_id: a.id, amount: 42, direction: "out", date: "2026-05-01", note: "x", tagIds: [1] });
  await createTransfer(db, { fromSourceId: a.id, toSourceId: b.id, amount: 100, date: "2026-05-02" }); // self-cyclic FK
  return { a, b };
}
const count = async (db: SqlExecutor, t: string) =>
  (await db.select<{ c: number }>(`SELECT COUNT(*) c FROM ${t}`))[0].c;

describe("backup round-trip", () => {
  it("exports all core tables and re-imports into a fresh DB (transfers included)", async () => {
    const src = await makeMemDb();
    await seed(src.db);
    const data = await exportAll(src.db);

    const dst = await makeMemDb();
    await importAll(dst.db, data);

    expect(await count(dst.db, "sources")).toBe(2); // Checking + Savings
    expect(await count(dst.db, "movements")).toBe(3); // 1 plain + 2 transfer legs
    expect(await count(dst.db, "movement_tag")).toBe(1);
    // transfer pair links survive (defer_foreign_keys made the cyclic insert possible)
    const paired = await dst.db.select<{ c: number }>(`SELECT COUNT(*) c FROM movements WHERE transfer_pair_id IS NOT NULL`);
    expect(paired[0].c).toBe(2);
  });

  it(".yfine archive round-trips through importFile", async () => {
    const src = await makeMemDb();
    await seed(src.db);
    const zip = await exportArchive(src.db, "2026-05-29T00:00:00Z");
    expect(zip[0]).toBe(0x50); // 'P' — it's a real ZIP

    const dst = await makeMemDb();
    await importFile(dst.db, zip);
    expect(await count(dst.db, "movements")).toBe(3);
    expect(await count(dst.db, "sources")).toBe(2);
  });

  it("legacy JSON backup imports via importFile", async () => {
    const src = await makeMemDb();
    await seed(src.db);
    const json = await exportJson(src.db);
    const dst = await makeMemDb();
    await importFile(dst.db, new TextEncoder().encode(json));
    expect(await count(dst.db, "movements")).toBe(3);
  });

  it("rejects a zip without the yfine format marker", async () => {
    const dst = await makeMemDb();
    // a zip-looking byte sequence that isn't a real archive
    const fake = new Uint8Array([0x50, 0x4b, 0x03, 0x04, 0, 0, 0, 0]);
    await expect(importFile(dst.db, fake)).rejects.toBeTruthy();
  });

  it("preserves unknown/plugin tables when present in both DBs", async () => {
    const src = await makeMemDb();
    await seed(src.db);
    await src.db.execute(`CREATE TABLE seller_items (id INTEGER PRIMARY KEY, name TEXT)`);
    await src.db.execute(`INSERT INTO seller_items (name) VALUES ('widget')`);
    const data = await exportAll(src.db);
    expect((data._plugin_tables as Record<string, unknown[]>).seller_items.length).toBe(1);

    const dst = await makeMemDb();
    await dst.db.execute(`CREATE TABLE seller_items (id INTEGER PRIMARY KEY, name TEXT)`);
    await importAll(dst.db, data);
    expect(await count(dst.db, "seller_items")).toBe(1);
  });
});
