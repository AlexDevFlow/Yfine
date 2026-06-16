import { describe, it, expect } from "vitest";
import { groupMovementsHierarchically, type GroupableMovement } from "./grouping";

const mk = (
  date: string,
  direction: "in" | "out",
  amount: number,
  transfer = false,
): GroupableMovement => ({ date, direction, amount, transfer_pair_id: transfer ? 99 : null });

describe("groupMovementsHierarchically", () => {
  it("nests year → month → day and totals exclude transfers", () => {
    const rows = [
      mk("2026-05-10", "in", 2000),
      mk("2026-05-10", "out", 50),
      mk("2026-05-10", "out", 300, true), // transfer leg — not counted
      mk("2026-05-03", "out", 42.5),
      mk("2026-04-28", "in", 10),
      mk("2025-12-31", "out", 5),
    ];
    const groups = groupMovementsHierarchically(rows);

    expect(groups.map((y) => y.year)).toEqual(["2026", "2025"]);
    const y2026 = groups[0];
    expect(y2026.totalIn).toBe(2010);
    expect(y2026.totalOut).toBe(92.5); // 50 + 42.5, transfer 300 excluded
    expect(y2026.months.map((m) => m.month)).toEqual(["2026-05", "2026-04"]);

    const may = y2026.months[0];
    expect(may.days.map((d) => d.date)).toEqual(["2026-05-10", "2026-05-03"]);
    const may10 = may.days[0];
    expect(may10.items.length).toBe(3); // transfer row still listed
    expect(may10.totalIn).toBe(2000);
    expect(may10.totalOut).toBe(50);
  });

  it("handles an empty list", () => {
    expect(groupMovementsHierarchically([])).toEqual([]);
  });
});
