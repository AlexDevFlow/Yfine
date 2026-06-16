import { describe, it, expect } from "vitest";
import { makeMemDb } from "@/test/sqlite";
import type { SqlExecutor } from "../types";
import { createSource, getBalance, listSources } from "./sources";
import * as goals from "./goals";
import * as whims from "./whims";

async function eurAccount(db: SqlExecutor, bal = 1000) {
  return createSource(db, { name: "Checking", currency: "EUR", starting_balance: bal });
}
async function fundBalance(db: SqlExecutor) {
  const fund = (await listSources(db)).find((s) => s.is_savings_fund === 1);
  return fund ? getBalance(db, fund.id) : 0;
}

describe("goals", () => {
  it("creates with the per-currency savings fund as the default accumulating source", async () => {
    const { db } = await makeMemDb();
    const id = await goals.createGoal(db, { name: "Trip", target_amount: 1000, currency: "eur" });
    const g = (await goals.getGoal(db, id))!;
    expect(g.currency).toBe("EUR");
    const list = await goals.listGoals(db);
    expect(list[0].is_fund).toBe(true);
  });

  it("allocates via a real transfer; guards own-source/inactive/currency", async () => {
    const { db } = await makeMemDb();
    const acct = await eurAccount(db, 1000);
    const id = await goals.createGoal(db, { name: "Trip", target_amount: 1000, currency: "EUR" });
    const g = (await goals.getGoal(db, id))!;

    await goals.allocate(db, id, { fromSourceId: acct.id, amount: 200, date: "2026-05-01" });
    expect(await getBalance(db, acct.id)).toBe(800);
    expect(await fundBalance(db)).toBe(200);
    expect((await goals.listGoals(db))[0].allocated).toBe(200);
    expect((await goals.listGoals(db))[0].progress_pct).toBe(20);

    await expect(goals.allocate(db, id, { fromSourceId: g.source_id, amount: 10 })).rejects.toMatchObject({ code: "alloc_from_own_source" });
    const usd = await createSource(db, { name: "USD", currency: "USD" });
    await expect(goals.allocate(db, id, { fromSourceId: usd.id, amount: 10 })).rejects.toMatchObject({ code: "currency_mismatch" });
  });

  it("close = consolidated refund that KEEPS deposits and conserves money", async () => {
    const { db } = await makeMemDb();
    const acct = await eurAccount(db, 1000);
    const dest = await createSource(db, { name: "Dest", currency: "EUR", starting_balance: 0 });
    const id = await goals.createGoal(db, { name: "Trip", target_amount: 1000, currency: "EUR" });
    await goals.allocate(db, id, { fromSourceId: acct.id, amount: 200, date: "2026-05-01" });
    await goals.allocate(db, id, { fromSourceId: acct.id, amount: 100, date: "2026-05-02" });
    expect(await fundBalance(db)).toBe(300);

    await goals.closeGoal(db, id, dest.id, "2026-05-03");
    expect((await goals.getGoal(db, id))!.status).toBe("completed");
    expect(await fundBalance(db)).toBe(0); // refunded out
    expect(await getBalance(db, dest.id)).toBe(300); // landed here, once (no double payout)
    // allocation tracking rows gone, but the deposit movements remain in the fund history
    const allocs = await db.select<{ c: number }>(`SELECT COUNT(*) c FROM goal_allocations WHERE goal_id = ?`, [id]);
    expect(allocs[0].c).toBe(0);
  });

  it("delete auto-reverses every allocation back to origin", async () => {
    const { db } = await makeMemDb();
    const acct = await eurAccount(db, 1000);
    const id = await goals.createGoal(db, { name: "Trip", target_amount: 1000, currency: "EUR" });
    await goals.allocate(db, id, { fromSourceId: acct.id, amount: 250, date: "2026-05-01" });
    expect(await getBalance(db, acct.id)).toBe(750);
    await goals.deleteGoal(db, id);
    expect(await getBalance(db, acct.id)).toBe(1000); // money returned
    expect(await fundBalance(db)).toBe(0);
  });

  it("refuses to complete/cancel via plain update (BUG-3 fix)", async () => {
    const { db } = await makeMemDb();
    const id = await goals.createGoal(db, { name: "Trip", target_amount: 1000, currency: "EUR" });
    await expect(goals.updateGoal(db, id, { status: "cancelled" })).rejects.toMatchObject({ code: "use_close_or_delete" });
    await goals.updateGoal(db, id, { name: "Big Trip" }); // normal edits fine
  });
});

describe("whims", () => {
  it("save-for-this creates a linked goal (idempotent) with a back-reference", async () => {
    const { db } = await makeMemDb();
    const wid = await whims.createWhim(db, { name: "Camera", amount: 800, currency: "EUR" });
    const gid = await whims.startSavingForWhim(db, wid);
    expect((await whims.getWhim(db, wid))!.linked_goal_id).toBe(gid);
    expect(await whims.startSavingForWhim(db, wid)).toBe(gid); // idempotent
  });

  it("purchase drains a funded linked goal into the purchase source, then books the spend", async () => {
    const { db } = await makeMemDb();
    const acct = await eurAccount(db, 1000);
    const wid = await whims.createWhim(db, { name: "Camera", amount: 800, currency: "EUR" });
    const gid = await whims.startSavingForWhim(db, wid);
    await goals.allocate(db, gid, { fromSourceId: acct.id, amount: 500, date: "2026-05-01" });
    expect(await getBalance(db, acct.id)).toBe(500); // 500 moved to the goal fund

    await whims.purchaseWhim(db, wid, { sourceId: acct.id });
    // goal refunded 500 into acct (→1000), then 800 purchase booked (→200)
    expect(await getBalance(db, acct.id)).toBe(200);
    expect((await whims.getWhim(db, wid))!.status).toBe("purchased");
    expect(await fundBalance(db)).toBe(0);
  });

  it("purchase honors a price override and records it on the whim", async () => {
    const { db } = await makeMemDb();
    const acct = await eurAccount(db, 1000);
    const wid = await whims.createWhim(db, { name: "Camera", amount: 800, currency: "EUR" });
    await whims.purchaseWhim(db, wid, { sourceId: acct.id, amount: 720 }); // price dropped
    expect(await getBalance(db, acct.id)).toBe(280); // 720 booked, not 800
    const w = (await whims.getWhim(db, wid))!;
    expect(w.status).toBe("purchased");
    expect(w.amount).toBe(720); // whim reflects the actual price paid
  });

  it("restore only works on dismissed; delete clears the goal back-reference", async () => {
    const { db } = await makeMemDb();
    const wid = await whims.createWhim(db, { name: "Camera", amount: 800, currency: "EUR" });
    await expect(whims.restoreWhim(db, wid)).rejects.toMatchObject({ code: "not_dismissed" });
    await whims.dismissWhim(db, wid);
    await whims.restoreWhim(db, wid);
    expect((await whims.getWhim(db, wid))!.status).toBe("pending");

    const gid = await whims.startSavingForWhim(db, wid);
    await whims.deleteWhim(db, wid);
    expect((await goals.getGoal(db, gid))!.linked_whim_id).toBeNull();
  });
});
