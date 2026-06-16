import { describe, it, expect } from "vitest";
import { makeMemDb } from "@/test/sqlite";
import type { SqlExecutor } from "../types";
import { createSource, getBalance } from "./sources";
import { createRecurring } from "./recurring";
import { upsertRate } from "./exchange-rates";
import { createSplit, splitTotal } from "./splits";
import { forecastCashflow } from "./forecast";
import { consolidatedNetWorth } from "./consolidate";

async function tag(db: SqlExecutor, name: string) {
  return (await db.select<{ id: number }>(`INSERT INTO tags (name,created_at,updated_at) VALUES (?,?,?) RETURNING id`, [name, "t", "t"]))[0].id;
}

describe("split transactions", () => {
  it("creates one categorized movement per line, summing to the total", async () => {
    const { db } = await makeMemDb();
    const s = await createSource(db, { name: "Card", currency: "EUR", starting_balance: 500 });
    const food = await tag(db, "Food");
    const home = await tag(db, "Home");
    const lines = [{ amount: 60, tagId: food }, { amount: 30, tagId: home }, { amount: 10 }];
    expect(splitTotal(lines)).toBe(100);

    const ids = await createSplit(db, { source_id: s.id, direction: "out", date: "2026-05-01", note: "Supermarket", lines });
    expect(ids.length).toBe(3);
    expect(await getBalance(db, s.id)).toBe(400); // 500 − 100

    // each portion is a real tagged movement
    const tagged = await db.select<{ c: number }>(`SELECT COUNT(*) c FROM movement_tag WHERE tag_id = ?`, [food]);
    expect(tagged[0].c).toBe(1);
    const notes = await db.select<{ note: string }>(`SELECT note FROM movements WHERE source_id = ?`, [s.id]);
    expect(notes.every((n) => n.note === "Supermarket")).toBe(true);
  });
});

describe("cashflow forecast", () => {
  it("projects recurring items forward and flags when a balance goes negative", async () => {
    const { db } = await makeMemDb();
    const s = await createSource(db, { name: "Checking", currency: "EUR", starting_balance: 100 });
    await createRecurring(db, { name: "Rent", amount: 50, direction: "out", currency: "EUR", frequency: "monthly", start_date: "2026-06-02", source_id: s.id });

    const fc = await forecastCashflow(db, 90, "2026-06-02");
    const eur = fc.find((f) => f.currency === "EUR")!;
    expect(eur.start).toBe(100);
    // 3 monthly hits within 90 days: 100 → 50 → 0 → -50
    expect(eur.end).toBe(-50);
    expect(eur.lowest).toBe(-50);
    expect(eur.negativeFrom).toBe("2026-08-02");
  });

  it("stays flat with no recurring items", async () => {
    const { db } = await makeMemDb();
    await createSource(db, { name: "Checking", currency: "EUR", starting_balance: 250 });
    const fc = await forecastCashflow(db, 30, "2026-06-02");
    expect(fc[0].end).toBe(250);
    expect(fc[0].negativeFrom).toBeNull();
  });
});

describe("consolidated net worth", () => {
  it("converts every currency into the base and sums", async () => {
    const { db } = await makeMemDb();
    await createSource(db, { name: "EUR", currency: "EUR", starting_balance: 100 });
    await createSource(db, { name: "USD", currency: "USD", starting_balance: 50 });
    await upsertRate(db, "USD", "EUR", 0.9);
    const c = await consolidatedNetWorth(db, "EUR");
    expect(c.total).toBe(145); // 100 + 50*0.9
    expect(c.missing).toEqual([]);
  });

  it("flags currencies without a rate instead of mixing them in", async () => {
    const { db } = await makeMemDb();
    await createSource(db, { name: "EUR", currency: "EUR", starting_balance: 100 });
    await createSource(db, { name: "GBP", currency: "GBP", starting_balance: 50 });
    const c = await consolidatedNetWorth(db, "EUR");
    expect(c.total).toBe(100);
    expect(c.missing).toEqual(["GBP"]);
  });
});
