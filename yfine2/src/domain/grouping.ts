/**
 * Hierarchical year → month → day grouping for the movements list.
 * Totals (in/out) sum ONLY non-transfer rows (transfer_pair_id IS NULL), matching
 * the legacy group_movements_hierarchically. Input MUST be pre-sorted date DESC.
 */
import { round2 } from "./money";

export interface GroupableMovement {
  date: string; // YYYY-MM-DD
  direction: "in" | "out";
  amount: number;
  transfer_pair_id: number | null;
}

export interface DayGroup<T> {
  date: string;
  items: T[];
  totalIn: number;
  totalOut: number;
}
export interface MonthGroup<T> {
  month: string; // YYYY-MM
  days: DayGroup<T>[];
  totalIn: number;
  totalOut: number;
}
export interface YearGroup<T> {
  year: string; // YYYY
  months: MonthGroup<T>[];
  totalIn: number;
  totalOut: number;
}

export function groupMovementsHierarchically<T extends GroupableMovement>(
  rows: readonly T[],
): YearGroup<T>[] {
  const years: YearGroup<T>[] = [];
  let curYear: YearGroup<T> | undefined;
  let curMonth: MonthGroup<T> | undefined;
  let curDay: DayGroup<T> | undefined;

  for (const m of rows) {
    const y = m.date.slice(0, 4);
    const ym = m.date.slice(0, 7);
    const d = m.date;

    if (!curYear || curYear.year !== y) {
      curYear = { year: y, months: [], totalIn: 0, totalOut: 0 };
      years.push(curYear);
      curMonth = undefined;
      curDay = undefined;
    }
    if (!curMonth || curMonth.month !== ym) {
      curMonth = { month: ym, days: [], totalIn: 0, totalOut: 0 };
      curYear.months.push(curMonth);
      curDay = undefined;
    }
    if (!curDay || curDay.date !== d) {
      curDay = { date: d, items: [], totalIn: 0, totalOut: 0 };
      curMonth.days.push(curDay);
    }

    curDay.items.push(m);
    // Only non-transfer rows count toward totals.
    if (m.transfer_pair_id == null) {
      const field = m.direction === "in" ? "totalIn" : "totalOut";
      curDay[field] = round2(curDay[field] + m.amount);
      curMonth[field] = round2(curMonth[field] + m.amount);
      curYear[field] = round2(curYear[field] + m.amount);
    }
  }

  return years;
}
