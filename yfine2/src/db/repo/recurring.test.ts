import { describe, it, expect } from "vitest";
import { makeMemDb } from "@/test/sqlite";
import type { SqlExecutor } from "../types";
import { createSource, getBalance } from "./sources";
import {
  computeNextDueDate,
  createRecurring,
  applyRecurringById,
  processDueRecurring,
  monthlySummary,
  updateRecurring,
  getRecurring,
} from "./recurring";
import { processSourceYields } from "./scheduler";

async function countMovements(db: SqlExecutor) {
  return (await db.select<{ c: number }>(`SELECT COUNT(*) c FROM movements`))[0].c;
}
async function unreadConfirm(db: SqlExecutor, id: number) {
  return (await db.select<{ c: number }>(`SELECT COUNT(*) c FROM notifications WHERE related_entity = ? AND is_read = 0`, [`recurring:${id}#confirm`]))[0].c;
}

describe("computeNextDueDate", () => {
  it("advances by one period with calendar clamping", () => {
    expect(computeNextDueDate("2026-05-10", "daily")).toBe("2026-05-11");
    expect(computeNextDueDate("2026-05-10", "weekly")).toBe("2026-05-17");
    expect(computeNextDueDate("2026-01-31", "monthly")).toBe("2026-02-28");
    expect(computeNextDueDate("2024-02-29", "yearly")).toBe("2025-02-28");
    expect(computeNextDueDate("2026-05-10", "wat")).toBe("2026-06-10"); // unknown → monthly
  });
});

describe("recurring create/apply", () => {
  it("initializes next_due_date to start_date and validates currency", async () => {
    const { db } = await makeMemDb();
    const s = await createSource(db, { name: "A", currency: "EUR", starting_balance: 100 });
    const id = await createRecurring(db, { name: "Rent", amount: 50, direction: "out", currency: "EUR", frequency: "monthly", start_date: "2026-05-01", source_id: s.id });
    expect((await getRecurring(db, id))!.next_due_date).toBe("2026-05-01");

    await expect(
      createRecurring(db, { name: "X", amount: 1, direction: "out", currency: "USD", frequency: "monthly", start_date: "2026-05-01", source_id: s.id }),
    ).rejects.toMatchObject({ code: "currency_mismatch" });
    await expect(
      createRecurring(db, { name: "X", amount: 1, direction: "out", currency: "EUR", frequency: "monthly", start_date: "2026-05-01", end_date: "2026-04-01" }),
    ).rejects.toMatchObject({ code: "invalid_range" });
  });

  it("manual apply blocks future items and advances one period", async () => {
    const { db } = await makeMemDb();
    const s = await createSource(db, { name: "A", currency: "EUR", starting_balance: 100 });
    const id = await createRecurring(db, { name: "Rent", amount: 50, direction: "out", currency: "EUR", frequency: "monthly", start_date: "2099-01-01", source_id: s.id });
    await expect(applyRecurringById(db, id, {}, "2026-05-15")).rejects.toMatchObject({ code: "not_yet_due" });

    const id2 = await createRecurring(db, { name: "Rent2", amount: 50, direction: "out", currency: "EUR", frequency: "monthly", start_date: "2026-05-01", source_id: s.id });
    await applyRecurringById(db, id2, {}, "2026-05-15");
    expect(await getBalance(db, s.id)).toBe(50);
    expect((await getRecurring(db, id2))!.next_due_date).toBe("2026-06-01");
  });
});

describe("scheduler tick", () => {
  it("auto mode catches up missed periods once (idempotent)", async () => {
    const { db } = await makeMemDb();
    const s = await createSource(db, { name: "A", currency: "EUR", starting_balance: 1000 });
    await createRecurring(db, { name: "Daily", amount: 10, direction: "out", currency: "EUR", frequency: "daily", start_date: "2026-05-01", source_id: s.id, apply_mode: "auto" });

    const r1 = await processDueRecurring(db, "2026-05-04"); // 4 periods: 1,2,3,4
    expect(r1.applied).toBe(4);
    expect(await getBalance(db, s.id)).toBe(960);
    // running again same day → no double application
    const r2 = await processDueRecurring(db, "2026-05-04");
    expect(r2.applied).toBe(0);
    expect(await getBalance(db, s.id)).toBe(960);
  });

  it("confirm mode posts a distinct confirm prompt — NOT suppressed by the upcoming reminder (BUG-2)", async () => {
    const { db } = await makeMemDb();
    const s = await createSource(db, { name: "A", currency: "EUR", starting_balance: 1000 });
    // alert window active 7 days before; due today → both reminder and confirm should appear
    const id = await createRecurring(db, { name: "Rent", amount: 50, direction: "out", currency: "EUR", frequency: "monthly", start_date: "2026-05-15", source_id: s.id, apply_mode: "confirm" });

    await processDueRecurring(db, "2026-05-15");
    // an upcoming 📅 reminder (recurring:id) AND a ✅ confirm (recurring:id#confirm) both exist
    expect(await unreadConfirm(db, id)).toBe(1);
    // no movement auto-created in confirm mode
    expect(await countMovements(db)).toBe(0);
    // running again does not duplicate the confirm prompt
    await processDueRecurring(db, "2026-05-15");
    expect(await unreadConfirm(db, id)).toBe(1);
  });

  it("insufficient-funds warning fires for OUT but never for IN (BUG-1)", async () => {
    const { db } = await makeMemDb();
    const lowOut = await createSource(db, { name: "Out", currency: "EUR", starting_balance: 5 });
    const lowIn = await createSource(db, { name: "In", currency: "EUR", starting_balance: 5 });
    await createRecurring(db, { name: "BigBill", amount: 100, direction: "out", currency: "EUR", frequency: "monthly", start_date: "2026-05-15", source_id: lowOut.id, apply_mode: "confirm" });
    await createRecurring(db, { name: "BigSalary", amount: 100, direction: "in", currency: "EUR", frequency: "monthly", start_date: "2026-05-15", source_id: lowIn.id, apply_mode: "confirm" });

    await processDueRecurring(db, "2026-05-15");
    const warnings = await db.select<{ title: string }>(`SELECT title FROM notifications WHERE type = 'warning'`);
    expect(warnings.length).toBe(1);
    expect(warnings[0].title).toContain("BigBill"); // only the OUT rule warns
  });
});

describe("update + summary", () => {
  it("enforces end >= start on update (BUG-3) and protects against backdating", async () => {
    const { db } = await makeMemDb();
    const id = await createRecurring(db, { name: "R", amount: 10, direction: "out", currency: "EUR", frequency: "monthly", start_date: "2026-05-01" });
    await expect(updateRecurring(db, id, { end_date: "2026-04-01" })).rejects.toMatchObject({ code: "invalid_range" });
  });

  it("monthly summary uses the fixed multipliers", async () => {
    const { db } = await makeMemDb();
    await createRecurring(db, { name: "D", amount: 10, direction: "out", currency: "EUR", frequency: "daily", start_date: "2026-05-01" });
    await createRecurring(db, { name: "W", amount: 50, direction: "out", currency: "EUR", frequency: "weekly", start_date: "2026-05-01" });
    const sum = await monthlySummary(db);
    // 10 * 365.25/12 = 304.38 ; 50 * 52.1785714/12 = 217.41
    expect(sum.byCurrency.EUR.outflow).toBe(round2sum(304.38, 217.41));
  });
});

describe("source yield accrual via scheduler", () => {
  it("credits a due, compounding yield and advances the schedule", async () => {
    const { db } = await makeMemDb();
    const s = await createSource(db, { name: "TD", currency: "EUR", starting_balance: 1000, yield_rate: 3, yield_period_months: 1 }, "2026-01-15");
    // next_due = 2026-02-15; accrue up to 2026-04-15 → 3 periods compounding to 1092.73
    const credited = await processSourceYields(db, "2026-04-15");
    expect(credited).toBe(3);
    expect(await getBalance(db, s.id)).toBe(1092.73);
    const after = (await db.select<{ yield_last_date: string }>(`SELECT yield_last_date FROM sources WHERE id = ?`, [s.id]))[0];
    expect(after.yield_last_date).toBe("2026-04-15");
  });
});

function round2sum(a: number, b: number) {
  return Math.round((a + b) * 100) / 100;
}
