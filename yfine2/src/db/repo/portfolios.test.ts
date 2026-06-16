import { describe, it, expect } from "vitest";
import { makeMemDb } from "@/test/sqlite";
import { createSource } from "./sources";
import { upsertRate } from "./exchange-rates";
import * as pf from "./portfolios";

describe("holding valuation", () => {
  it("PnL is null (not 0) when cost basis is 0; computed otherwise", () => {
    const base = {
      id: 1, portfolio_id: 1, asset_class: "stock" as const, symbol: "X", display_name: null,
      currency: "EUR", last_price_at: null, manual_price: 1, note: null, created_at: "t", updated_at: "t",
    };
    const free = pf.enrichHolding({ ...base, quantity: 10, avg_cost: 0, last_price: 5 });
    expect(free.cost_basis).toBe(0);
    expect(free.market_value).toBe(50);
    expect(free.unrealized_pnl).toBeNull(); // cost unknown ≠ no profit

    const priced = pf.enrichHolding({ ...base, quantity: 10, avg_cost: 4, last_price: 5 });
    expect(priced.cost_basis).toBe(40);
    expect(priced.unrealized_pnl).toBe(10);
    expect(priced.unrealized_pnl_pct).toBe(25);

    const unpriced = pf.enrichHolding({ ...base, quantity: 10, avg_cost: 4, last_price: null });
    expect(unpriced.market_value).toBeNull();
    expect(unpriced.unrealized_pnl).toBeNull();
  });
});

describe("portfolio summary", () => {
  it("falls back to cost basis for unpriced holdings", async () => {
    const { db } = await makeMemDb();
    const s = await createSource(db, { name: "Inv", currency: "EUR" });
    const pid = await pf.createPortfolio(db, { name: "P", base_currency: "EUR", source_id: s.id });
    await pf.createHolding(db, { portfolio_id: pid, asset_class: "stock", symbol: "AAA", quantity: 10, avg_cost: 3, currency: "EUR", manual_price: true, last_price: 5 });
    await pf.createHolding(db, { portfolio_id: pid, asset_class: "stock", symbol: "BBB", quantity: 2, avg_cost: 20, currency: "EUR" }); // unpriced
    const sum = await pf.summarizePortfolio(db, pid);
    // AAA: value 50, cost 30 ; BBB unpriced → contributes cost 40
    expect(sum.total_value).toBe(90);
    expect(sum.total_cost).toBe(70);
    expect(sum.total_pnl).toBe(20); // only AAA has pnl
  });

  it("converts mixed-currency holdings to the base currency (BUG-1 fix)", async () => {
    const { db } = await makeMemDb();
    const s = await createSource(db, { name: "Inv", currency: "EUR" });
    const pid = await pf.createPortfolio(db, { name: "P", base_currency: "EUR", source_id: s.id });
    await upsertRate(db, "USD", "EUR", 0.9);
    // a USD-priced holding worth $100 → should count as €90 in an EUR portfolio
    await pf.createHolding(db, { portfolio_id: pid, asset_class: "stock", symbol: "USX", quantity: 10, avg_cost: 8, currency: "USD", manual_price: true, last_price: 10 });
    const sum = await pf.summarizePortfolio(db, pid);
    expect(sum.total_value).toBe(90); // $100 × 0.9, NOT 100
    expect(sum.total_cost).toBe(72); // $80 × 0.9
    expect(sum.has_unconverted).toBe(false);
  });

  it("flags unconverted when a rate is missing", async () => {
    const { db } = await makeMemDb();
    const s = await createSource(db, { name: "Inv", currency: "EUR" });
    const pid = await pf.createPortfolio(db, { name: "P", base_currency: "EUR", source_id: s.id });
    await pf.createHolding(db, { portfolio_id: pid, asset_class: "crypto", symbol: "BTC", quantity: 1, avg_cost: 100, currency: "GBP", manual_price: true, last_price: 200 });
    const sum = await pf.summarizePortfolio(db, pid);
    expect(sum.has_unconverted).toBe(true); // no GBP→EUR rate
  });
});

describe("snapshots", () => {
  it("writes one per (holding,date) and replaces only on price change", async () => {
    const { db } = await makeMemDb();
    const s = await createSource(db, { name: "Inv", currency: "EUR" });
    const pid = await pf.createPortfolio(db, { name: "P", source_id: s.id });
    const hid = await pf.createHolding(db, { portfolio_id: pid, asset_class: "stock", symbol: "AAA", quantity: 1, avg_cost: 1, currency: "EUR", manual_price: true, last_price: 5 });
    // create-time snapshot
    let snaps = await db.select<{ c: number }>(`SELECT COUNT(*) c FROM holding_price_snapshots WHERE holding_id = ?`, [hid]);
    expect(snaps[0].c).toBe(1);
    // update price same day → replaces in place (still 1)
    await pf.updateHolding(db, hid, { manual_price: true, last_price: 7 });
    snaps = await db.select<{ c: number }>(`SELECT COUNT(*) c FROM holding_price_snapshots WHERE holding_id = ?`, [hid]);
    expect(snaps[0].c).toBe(1);
    const price = await db.select<{ price: number }>(`SELECT price FROM holding_price_snapshots WHERE holding_id = ?`, [hid]);
    expect(price[0].price).toBe(7);
  });

  it("turning manual price off clears the price", async () => {
    const { db } = await makeMemDb();
    const s = await createSource(db, { name: "Inv", currency: "EUR" });
    const pid = await pf.createPortfolio(db, { name: "P", source_id: s.id });
    const hid = await pf.createHolding(db, { portfolio_id: pid, asset_class: "stock", symbol: "AAA", quantity: 1, avg_cost: 1, currency: "EUR", manual_price: true, last_price: 5 });
    await pf.updateHolding(db, hid, { manual_price: false });
    const h = (await pf.getHolding(db, hid))!;
    expect(h.last_price).toBeNull();
    expect(h.manual_price).toBe(0);
  });
});
