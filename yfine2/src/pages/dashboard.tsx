import { ArrowDownLeft, ArrowLeftRight, ArrowUpRight, CalendarClock, Info, PiggyBank } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Slot, SlotMoney } from "@/components/ui/slot";
import { ForecastCard } from "@/components/forecast-card";
import { isPreviewDb } from "@/db/connection";
import { useConsolidated, useDashboard } from "@/db/queries";
import { round2 } from "@/domain/money";
import { cn } from "@/lib/cn";
import { dayLabel, monthLabel } from "@/lib/date";
import { formatMoney, formatSigned } from "@/lib/format";

function Sparkline({ data }: { data: number[] }) {
  if (data.length < 2) return null;
  const w = 100;
  const h = 32;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const span = max - min || 1;
  const pts = data
    .map((v, i) => `${((i / (data.length - 1)) * w).toFixed(2)},${(h - ((v - min) / span) * h).toFixed(2)}`)
    .join(" ");
  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" className="h-12 w-full">
      <defs>
        <linearGradient id="spark" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--primary)" stopOpacity="0.25" />
          <stop offset="100%" stopColor="var(--primary)" stopOpacity="0" />
        </linearGradient>
      </defs>
      <polyline points={`0,${h} ${pts} ${w},${h}`} fill="url(#spark)" stroke="none" />
      <polyline points={pts} fill="none" stroke="var(--primary)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

function Stat({
  label,
  value,
  raw,
  tone,
  icon: Icon,
}: {
  label: string;
  value: string;
  raw: number;
  tone: "positive" | "negative" | "primary";
  icon: typeof ArrowUpRight;
}) {
  const toneClass =
    tone === "positive" ? "text-positive bg-positive-soft" : tone === "negative" ? "text-negative bg-negative-soft" : "text-primary bg-accent-soft";
  return (
    <div className="flex items-center gap-3">
      <div className={cn("grid h-9 w-9 shrink-0 place-items-center rounded-[var(--radius-control)]", toneClass)}>
        <Icon className="h-[18px] w-[18px]" />
      </div>
      <div className="min-w-0">
        <p className="text-xs text-muted">{label}</p>
        <SlotMoney value={raw} text={value} className="num text-base font-semibold text-foreground" />
      </div>
    </div>
  );
}

export function Dashboard() {
  const { t, i18n } = useTranslation();
  const locale = i18n.resolvedLanguage;
  const { data, isLoading } = useDashboard();
  const [showTotal, setShowTotal] = useState(false);
  const consolidated = useConsolidated(showTotal && data ? data.primaryCurrency : null);

  const view = useMemo(() => {
    if (!data) return null;
    const entries = Object.entries(data.netWorth).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]));
    const primary = data.primaryCurrency;
    const flow = data.flow.byCurrency[primary] ?? { income: 0, expense: 0 };
    const saved = data.savings[primary] ?? 0;
    const net = round2(flow.income - flow.expense);
    // cumulative net series for the sparkline
    let acc = 0;
    const series = data.comparison.map((c) => (acc = round2(acc + c.income - c.expense)));
    const maxBar = Math.max(1, ...data.comparison.flatMap((c) => [c.income, c.expense]));
    return { entries, primary, flow, saved, net, series, maxBar };
  }, [data]);

  if (isLoading || !view || !data) {
    return <Card className="p-10 text-center text-sm text-muted">{t("loading", { defaultValue: "Loading…" })}</Card>;
  }

  return (
    <div className="space-y-4">
      {isPreviewDb && (
        <div className="flex items-center gap-2 rounded-[var(--radius-control)] border border-border bg-warning-soft px-3 py-2 text-xs text-warning">
          <Info className="h-3.5 w-3.5" />
          {t("preview_db_note", { defaultValue: "Browser preview with seeded sample data (in-memory). The packaged app uses your real database." })}
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
        {/* Net worth */}
        <Card className="lg:col-span-8">
          <CardHeader
            title={t("net_worth", { defaultValue: "Net Worth" })}
            subtitle={view.entries.length > 1 ? t("primary_currency", { defaultValue: "Primary currency" }) + ` · ${view.primary}` : view.primary}
            action={
              view.net !== 0 ? (
                <Badge tone={view.net >= 0 ? "positive" : "negative"}>
                  {view.net >= 0 ? <ArrowUpRight className="h-3 w-3" /> : <ArrowDownLeft className="h-3 w-3" />}
                  {formatSigned(view.net, view.primary, locale)}
                </Badge>
              ) : undefined
            }
          />
          <CardContent className="pt-2">
            <SlotMoney
              value={data.netWorth[view.primary] ?? 0}
              text={formatMoney(data.netWorth[view.primary] ?? 0, view.primary, locale)}
              className="num text-4xl font-semibold tracking-tight text-foreground"
            />
            <p className="mt-1 text-sm text-muted">{t("this_month", { defaultValue: "this month" })}</p>
            <div className="mt-3"><Sparkline data={view.series} /></div>
            {view.entries.length > 1 && (
              <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-border pt-3">
                {view.entries.filter(([c]) => c !== view.primary).map(([ccy, amt]) => (
                  <span key={ccy} className="num rounded-[var(--radius-control)] bg-surface-2 px-2.5 py-1 text-sm text-foreground">
                    {formatMoney(amt, ccy, locale)}
                  </span>
                ))}
                <button onClick={() => setShowTotal((v) => !v)} className="text-xs font-medium text-primary">
                  <Slot
                    text={showTotal ? t("hide_total", { defaultValue: "Hide total" }) : t("show_total_in", { defaultValue: "Total in {{ccy}}", ccy: view.primary })}
                    options={{ direction: showTotal ? "up" : "down" }}
                  />
                </button>
              </div>
            )}
            {showTotal && consolidated.data && (
              <p className="num mt-2 text-sm text-foreground">
                ≈ {formatMoney(consolidated.data.total, consolidated.data.base, locale)}
                {consolidated.data.missing.length > 0 && (
                  <span className="text-warning"> ({t("excluding", { defaultValue: "excl." })} {consolidated.data.missing.join(", ")})</span>
                )}
              </p>
            )}
          </CardContent>
        </Card>

        {/* This month */}
        <Card className="lg:col-span-4">
          <CardHeader title={t("this_month", { defaultValue: "This month" })} subtitle={view.primary} />
          <CardContent className="space-y-4 pt-3">
            <Stat label={t("income", { defaultValue: "Income" })} raw={view.flow.income} value={formatMoney(view.flow.income, view.primary, locale)} tone="positive" icon={ArrowUpRight} />
            <Stat label={t("expense", { defaultValue: "Expense" })} raw={view.flow.expense} value={formatMoney(view.flow.expense, view.primary, locale)} tone="negative" icon={ArrowDownLeft} />
            <Stat label={t("saved", { defaultValue: "Saved" })} raw={view.saved} value={formatMoney(view.saved, view.primary, locale)} tone="primary" icon={PiggyBank} />
          </CardContent>
        </Card>

        {/* Monthly flow */}
        <Card className="lg:col-span-7">
          <CardHeader title={t("monthly_flow", { defaultValue: "Monthly flow" })} subtitle={`${t("income_vs_expense", { defaultValue: "Income vs expense" })} · ${view.primary}`} />
          <CardContent>
            <div className="flex h-40 items-end justify-between gap-3">
              {data.comparison.map((c) => (
                <div key={c.month} className="flex flex-1 flex-col items-center gap-1.5">
                  <div className="flex w-full items-end justify-center gap-1" style={{ height: 128 }}>
                    <div className="w-1/2 rounded-t bg-positive/80" style={{ height: `${(c.income / view.maxBar) * 100}%` }} title={`${t("income", { defaultValue: "Income" })} ${c.income}`} />
                    <div className="w-1/2 rounded-t bg-negative/70" style={{ height: `${(c.expense / view.maxBar) * 100}%` }} title={`${t("expense", { defaultValue: "Expense" })} ${c.expense}`} />
                  </div>
                  <span className="text-[11px] text-muted">{monthLabel(c.month, locale).split(" ")[0].slice(0, 3)}</span>
                </div>
              ))}
            </div>
            <div className="mt-3 flex items-center gap-4 text-xs text-muted">
              <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-positive" />{t("income", { defaultValue: "Income" })}</span>
              <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-negative" />{t("expense", { defaultValue: "Expense" })}</span>
            </div>
          </CardContent>
        </Card>

        {/* Upcoming recurring */}
        <Card className="lg:col-span-5">
          <CardHeader title={t("upcoming_recurring", { defaultValue: "Upcoming" })} action={<CalendarClock className="h-4 w-4 text-muted" />} />
          <CardContent className="pt-2">
            {data.upcoming.length === 0 ? (
              <p className="py-6 text-center text-sm text-muted">{t("no_recurring", { defaultValue: "Nothing scheduled." })}</p>
            ) : (
              <ul className="divide-y divide-border">
                {data.upcoming.map((r) => (
                  <li key={r.id} className="flex items-center justify-between gap-3 py-2.5">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium text-foreground">{r.name}</p>
                      <p className="text-xs text-muted">{dayLabel(r.next_due_date, locale)}</p>
                    </div>
                    <span className={cn("num text-sm font-semibold", r.direction === "in" ? "text-positive" : "text-foreground")}>
                      {formatSigned(r.direction === "in" ? r.amount : -r.amount, r.currency, locale)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        {/* Recent movements */}
        <Card className="lg:col-span-12">
          <CardHeader title={t("recent_movements", { defaultValue: "Recent Movements" })} />
          <CardContent className="pt-2">
            {data.recent.length === 0 ? (
              <p className="py-6 text-center text-sm text-muted">{t("no_movements", { defaultValue: "No movements yet." })}</p>
            ) : (
              <ul className="divide-y divide-border">
                {data.recent.map((m) => {
                  const transfer = m.transfer_pair_id != null;
                  const ccy = m.source_currency ?? view.primary;
                  return (
                    <li key={m.id} className="flex items-center justify-between gap-3 py-2.5">
                      <div className="flex min-w-0 items-center gap-3">
                        <span className={cn("grid h-8 w-8 shrink-0 place-items-center rounded-full", transfer ? "bg-surface-2 text-muted" : m.direction === "in" ? "bg-positive-soft text-positive" : "bg-negative-soft text-negative")}>
                          {transfer ? <ArrowLeftRight className="h-4 w-4" /> : m.direction === "in" ? <ArrowUpRight className="h-4 w-4" /> : <ArrowDownLeft className="h-4 w-4" />}
                        </span>
                        <div className="min-w-0">
                          <p className="truncate text-sm font-medium text-foreground">{m.note || m.source_name || t("external", { defaultValue: "External" })}</p>
                          <p className="truncate text-xs text-muted">{m.source_name ?? t("external", { defaultValue: "External" })}</p>
                        </div>
                      </div>
                      <div className="text-right">
                        <p className={cn("num text-sm font-semibold", transfer ? "text-muted" : m.direction === "in" ? "text-positive" : "text-foreground")}>
                          {transfer ? formatMoney(m.amount, ccy, locale) : formatSigned(m.direction === "in" ? m.amount : -m.amount, ccy, locale)}
                        </p>
                        <p className="text-xs text-muted">{dayLabel(m.date, locale)}</p>
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>
      <ForecastCard />
    </div>
  );
}
