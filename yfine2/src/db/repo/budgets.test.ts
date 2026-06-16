import { describe, it, expect } from "vitest";
import { makeMemDb } from "@/test/sqlite";
import type { SqlExecutor } from "../types";
import { createSource } from "./sources";
import { createMovement, createTransfer } from "./movements";
import { addMonthsISO, monthStart, todayISO } from "@/lib/date";
import * as bud from "./budgets";

async function tag(db: SqlExecutor, name: string) {
  return (await db.select<{ id: number }>(`INSERT INTO tags (name,created_at,updated_at) VALUES (?,?,?) RETURNING id`, [name, "t", "t"]))[0].id;
}

describe("budget actuals", () => {
  it("sums tagged, same-currency, in-period, non-transfer, non-excluded movements", async () => {
    const { db } = await makeMemDb();
    const eur = await createSource(db, { name: "EUR", currency: "EUR", starting_balance: 1000 });
    const usd = await createSource(db, { name: "USD", currency: "USD", starting_balance: 1000 });
    const food = await tag(db, "Food");
    const today = todayISO();
    const inMonth = monthStart(today);

    await createMovement(db, { source_id: eur.id, amount: 30, direction: "out", date: inMonth, tagIds: [food] });
    await createMovement(db, { source_id: eur.id, amount: 12, direction: "out", date: today, tagIds: [food] });
    await createMovement(db, { source_id: usd.id, amount: 99, direction: "out", date: today, tagIds: [food] }); // wrong currency
    await createMovement(db, { source_id: eur.id, amount: 5, direction: "in", date: today, tagIds: [food] }); // wrong direction
    await createMovement(db, { source_id: null, amount: 7, direction: "out", date: today, tagIds: [food] }); // external
    await createTransfer(db, { fromSourceId: eur.id, toSourceId: usd.id, amount: 50, date: today }); // transfer

    const id = await bud.createBudget(db, { tag_id: food, amount: 100, currency: "EUR", period: "monthly" });
    const st = await bud.budgetStatus(db, (await bud.getBudget(db, id))!, today);
    expect(st.actual).toBe(42); // 30 + 12 only
    expect(st.available).toBe(100);
    expect(st.remaining).toBe(58);
    expect(st.status).toBe("ok");
  });

  it("carries signed rollover across periods", async () => {
    const { db } = await makeMemDb();
    const eur = await createSource(db, { name: "EUR", currency: "EUR", starting_balance: 10000 });
    const food = await tag(db, "Food");
    const today = todayISO();
    const m2 = addMonthsISO(monthStart(today), -2);
    const m1 = addMonthsISO(monthStart(today), -1);
    await createMovement(db, { source_id: eur.id, amount: 30, direction: "out", date: m2, tagIds: [food] });
    await createMovement(db, { source_id: eur.id, amount: 150, direction: "out", date: m1, tagIds: [food] });

    const id = await bud.createBudget(db, { tag_id: food, amount: 100, currency: "EUR", period: "monthly", rollover: true, start_date: m2 });
    const st = await bud.budgetStatus(db, (await bud.getBudget(db, id))!, today);
    // m2: 100-30=+70 ; m1: 100+70-150=-... = 20 ; current available = 100 + 20 = 120
    expect(st.rolloverIn).toBe(20);
    expect(st.available).toBe(120);
  });

  it("reports 'over' even when rollover makes available negative (BUG-1 fix)", async () => {
    const { db } = await makeMemDb();
    const eur = await createSource(db, { name: "EUR", currency: "EUR", starting_balance: 10000 });
    const food = await tag(db, "Food");
    const today = todayISO();
    const m1 = addMonthsISO(monthStart(today), -1);
    await createMovement(db, { source_id: eur.id, amount: 500, direction: "out", date: m1, tagIds: [food] }); // huge overspend
    await createMovement(db, { source_id: eur.id, amount: 50, direction: "out", date: today, tagIds: [food] });

    const id = await bud.createBudget(db, { tag_id: food, amount: 100, currency: "EUR", period: "monthly", rollover: true, start_date: m1 });
    const st = await bud.budgetStatus(db, (await bud.getBudget(db, id))!, today);
    expect(st.available).toBeLessThanOrEqual(0);
    expect(st.status).toBe("over"); // would have been "ok"/"warning" before the fix
  });

  it("rejects a duplicate active (tag,currency); allows inactive + other currency", async () => {
    const { db } = await makeMemDb();
    const food = await tag(db, "Food");
    await bud.createBudget(db, { tag_id: food, amount: 100, currency: "EUR" });
    await expect(bud.createBudget(db, { tag_id: food, amount: 50, currency: "EUR" })).rejects.toMatchObject({ code: "duplicate_budget" });
    await bud.createBudget(db, { tag_id: food, amount: 50, currency: "EUR", active: false }); // inactive ok
    await bud.createBudget(db, { tag_id: food, amount: 50, currency: "USD" }); // other currency ok
  });

  it("fires threshold then overspend alerts once each (idempotent bands)", async () => {
    const { db } = await makeMemDb();
    const eur = await createSource(db, { name: "EUR", currency: "EUR", starting_balance: 10000 });
    const food = await tag(db, "Food");
    const today = todayISO();
    await bud.createBudget(db, { tag_id: food, amount: 100, currency: "EUR", period: "monthly", alert_threshold_pct: 80 });

    await createMovement(db, { source_id: eur.id, amount: 85, direction: "out", date: today, tagIds: [food] });
    expect(await bud.checkBudgetAlerts(db, today)).toBe(1); // threshold band
    expect(await bud.checkBudgetAlerts(db, today)).toBe(0); // idempotent

    await createMovement(db, { source_id: eur.id, amount: 30, direction: "out", date: today, tagIds: [food] });
    expect(await bud.checkBudgetAlerts(db, today)).toBe(1); // overspend band
    expect(await bud.checkBudgetAlerts(db, today)).toBe(0);
  });

  it("deletes budgets for a tag", async () => {
    const { db } = await makeMemDb();
    const food = await tag(db, "Food");
    await bud.createBudget(db, { tag_id: food, amount: 100, currency: "EUR" });
    await bud.deleteBudgetsForTag(db, food);
    expect((await bud.listBudgetStatuses(db)).length).toBe(0);
  });
});
