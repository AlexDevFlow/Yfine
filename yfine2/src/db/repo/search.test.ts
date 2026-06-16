import { describe, it, expect } from "vitest";
import { makeMemDb } from "@/test/sqlite";
import { createSource } from "./sources";
import { createMovement } from "./movements";
import { searchAll } from "./search";

describe("global search", () => {
  it("matches names, notes, and exact amounts across types", async () => {
    const { db } = await makeMemDb();
    const checking = await createSource(db, { name: "Checking account", currency: "EUR" });
    await createSource(db, { name: "Savings stash", currency: "EUR" });
    await db.execute(`INSERT INTO tags (name,created_at,updated_at) VALUES ('Groceries','t','t')`);
    await db.execute(`INSERT INTO goals (name,target_amount,currency,source_id,status,created_at,updated_at) VALUES ('New car',5000,'EUR',?, 'active','t','t')`, [checking.id]);
    await createMovement(db, { source_id: checking.id, amount: 42.5, direction: "out", date: "2026-05-01", note: "Weekly groceries" });

    const byName = await searchAll(db, "account");
    expect(byName.some((r) => r.type === "source" && r.label === "Checking account")).toBe(true);

    const byNote = await searchAll(db, "groceries");
    expect(byNote.some((r) => r.type === "movement")).toBe(true);
    expect(byNote.some((r) => r.type === "tag" && r.label === "Groceries")).toBe(true);

    const byAmount = await searchAll(db, "42.5");
    expect(byAmount.some((r) => r.type === "movement")).toBe(true);

    const goal = await searchAll(db, "car");
    expect(goal.some((r) => r.type === "goal" && r.label === "New car")).toBe(true);
  });

  it("ignores queries shorter than 2 chars and escapes wildcards", async () => {
    const { db } = await makeMemDb();
    await createSource(db, { name: "100%_real", currency: "EUR" });
    await createSource(db, { name: "other", currency: "EUR" });
    expect(await searchAll(db, "a")).toEqual([]);
    const res = await searchAll(db, "100%_real");
    expect(res.filter((r) => r.type === "source").length).toBe(1); // % and _ treated literally
  });
});
