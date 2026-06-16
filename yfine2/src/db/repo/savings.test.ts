import { describe, it, expect } from "vitest";
import { makeMemDb } from "@/test/sqlite";
import { netWorthByCurrency } from "@/domain/money";
import * as sources from "./sources";
import { createSaving, deleteSaving, listSavings } from "./savings";

async function netWorthEUR(db: Parameters<typeof sources.getBalancesBatch>[0]) {
  const all = await sources.listSources(db);
  const balances = await sources.getBalancesBatch(db);
  return netWorthByCurrency(
    all.map((s) => ({ currency: s.currency, balance: balances.get(s.id) ?? 0 })),
  )["EUR"];
}

describe("savings deposit (transfer-backed, conserving)", () => {
  it("moves money source→fund, conserving net worth; flags the in-leg; tags both legs", async () => {
    const { db } = await makeMemDb();
    const acct = await sources.createSource(db, { name: "Checking", currency: "EUR", starting_balance: 1000 });
    await db.execute(`INSERT INTO tags (name,created_at,updated_at) VALUES ('Goal','t','t')`);

    const before = await netWorthEUR(db);
    const savingId = await createSaving(db, {
      fromSourceId: acct.id,
      amount: 300,
      date: "2026-05-01",
      note: "monthly",
      tagIds: [1],
    });
    const after = await netWorthEUR(db);

    expect(after).toBe(before); // conservation
    expect(await sources.getBalance(db, acct.id)).toBe(700);

    const fund = (await sources.listSources(db)).find((s) => s.is_savings_fund === 1)!;
    expect(fund.currency).toBe("EUR");
    expect(await sources.getBalance(db, fund.id)).toBe(300);

    // in-leg flagged + both legs linked + tags on both
    const inLeg = (await db.select<{ id: number; is_savings_contribution: number; transfer_pair_id: number }>(
      `SELECT id,is_savings_contribution,transfer_pair_id FROM movements WHERE id = ?`,
      [savingId],
    ))[0];
    expect(inLeg.is_savings_contribution).toBe(1);
    const tagCount = (await db.select<{ c: number }>(
      `SELECT COUNT(*) c FROM movement_tag WHERE tag_id = 1`,
    ))[0].c;
    expect(tagCount).toBe(2); // both legs tagged
  });

  it("lists deposits newest-first with currency, source, and tags", async () => {
    const { db } = await makeMemDb();
    const acct = await sources.createSource(db, { name: "Checking", currency: "EUR", starting_balance: 1000 });
    await db.execute(`INSERT INTO tags (name,created_at,updated_at) VALUES ('Goal','t','t')`);
    await createSaving(db, { fromSourceId: acct.id, amount: 100, date: "2026-05-01", note: "first" });
    await createSaving(db, { fromSourceId: acct.id, amount: 200, date: "2026-05-10", note: "second", tagIds: [1] });

    const list = await listSavings(db);
    expect(list.map((s) => s.amount)).toEqual([200, 100]); // newest first
    expect(list[0]).toMatchObject({ currency: "EUR", from_source_name: "Checking", note: "second" });
    expect(list[0].tags).toEqual([{ id: 1, name: "Goal", color: null }]);
    expect(list[1].tags).toEqual([]);
  });

  it("rejects saving FROM a fund", async () => {
    const { db } = await makeMemDb();
    const fund = await sources.ensureFundForCurrency(db, "EUR");
    await expect(
      createSaving(db, { fromSourceId: fund.id, amount: 10, date: "2026-05-01" }),
    ).rejects.toMatchObject({ code: "fund_save_rejected" });
  });

  it("rejects a currency that doesn't match the from-source", async () => {
    const { db } = await makeMemDb();
    const acct = await sources.createSource(db, { name: "USD acct", currency: "USD" });
    await expect(
      createSaving(db, { fromSourceId: acct.id, amount: 10, date: "2026-05-01", currency: "EUR" }),
    ).rejects.toMatchObject({ code: "currency_mismatch" });
  });

  it("deleting a saving reverses both legs (full refund)", async () => {
    const { db } = await makeMemDb();
    const acct = await sources.createSource(db, { name: "Checking", currency: "EUR", starting_balance: 1000 });
    const savingId = await createSaving(db, { fromSourceId: acct.id, amount: 250, date: "2026-05-01" });
    expect(await sources.getBalance(db, acct.id)).toBe(750);

    await deleteSaving(db, savingId);
    expect(await sources.getBalance(db, acct.id)).toBe(1000); // refunded
    const fund = (await sources.listSources(db)).find((s) => s.is_savings_fund === 1)!;
    expect(await sources.getBalance(db, fund.id)).toBe(0);
    const movCount = (await db.select<{ c: number }>(`SELECT COUNT(*) c FROM movements`))[0].c;
    expect(movCount).toBe(0); // both legs gone
  });
});
