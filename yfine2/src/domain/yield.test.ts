import { describe, it, expect } from "vitest";
import { round2 } from "./money";
import { accrueSource, resyncYieldSchedule, type YieldAccrualPort } from "./yield";
import { addMonthsISO } from "@/lib/date";

function memPort(initial: number) {
  let balance = initial;
  const posted: { amount: number; date: string }[] = [];
  const port: YieldAccrualPort = {
    async getBalance() {
      return balance;
    },
    async postInterest(_id, amount, date) {
      balance = round2(balance + amount);
      posted.push({ amount, date });
    },
  };
  return { port, posted, get balance() { return balance; } };
}

const NOTE = () => "interest";

describe("addMonthsISO", () => {
  it("clamps to end of shorter months", () => {
    expect(addMonthsISO("2026-01-31", 1)).toBe("2026-02-28");
    expect(addMonthsISO("2024-01-31", 1)).toBe("2024-02-29"); // leap
    expect(addMonthsISO("2026-01-15", 3)).toBe("2026-04-15");
    expect(addMonthsISO("2026-11-30", 3)).toBe("2027-02-28");
  });
});

describe("resyncYieldSchedule", () => {
  it("is null when inactive", () => {
    expect(resyncYieldSchedule(0, 12, null, "2026-01-01")).toBeNull();
    expect(resyncYieldSchedule(5, 0, null, "2026-01-01")).toBeNull();
  });
  it("anchors to last_date when present, else today", () => {
    expect(resyncYieldSchedule(5, 1, "2026-03-10", "2026-06-01")).toBe("2026-04-10");
    expect(resyncYieldSchedule(5, 1, null, "2026-06-01")).toBe("2026-07-01");
  });
});

describe("accrueSource", () => {
  const base = (over: Partial<Parameters<typeof accrueSource>[0]> = {}) => ({
    id: 1,
    yield_rate: 3,
    yield_period_months: 1,
    yield_last_date: null,
    yield_next_date: "2026-02-15",
    ...over,
  });

  it("compounds missed periods in one catch-up pass", async () => {
    const m = memPort(1000);
    const r = await accrueSource(base(), m.port, "2026-04-15", NOTE);
    expect(r.created).toBe(3);
    expect(m.balance).toBe(1092.73); // 1000 * 1.03^3
    expect(m.posted.map((p) => p.amount)).toEqual([30, 30.9, 31.83]);
    expect(r.yield_last_date).toBe("2026-04-15");
    expect(r.yield_next_date).toBe("2026-05-15");
  });

  it("advances without crediting a zero/negative balance, and terminates", async () => {
    const zero = memPort(0);
    const r0 = await accrueSource(base(), zero.port, "2026-06-15", NOTE);
    expect(r0.created).toBe(0);
    expect(zero.balance).toBe(0);
    expect(r0.yield_next_date! > "2026-06-15").toBe(true);

    const neg = memPort(-100);
    const rn = await accrueSource(base(), neg.port, "2026-04-15", NOTE);
    expect(rn.created).toBe(0);
    expect(neg.balance).toBe(-100);
  });

  it("never double-credits the same due date (idempotency)", async () => {
    const m = memPort(1000);
    const src = base();
    const r1 = await accrueSource(src, m.port, "2026-04-15", NOTE);
    expect(r1.created).toBe(3);
    // running again with the advanced schedule + same today does nothing
    const r2 = await accrueSource(
      { ...src, yield_last_date: r1.yield_last_date, yield_next_date: r1.yield_next_date },
      m.port,
      "2026-04-15",
      NOTE,
    );
    expect(r2.created).toBe(0);
    expect(m.balance).toBe(1092.73);
  });

  it("breaks immediately when last_date === next_date", async () => {
    const m = memPort(1000);
    const r = await accrueSource(
      base({ yield_last_date: "2026-02-15", yield_next_date: "2026-02-15" }),
      m.port,
      "2026-12-31",
      NOTE,
    );
    expect(r.created).toBe(0);
  });

  it("does nothing when inactive (rate 0 or next null)", async () => {
    const m = memPort(1000);
    expect((await accrueSource(base({ yield_rate: 0 }), m.port, "2026-12-31", NOTE)).created).toBe(0);
    expect((await accrueSource(base({ yield_next_date: null }), m.port, "2026-12-31", NOTE)).created).toBe(0);
  });
});
