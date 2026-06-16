import { describe, it, expect } from "vitest";
import { computeBalance, netWorthByCurrency, round2 } from "./money";

describe("round2", () => {
  it("rounds to 2 decimals half away from zero", () => {
    expect(round2(1.005)).toBe(1.01);
    expect(round2(2.675)).toBe(2.68);
    expect(round2(-1.005)).toBe(-1.01);
    expect(round2(1092.727)).toBe(1092.73);
    expect(round2(0)).toBe(0);
    expect(round2(10)).toBe(10);
  });
  it("cleans accumulated float error", () => {
    expect(round2(0.1 + 0.2)).toBe(0.3);
  });
});

describe("computeBalance", () => {
  it("is starting + Σin − Σout", () => {
    expect(
      computeBalance(100, [
        { direction: "in", amount: 50 },
        { direction: "out", amount: 30 },
        { direction: "in", amount: 5.5 },
      ]),
    ).toBe(125.5);
  });
  it("falls back to starting_balance with no movements", () => {
    expect(computeBalance(42.42, [])).toBe(42.42);
  });
  it("can go negative", () => {
    expect(computeBalance(0, [{ direction: "out", amount: 9.99 }])).toBe(-9.99);
  });
});

describe("netWorthByCurrency", () => {
  it("groups per currency and never mixes them", () => {
    expect(
      netWorthByCurrency([
        { currency: "EUR", balance: 100 },
        { currency: "USD", balance: 50 },
        { currency: "EUR", balance: 25.5 },
      ]),
    ).toEqual({ EUR: 125.5, USD: 50 });
  });
});
