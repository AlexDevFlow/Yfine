import { ChevronLeft, ChevronRight } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Modal } from "@/components/ui/modal";
import { useMovements } from "@/db/queries";
import type { EnrichedMovement } from "@/db/repo/movements";
import { cn } from "@/lib/cn";
import { dayLabel, monthLabel, todayISO } from "@/lib/date";
import { formatMoney, formatSigned } from "@/lib/format";

function daysInMonth(year: number, month1: number): number {
  return new Date(year, month1, 0).getDate();
}

/** Month calendar with per-day movement counts + net direction; click a day to list it. */
export function MovementsCalendar({ onClose, locale }: { onClose: () => void; locale?: string }) {
  const { t } = useTranslation();
  const [month, setMonth] = useState(() => todayISO().slice(0, 7)); // YYYY-MM
  const [selected, setSelected] = useState<string | null>(null);

  const [yy, mm] = month.split("-").map(Number);
  const first = `${month}-01`;
  const last = `${month}-${String(daysInMonth(yy, mm)).padStart(2, "0")}`;
  const { data } = useMovements({ dateFrom: first, dateTo: last, excludeTransferIn: true }, 1000);

  const byDay = useMemo(() => {
    const m = new Map<string, { count: number; net: number; items: EnrichedMovement[] }>();
    for (const mv of data?.items ?? []) {
      const e = m.get(mv.date) ?? { count: 0, net: 0, items: [] };
      e.count += 1;
      e.net += mv.direction === "in" ? mv.amount : -mv.amount;
      e.items.push(mv);
      m.set(mv.date, e);
    }
    return m;
  }, [data]);

  const shift = (delta: number) => {
    const d = new Date(yy, mm - 1 + delta, 1);
    setMonth(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`);
    setSelected(null);
  };

  // Monday-first grid.
  const leading = (new Date(yy, mm - 1, 1).getDay() + 6) % 7;
  const total = daysInMonth(yy, mm);
  const cells: (string | null)[] = [
    ...Array(leading).fill(null),
    ...Array.from({ length: total }, (_, i) => `${month}-${String(i + 1).padStart(2, "0")}`),
  ];
  const weekdays = [t("mon", { defaultValue: "Mon" }), t("tue", { defaultValue: "Tue" }), t("wed", { defaultValue: "Wed" }), t("thu", { defaultValue: "Thu" }), t("fri", { defaultValue: "Fri" }), t("sat", { defaultValue: "Sat" }), t("sun", { defaultValue: "Sun" })];
  const sel = selected ? byDay.get(selected) : null;

  return (
    <Modal open onClose={onClose} title={t("calendar", { defaultValue: "Calendar" })}>
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <button onClick={() => shift(-1)} aria-label={t("previous", { defaultValue: "Previous" })} className="grid h-8 w-8 place-items-center rounded-[var(--radius-control)] text-muted hover:bg-surface-2 hover:text-foreground"><ChevronLeft className="h-4 w-4" /></button>
          <span className="text-sm font-semibold text-foreground">{monthLabel(month, locale)}</span>
          <button onClick={() => shift(1)} aria-label={t("next", { defaultValue: "Next" })} className="grid h-8 w-8 place-items-center rounded-[var(--radius-control)] text-muted hover:bg-surface-2 hover:text-foreground"><ChevronRight className="h-4 w-4" /></button>
        </div>

        <div className="grid grid-cols-7 gap-1 text-center">
          {weekdays.map((w) => <div key={w} className="text-[11px] font-medium text-muted-2">{w}</div>)}
          {cells.map((d, i) => {
            if (!d) return <div key={`b${i}`} />;
            const info = byDay.get(d);
            const dayNum = Number(d.slice(8));
            return (
              <button
                key={d}
                onClick={() => info && setSelected(d)}
                disabled={!info}
                className={cn(
                  "flex aspect-square flex-col items-center justify-center rounded-[var(--radius-control)] text-xs",
                  selected === d ? "bg-accent-soft ring-1 ring-primary" : info ? "bg-surface-2 hover:bg-border" : "text-muted-2",
                )}
              >
                <span className={cn(info && "font-medium text-foreground")}>{dayNum}</span>
                {info && (
                  <span className={cn("mt-0.5 h-1.5 w-1.5 rounded-full", info.net >= 0 ? "bg-positive" : "bg-negative")} />
                )}
              </button>
            );
          })}
        </div>

        {sel ? (
          <div className="border-t border-border pt-2">
            <p className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-2">{dayLabel(selected!, locale)}</p>
            <ul className="max-h-56 divide-y divide-border overflow-y-auto">
              {sel.items.map((m) => (
                <li key={m.id} className="flex items-center justify-between gap-3 py-2 text-sm">
                  <span className="min-w-0 truncate text-foreground">{m.note || m.source_name || t("movement", { defaultValue: "Movement" })}</span>
                  <span className={cn("num shrink-0 font-semibold", m.direction === "in" ? "text-positive" : "text-foreground")}>
                    {m.source_currency ? formatSigned(m.direction === "in" ? m.amount : -m.amount, m.source_currency, locale) : m.amount.toFixed(2)}
                  </span>
                </li>
              ))}
            </ul>
            <p className="mt-1 text-right text-xs text-muted">
              {t("net", { defaultValue: "Net" })}: <span className={cn("num", sel.net >= 0 ? "text-positive" : "text-negative")}>{sel.items[0]?.source_currency ? formatMoney(sel.net, sel.items[0].source_currency, locale) : sel.net.toFixed(2)}</span>
            </p>
          </div>
        ) : (
          <p className="border-t border-border pt-2 text-center text-xs text-muted">{t("calendar_hint", { defaultValue: "Pick a day with activity to see its movements." })}</p>
        )}
      </div>
    </Modal>
  );
}
