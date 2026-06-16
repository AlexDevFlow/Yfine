import { describe, it, expect } from "vitest";
import { makeMemDb } from "@/test/sqlite";
import * as sources from "./sources";
import { createBudget } from "./budgets";
import { createTag, deleteTag, listTagsWithUsage, mergeTags, updateTag } from "./tags";

describe("tags CRUD", () => {
  it("creates, normalizes color, and lists with usage counts", async () => {
    const { db } = await makeMemDb();
    const id = await createTag(db, { name: "Food", color: "#10B981" });
    const rows = await listTagsWithUsage(db);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ id, name: "Food", color: "#10b981", movement_count: 0, budget_count: 0 });
  });

  it("rejects blank names, duplicate names (case-insensitive), and bad colors", async () => {
    const { db } = await makeMemDb();
    await createTag(db, { name: "Travel" });
    await expect(createTag(db, { name: "  " })).rejects.toMatchObject({ code: "tag_name_required" });
    await expect(createTag(db, { name: "travel" })).rejects.toMatchObject({ code: "duplicate_tag" });
    await expect(createTag(db, { name: "X", color: "blue" })).rejects.toMatchObject({ code: "invalid_color" });
  });

  it("renames and recolors; clearing color sets NULL", async () => {
    const { db } = await makeMemDb();
    const id = await createTag(db, { name: "Old", color: "#ef4444" });
    await updateTag(db, id, { name: "New", color: null });
    const row = (await listTagsWithUsage(db))[0];
    expect(row).toMatchObject({ name: "New", color: null });
  });

  it("counts movements and budgets; delete cascades links and drops budgets", async () => {
    const { db } = await makeMemDb();
    const acct = await sources.createSource(db, { name: "Checking", currency: "EUR", starting_balance: 100 });
    const tagId = await createTag(db, { name: "Bills" });
    // two tagged movements
    for (let i = 0; i < 2; i++) {
      const m = await db.select<{ id: number }>(
        `INSERT INTO movements (source_id,amount,direction,date,note,exclude_from_stats,is_savings_contribution,created_at,updated_at)
         VALUES (?,?, 'out','2026-02-0${i + 1}',NULL,0,0,'t','t') RETURNING id`,
        [acct.id, 5],
      );
      await db.execute(`INSERT INTO movement_tag (movement_id,tag_id) VALUES (?,?)`, [m[0].id, tagId]);
    }
    await createBudget(db, { tag_id: tagId, amount: 50, currency: "EUR" });

    const before = (await listTagsWithUsage(db))[0];
    expect(before).toMatchObject({ movement_count: 2, budget_count: 1 });

    await deleteTag(db, tagId);
    expect(await listTagsWithUsage(db)).toHaveLength(0);
    expect((await db.select<{ c: number }>(`SELECT COUNT(*) c FROM movement_tag`))[0].c).toBe(0);
    expect((await db.select<{ c: number }>(`SELECT COUNT(*) c FROM budgets`))[0].c).toBe(0);
    // the movements themselves survive — only the links are gone
    expect((await db.select<{ c: number }>(`SELECT COUNT(*) c FROM movements`))[0].c).toBe(2);
  });

  it("merge re-points movements onto the target tag, deduping, then deletes the source", async () => {
    const { db } = await makeMemDb();
    const acct = await sources.createSource(db, { name: "Checking", currency: "EUR", starting_balance: 100 });
    const a = await createTag(db, { name: "Groceries" });
    const b = await createTag(db, { name: "Food" });
    // m1 has only A; m2 has both A and B (the merge must not create a duplicate link)
    const mk = async () => {
      const r = await db.select<{ id: number }>(
        `INSERT INTO movements (source_id,amount,direction,date,exclude_from_stats,is_savings_contribution,created_at,updated_at)
         VALUES (?,?, 'out','2026-02-01',0,0,'t','t') RETURNING id`, [acct.id, 5]);
      return r[0].id;
    };
    const m1 = await mk();
    const m2 = await mk();
    await db.execute(`INSERT INTO movement_tag (movement_id,tag_id) VALUES (?,?)`, [m1, a]);
    await db.execute(`INSERT INTO movement_tag (movement_id,tag_id) VALUES (?,?)`, [m2, a]);
    await db.execute(`INSERT INTO movement_tag (movement_id,tag_id) VALUES (?,?)`, [m2, b]);

    await mergeTags(db, a, b); // merge Groceries into Food

    const remaining = await listTagsWithUsage(db);
    expect(remaining.map((t) => t.name)).toEqual(["Food"]);
    expect(remaining[0].movement_count).toBe(2); // both movements now on Food, no dupes
    expect((await db.select<{ c: number }>(`SELECT COUNT(*) c FROM movement_tag WHERE tag_id = ?`, [a]))[0].c).toBe(0);
  });
});
