/** Date helpers operating on ISO `YYYY-MM-DD` strings in UTC (tz-stable). */

/** Today as `YYYY-MM-DD` in the local calendar. */
export function todayISO(d: Date = new Date()): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

/**
 * Add `n` whole months to an ISO date, clamping the day to the last day of the
 * target month (Jan 31 + 1mo -> Feb 28/29), matching dateutil.relativedelta as
 * used by the legacy scheduler/yield code.
 */
export function addMonthsISO(iso: string, n: number): string {
  const [y, m, d] = iso.split("-").map(Number);
  const targetMonthStart = new Date(Date.UTC(y, m - 1 + n, 1));
  const ty = targetMonthStart.getUTCFullYear();
  const tm = targetMonthStart.getUTCMonth();
  const lastDay = new Date(Date.UTC(ty, tm + 1, 0)).getUTCDate();
  const day = Math.min(d, lastDay);
  const res = new Date(Date.UTC(ty, tm, day));
  return res.toISOString().slice(0, 10);
}

/** "2026-05" → "May 2026" (locale-aware). */
export function monthLabel(ym: string, locale?: string): string {
  const [y, m] = ym.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, 1)).toLocaleDateString(locale, {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });
}

/** Add `n` days to an ISO date (UTC, tz-stable). */
export function addDaysISO(iso: string, n: number): string {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d + n)).toISOString().slice(0, 10);
}

/** Whole days between two ISO dates (b − a). */
export function daysBetween(a: string, b: string): number {
  const [ay, am, ad] = a.split("-").map(Number);
  const [by, bm, bd] = b.split("-").map(Number);
  return Math.round((Date.UTC(by, bm - 1, bd) - Date.UTC(ay, am - 1, ad)) / 86400000);
}

/** First day of the ISO date's month, e.g. "2026-05-17" → "2026-05-01". */
export function monthStart(iso: string): string {
  return iso.slice(0, 7) + "-01";
}

/** Last day of the ISO date's month, e.g. "2026-05-17" → "2026-05-31". */
export function monthEnd(iso: string): string {
  const [y, m] = iso.split("-").map(Number);
  const last = new Date(Date.UTC(y, m, 0)).getUTCDate();
  return `${iso.slice(0, 7)}-${String(last).padStart(2, "0")}`;
}

/** The last `n` "YYYY-MM" months ending at `iso`'s month, chronological. */
export function lastNMonths(iso: string, n: number): string[] {
  const [y, m] = iso.split("-").map(Number);
  const out: string[] = [];
  for (let i = n - 1; i >= 0; i--) {
    out.push(new Date(Date.UTC(y, m - 1 - i, 1)).toISOString().slice(0, 7));
  }
  return out;
}

/** "2026-05-03" → "Sun, 3 May" (locale-aware). */
export function dayLabel(iso: string, locale?: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString(locale, {
    weekday: "short",
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  });
}
