/**
 * Calendar-aligned budget periods (refactor-analysis/budgets-goals-whims.md §A2/A3).
 * Pure date math over ISO YYYY-MM-DD strings (UTC).
 */
import { addDaysISO, addMonthsISO } from "@/lib/date";

export type Period = "weekly" | "monthly" | "quarterly" | "yearly";

/** [start, end] inclusive ISO dates of the period containing `ref`. */
export function periodBounds(period: Period, ref: string): [string, string] {
  const [y, m, d] = ref.split("-").map(Number);
  switch (period) {
    case "weekly": {
      const dow = new Date(Date.UTC(y, m - 1, d)).getUTCDay(); // Sun=0
      const offsetToMon = (dow + 6) % 7;
      const monday = addDaysISO(ref, -offsetToMon);
      return [monday, addDaysISO(monday, 6)];
    }
    case "quarterly": {
      const qStartMonth = Math.floor((m - 1) / 3) * 3; // 0,3,6,9
      const start = new Date(Date.UTC(y, qStartMonth, 1)).toISOString().slice(0, 10);
      const end = new Date(Date.UTC(y, qStartMonth + 3, 0)).toISOString().slice(0, 10);
      return [start, end];
    }
    case "yearly":
      return [`${y}-01-01`, `${y}-12-31`];
    case "monthly":
    default: {
      const start = `${ref.slice(0, 7)}-01`;
      const last = new Date(Date.UTC(y, m, 0)).getUTCDate();
      return [start, `${ref.slice(0, 7)}-${String(last).padStart(2, "0")}`];
    }
  }
}

function isoWeek(ref: string): { year: number; week: number } {
  const [y, m, d] = ref.split("-").map(Number);
  const date = new Date(Date.UTC(y, m - 1, d));
  // ISO: Thursday of this week decides the year
  const day = (date.getUTCDay() + 6) % 7;
  date.setUTCDate(date.getUTCDate() - day + 3);
  const firstThursday = new Date(Date.UTC(date.getUTCFullYear(), 0, 4));
  const ft = (firstThursday.getUTCDay() + 6) % 7;
  firstThursday.setUTCDate(firstThursday.getUTCDate() - ft + 3);
  const week = 1 + Math.round((date.getTime() - firstThursday.getTime()) / (7 * 86400000));
  return { year: date.getUTCFullYear(), week };
}

/** Stable key per period (alert idempotency + display). */
export function periodKey(period: Period, ref: string): string {
  switch (period) {
    case "weekly": {
      const { year, week } = isoWeek(ref);
      return `${year}-W${String(week).padStart(2, "0")}`;
    }
    case "quarterly": {
      const m = Number(ref.slice(5, 7));
      return `${ref.slice(0, 4)}-Q${Math.floor((m - 1) / 3) + 1}`;
    }
    case "yearly":
      return ref.slice(0, 4);
    case "monthly":
    default:
      return ref.slice(0, 7);
  }
}

/** A ref date inside the period `offset` whole periods away from `ref`. */
export function shiftPeriod(period: Period, ref: string, offset: number): string {
  switch (period) {
    case "weekly":
      return addDaysISO(ref, 7 * offset);
    case "quarterly":
      return addMonthsISO(ref, 3 * offset);
    case "yearly":
      return addMonthsISO(ref, 12 * offset);
    case "monthly":
    default:
      return addMonthsISO(ref, offset);
  }
}
