import { describe, it, expect } from "vitest";
import { addMovement, makeMemDb } from "@/test/sqlite";
import type { SqlExecutor } from "../types";
import { DomainError } from "../errors";
import * as repo from "./sources";

const TS = "2026-01-01T00:00:00";

async function addGoal(db: SqlExecutor, sourceId: number, status = "active") {
  await db.execute(
    `INSERT INTO goals (name,target_amount,currency,source_id,status,created_at,updated_at)
     VALUES ('G',100,'EUR',?,?,?,?)`,
    [sourceId, status, TS, TS],
  );
}
async function addPortfolio(db: SqlExecutor, sourceId: number) {
  await db.execute(
    `INSERT INTO portfolios (name,kind,base_currency,source_id,created_at,updated_at)
     VALUES ('P','mixed','EUR',?,?,?)`,
    [sourceId, TS, TS],
  );
}

describe("sources repo", () => {
  it("creates a source, uppercasing currency; no yield => null schedule", async () => {
    const { db } = await makeMemDb();
    const s = await repo.createSource(db, { name: "Cash", currency: "eur", starting_balance: 10 });
    expect(s.currency).toBe("EUR");
    expect(s.is_savings_fund).toBe(0);
    expect(s.yield_next_date).toBeNull();
    expect(s.starting_balance).toBe(10);
  });

  it("sets the yield schedule on create when rate > 0", async () => {
    const { db } = await makeMemDb();
    const s = await repo.createSource(
      db,
      { name: "Term deposit", currency: "EUR", yield_rate: 5, yield_period_months: 6 },
      "2026-01-10",
    );
    expect(s.yield_next_date).toBe("2026-07-10");
  });

  it("derives balance = starting + Σin − Σout (per-source and batch agree)", async () => {
    const { db } = await makeMemDb();
    const s = await repo.createSource(db, { name: "A", currency: "EUR", starting_balance: 100 });
    await addMovement(db, s.id, "in", 50);
    await addMovement(db, s.id, "out", 30.5);
    const empty = await repo.createSource(db, { name: "B", currency: "EUR", starting_balance: 7.25 });

    expect(await repo.getBalance(db, s.id)).toBe(119.5);
    expect(await repo.getBalance(db, empty.id)).toBe(7.25); // zero-movement fallback
    const batch = await repo.getBalancesBatch(db);
    expect(batch.get(s.id)).toBe(119.5);
    expect(batch.get(empty.id)).toBe(7.25);
  });

  it("resyncs yield only when rate/period change (§17)", async () => {
    const { db } = await makeMemDb();
    const s = await repo.createSource(
      db,
      { name: "TD", currency: "EUR", yield_rate: 5, yield_period_months: 6 },
      "2026-01-10",
    );
    expect(s.yield_next_date).toBe("2026-07-10");

    const renamed = await repo.updateSource(db, s.id, { name: "Renamed" }, "2026-03-01");
    expect(renamed.yield_next_date).toBe("2026-07-10"); // unchanged

    const rerated = await repo.updateSource(db, s.id, { yield_period_months: 12 }, "2026-03-01");
    expect(rerated.yield_next_date).toBe("2027-03-01"); // re-anchored: last is null → today + 12mo
  });

  it("ensures exactly one fund per currency", async () => {
    const { db } = await makeMemDb();
    const a = await repo.ensureFundForCurrency(db, "eur");
    const b = await repo.ensureFundForCurrency(db, "EUR");
    const usd = await repo.ensureFundForCurrency(db, "USD");
    expect(a.id).toBe(b.id);
    expect(a.is_savings_fund).toBe(1);
    expect(usd.id).not.toBe(a.id);
    const funds = (await repo.listSources(db)).filter((s) => s.is_savings_fund === 1);
    expect(funds.length).toBe(2);
  });

  it("toggles fund visibility; rejects non-funds", async () => {
    const { db } = await makeMemDb();
    const reg = await repo.createSource(db, { name: "Cash", currency: "EUR" });
    await expect(repo.setFundVisibility(db, reg.id, true)).rejects.toMatchObject({ code: "not_a_fund" });
    const fund = await repo.ensureFundForCurrency(db, "EUR");
    await repo.setFundVisibility(db, fund.id, true);
    expect((await repo.getSource(db, fund.id))!.hidden_from_sources).toBe(1);
  });

  it("merges same-currency sources; rejects funds and cross-currency", async () => {
    const { db } = await makeMemDb();
    const eur = await repo.createSource(db, { name: "A", currency: "EUR", starting_balance: 100 });
    const eur2 = await repo.createSource(db, { name: "B", currency: "EUR", starting_balance: 25 });
    const usd = await repo.createSource(db, { name: "C", currency: "USD" });
    const fund = await repo.ensureFundForCurrency(db, "EUR");
    await addMovement(db, eur.id, "in", 40);

    await expect(repo.mergeSources(db, eur.id, usd.id)).rejects.toMatchObject({ code: "cross_currency" });
    await expect(repo.mergeSources(db, fund.id, eur.id)).rejects.toMatchObject({ code: "fund_not_mergeable" });

    await repo.mergeSources(db, eur.id, eur2.id);
    expect(await repo.getSource(db, eur.id)).toBeNull();
    expect((await repo.getSource(db, eur2.id))!.starting_balance).toBe(125);
    expect(await repo.getBalance(db, eur2.id)).toBe(165); // 125 + moved 40-in movement
  });

  it("blocks delete when an active goal references the source", async () => {
    const { db } = await makeMemDb();
    const s = await repo.createSource(db, { name: "A", currency: "EUR" });
    await addGoal(db, s.id, "active");
    await expect(repo.deleteSource(db, s.id, { kind: "delete_all" })).rejects.toMatchObject({
      code: "active_goal_blocks_delete",
    });
  });

  it("rejects cross-currency move and make_external with portfolios", async () => {
    const { db } = await makeMemDb();
    const eur = await repo.createSource(db, { name: "A", currency: "EUR" });
    const usd = await repo.createSource(db, { name: "B", currency: "USD" });
    await expect(
      repo.deleteSource(db, eur.id, { kind: "move_to", targetId: usd.id }),
    ).rejects.toMatchObject({ code: "cross_currency" });

    const withPort = await repo.createSource(db, { name: "Inv", currency: "EUR" });
    await addPortfolio(db, withPort.id);
    await expect(
      repo.deleteSource(db, withPort.id, { kind: "make_external" }),
    ).rejects.toMatchObject({ code: "has_portfolios" });
  });

  it("delete_all purges the source's movements", async () => {
    const { db } = await makeMemDb();
    const s = await repo.createSource(db, { name: "A", currency: "EUR" });
    await addMovement(db, s.id, "in", 10);
    await addMovement(db, s.id, "out", 4);
    await repo.deleteSource(db, s.id, { kind: "delete_all" });
    expect(await repo.getSource(db, s.id)).toBeNull();
    const left = await db.select<{ c: number }>(`SELECT COUNT(*) c FROM movements WHERE source_id = ?`, [s.id]);
    expect(left[0].c).toBe(0);
  });

  it("move_to reassigns movements and folds starting_balance", async () => {
    const { db } = await makeMemDb();
    const a = await repo.createSource(db, { name: "A", currency: "EUR", starting_balance: 50 });
    const b = await repo.createSource(db, { name: "B", currency: "EUR", starting_balance: 20 });
    await addMovement(db, a.id, "in", 10);
    await repo.deleteSource(db, a.id, { kind: "move_to", targetId: b.id });
    expect(await repo.getSource(db, a.id)).toBeNull();
    expect(await repo.getBalance(db, b.id)).toBe(80); // 50+20 starting + 10-in
  });
});

// Ensure DomainError is the thrown type (not a generic Error).
describe("DomainError", () => {
  it("carries a code", () => {
    expect(new DomainError("not_found").code).toBe("not_found");
  });
});
