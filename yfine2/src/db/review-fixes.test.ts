/** Regression tests for the defects the adversarial review confirmed + fixed. */
import { describe, it, expect } from "vitest";
import { makeMemDb } from "@/test/sqlite";
import { createSource, getBalance } from "./repo/sources";
import { createSaving } from "./repo/savings";
import { parseCsv } from "./importers/csv";
import { exportAll, importAll } from "./backup";
import { formatMoney } from "@/lib/format";

describe("review fixes", () => {
  it("createSaving rejects non-positive amounts (MED #6)", async () => {
    const { db } = await makeMemDb();
    const s = await createSource(db, { name: "A", currency: "EUR", starting_balance: 100 });
    await expect(createSaving(db, { fromSourceId: s.id, amount: 0, date: "2026-05-01" })).rejects.toMatchObject({ code: "invalid_amount" });
    await expect(createSaving(db, { fromSourceId: s.id, amount: -5, date: "2026-05-01" })).rejects.toMatchObject({ code: "invalid_amount" });
  });

  it("CSV sub-cent rows that round to 0 are skipped, not emitted (MED #7)", () => {
    const csv = "Date,Amount,Description\n2026-05-01,0.004,tiny\n2026-05-02,10,real\n";
    const r = parseCsv(csv);
    expect(r.movements.length).toBe(1); // the 0.004 row dropped
    expect(r.movements[0].amount).toBe(10);
    expect(r.warnings.some((w) => w.endsWith("_zero_or_invalid"))).toBe(true);
  });

  it("formatMoney keeps crypto precision instead of truncating to 2dp (MED #9)", () => {
    expect(formatMoney(0.12345678, "BTC", "en")).toContain("0.12345678");
    expect(formatMoney(1.5, "ETH", "en")).toContain("ETH");
    // fiat still uses currency formatting
    expect(formatMoney(10, "EUR", "en")).toMatch(/10/);
  });

  it("importAll restores transfers without relying on defer_foreign_keys, and is recoverable (HIGH #1)", async () => {
    const src = await makeMemDb();
    const a = await createSource(src.db, { name: "A", currency: "EUR", starting_balance: 1000 });
    const b = await createSource(src.db, { name: "B", currency: "EUR" });
    const { createTransfer } = await import("./repo/movements");
    await createTransfer(src.db, { fromSourceId: a.id, toSourceId: b.id, amount: 300, date: "2026-05-01" });
    const data = await exportAll(src.db);

    const dst = await makeMemDb();
    await importAll(dst.db, data); // movements inserted NULL-then-UPDATE; no FK error
    const paired = await dst.db.select<{ c: number }>(`SELECT COUNT(*) c FROM movements WHERE transfer_pair_id IS NOT NULL`);
    expect(paired[0].c).toBe(2);
    // balances reconstructed
    const dstSources = await dst.db.select<{ id: number; name: string }>(`SELECT id,name FROM sources`);
    const aId = dstSources.find((s) => s.name === "A")!.id;
    expect(await getBalance(dst.db, aId)).toBe(700);
  });
});
