import { describe, it, expect } from "vitest";
import { periodBounds, periodKey, shiftPeriod } from "./period";

describe("periodBounds", () => {
  it("aligns to calendar periods", () => {
    expect(periodBounds("weekly", "2026-05-13")).toEqual(["2026-05-11", "2026-05-17"]); // Wed → Mon..Sun
    expect(periodBounds("monthly", "2026-02-15")).toEqual(["2026-02-01", "2026-02-28"]);
    expect(periodBounds("quarterly", "2026-05-15")).toEqual(["2026-04-01", "2026-06-30"]);
    expect(periodBounds("yearly", "2026-07-01")).toEqual(["2026-01-01", "2026-12-31"]);
  });
});

describe("periodKey", () => {
  it("produces stable keys", () => {
    expect(periodKey("monthly", "2026-05-15")).toBe("2026-05");
    expect(periodKey("quarterly", "2026-05-15")).toBe("2026-Q2");
    expect(periodKey("yearly", "2026-05-15")).toBe("2026");
    expect(periodKey("weekly", "2026-01-01")).toMatch(/^\d{4}-W\d{2}$/);
  });
});

describe("shiftPeriod", () => {
  it("steps whole periods in the native cadence", () => {
    expect(periodBounds("monthly", shiftPeriod("monthly", "2026-05-15", -1))[0]).toBe("2026-04-01");
    expect(periodBounds("weekly", shiftPeriod("weekly", "2026-05-13", 1))).toEqual(["2026-05-18", "2026-05-24"]);
  });
});
