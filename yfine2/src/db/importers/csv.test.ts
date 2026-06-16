import { describe, it, expect } from "vitest";
import { makeMemDb } from "@/test/sqlite";
import { createSource, getBalance } from "../repo/sources";
import { parseAmount, tryParseDate, parseCsv, detectPreset, extractHeaders, previewCsv, commitCsv, type ParsedMovement } from "./csv";

describe("csv heuristics", () => {
  it("parses amounts with separators and currency tokens", () => {
    expect(parseAmount("1,234.56", ".")).toBe(1234.56);
    expect(parseAmount("1.234,56", ",")).toBe(1234.56);
    expect(parseAmount("€ 42,10", ",")).toBe(42.1);
    expect(parseAmount("-9.99", ".")).toBe(-9.99);
    expect(parseAmount("", ".")).toBeNull();
  });
  it("parses dates with formats and day-first fallback", () => {
    expect(tryParseDate("2026-05-10")).toBe("2026-05-10");
    expect(tryParseDate("10/05/2026")).toBe("2026-05-10"); // d/m/y fallback
    expect(tryParseDate("05/10/2026", "%m/%d/%Y")).toBe("2026-05-10");
    expect(tryParseDate("2026-05-10 14:30:00", "%Y-%m-%d %H:%M:%S")).toBe("2026-05-10");
    expect(tryParseDate("nonsense")).toBeNull();
  });
});

describe("csv parse + presets", () => {
  it("auto-guesses columns and signs amounts", () => {
    const csv = "Date,Amount,Description\n2026-05-01,-42.10,Groceries\n2026-05-02,2000,Salary\n";
    const r = parseCsv(csv);
    expect(r.movements.length).toBe(2);
    expect(r.movements[0]).toMatchObject({ date: "2026-05-01", amount: 42.1, direction: "out", note: "Groceries" });
    expect(r.movements[1]).toMatchObject({ amount: 2000, direction: "in" });
  });

  it("detects the Revolut preset and applies its mapping", () => {
    const csv = "Type,Started Date,Completed Date,Description,Amount,Currency,State\nCARD,2026-05-01 10:00:00,2026-05-01 12:00:00,Coffee,-3.50,EUR,COMPLETED\n";
    const headers = extractHeaders(csv);
    const preset = detectPreset(csv, headers);
    expect(preset?.id).toBe("revolut");
    const r = parseCsv(csv, preset!.options);
    expect(r.movements[0]).toMatchObject({ date: "2026-05-01", amount: 3.5, direction: "out", note: "Coffee", currency: "EUR" });
  });

  it("returns needs_mapping when columns can't be guessed", () => {
    const r = parseCsv("foo,bar\n1,2\n");
    expect(r.needsMapping).toBe(true);
  });
});

describe("csv preview + commit", () => {
  const movements: ParsedMovement[] = [
    { date: "2026-05-01", amount: 42.1, direction: "out", note: "Groceries", currency: "EUR" },
    { date: "2026-05-02", amount: 2000, direction: "in", note: "Salary", currency: "EUR" },
  ];

  it("commits rows, then re-dedupes on a second import (BUG-1 fix)", async () => {
    const { db } = await makeMemDb();
    const s = await createSource(db, { name: "Bank", currency: "EUR", starting_balance: 0 });
    const r1 = await commitCsv(db, { movements, sourceId: s.id });
    expect(r1.imported).toBe(2);
    expect(await getBalance(db, s.id)).toBe(1957.9); // 2000 - 42.10
    // importing the same file again imports nothing (dedupe at commit)
    const r2 = await commitCsv(db, { movements, sourceId: s.id });
    expect(r2.imported).toBe(0);
    expect(r2.skipped).toBe(2);
  });

  it("warns on a currency mismatch with the target account (BUG-2 fix)", async () => {
    const { db } = await makeMemDb();
    const usd = await createSource(db, { name: "USD acct", currency: "USD", starting_balance: 0 });
    const r = await commitCsv(db, { movements, sourceId: usd.id });
    expect(r.currencyWarning).toContain("EUR");
    expect(r.imported).toBe(2); // still imported verbatim
  });

  it("preview flags duplicates against an existing source", async () => {
    const { db } = await makeMemDb();
    const s = await createSource(db, { name: "Bank", currency: "EUR" });
    await commitCsv(db, { movements: [movements[0]], sourceId: s.id });
    const csv = "Date,Amount,Description\n2026-05-01,-42.10,Groceries\n2026-05-02,2000,Salary\n";
    const preview = await previewCsv(db, csv, { sourceId: s.id });
    expect(preview.duplicateCount).toBe(1); // the groceries row already exists
    expect(preview.rows.find((r) => r.note === "Groceries")?.isDuplicate).toBe(true);
  });
});
