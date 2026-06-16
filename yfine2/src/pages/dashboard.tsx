import { ArrowDownLeft, ArrowLeftRight, ArrowUpRight, CalendarClock, Eye, EyeOff, Info, PiggyBank } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { LineChart } from "@/components/ui/line-chart";
import { Slot, SlotMoney } from "@/components/ui/slot";
import { ForecastCard } from "@/components/forecast-card";
import { isPreviewDb } from "@/db/connection";
import { useConsolidated, useDashboard, useNetWorthHistory, usePreferences, useUpdatePreferences } from "@/db/queries";
import { round2 } from "@/domain/money";
import { cn } from "@/lib/cn";
import { dayLabel, monthLabel } from "@/lib/date";
import { formatMoney, formatSigned } from "@/lib/format";

const MASK = "••••••";

const RANGES = [
  { key: "30d", days: 30 },
  { key: "90d", days: 90 },
  { key: "1y", days: 365 },
  { key: "all", days: Infinity },
] as const;
type RangeKey = (typeof RANGES)[number]["key"];

function cutoffISO(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString().slice(0, 10);
}

function Stat({
  label,
  value,
  raw,
  tone,
  hidden,
  icon: Icon,
}: {
  label: string;
  value: string;
  raw: number;
  tone: "positive" | "negative" | "primary";
  hidden: boolean;
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
        <SlotMoney value={raw} text={hidden ? MASK : value} className="num text-base font-semibold text-foreground" />
      </div>
    </div>
  );
}

/** Income-vs-expense bars with per-month hover read-out and range totals. */
function MonthlyFlow({ comparison, primary, locale }: {
  comparison: { month: string; income: number; expense: number }[];
  primary: string;
  locale?: string;
}) {
  const { t } = useTranslation();
  const [hover, setHover] = useState<number | null>(null);
  const maxBar = Math.max(1, ...comparison.flatMap((c) => [c.income, c.expense]));
  const totalIn = round2(comparison.reduce((s, c) => s + c.income, 0));
  const totalOut = round2(comparison.reduce((s, c) => s + c.expense, 0));
  const hc = hover != null ? comparison[hover] : null;

  return (
    <Card className="lg:col-span-7">
      <CardHeader
        title={t("monthly_flow", { defaultValue: "Monthly flow" })}
        subtitle={`${t("income_vs_expense", { defaultValue: "Income vs expense" })} · ${primary}`}
        action={
          <div className="flex items-center gap-3 text-xs">
            <span className="num text-positive">+{formatMoney(totalIn, primary, locale)}</span>
            <span className="num text-negative">−{formatMoney(totalOut, primary, locale)}</span>
          </div>
        }
      />
      <CardContent>
        <div className="relative flex h-40 items-end justify-between gap-3">
          {hc && (
            <div className="absolute inset-x-0 -top-1 z-10 flex justify-center">
              <div className="whitespace-nowrap rounded-[var(--radius-control)] border border-border bg-surface px-2.5 py-1 text-xs shadow-[var(--shadow-pop)]">
                <span className="mr-2 font-medium text-foreground">{monthLabel(hc.month, locale)}</span>
                <span className="num text-positive">+{formatMoney(hc.income, primary, locale)}</span>
                <span className="num ml-2 text-negative">−{formatMoney(hc.expense, primary, locale)}</span>
              </div>
            </div>
          )}
          {comparison.map((c, i) => (
            <div
              key={c.month}
              className="flex flex-1 cursor-default flex-col items-center gap-1.5"
              onPointerEnter={() => setHover(i)}
              onPointerLeave={() => setHover((h) => (h === i ? null : h))}
            >
              <div className={cn("flex w-full items-end justify-center gap-1 rounded-t transition-colors", hover === i && "bg-surface-2/60")} style={{ height: 128 }}>
                <div className="w-1/2 rounded-t bg-positive/80" style={{ height: `${(c.income / maxBar) * 100}%` }} />
                <div className="w-1/2 rounded-t bg-negative/70" style={{ height: `${(c.expense / maxBar) * 100}%` }} />
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
  );
}

export function Dashboard() {
  const { t, i18n } = useTranslation();
  const locale = i18n.resolvedLanguage;
  const { data, isLoading } = useDashboard();
  const { data: prefs } = usePreferences();
  const updatePrefs = useUpdatePreferences();
  const [showTotal, setShowTotal] = useState(false);
  const [range, setRange] = useState<RangeKey>("1y");
  const consolidated = useConsolidated(showTotal && data ? data.primaryCurrency : null);

  const hidden = (prefs?.hide_net_worth ?? 0) === 1;
  const toggleHidden = () => updatePrefs.mutate({ hide_net_worth: !hidden });

  const view = useMemo(() => {
    if (!data) return null;
    const entries = Object.entries(data.netWorth).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]));
    const primary = data.primaryCurrency;
    const flow = data.flow.byCurrency[primary] ?? { income: 0, expense: 0 };
    const saved = data.savings[primary] ?? 0;
    const net = round2(flow.income - flow.expense);
    return { entries, primary, flow, saved, net };
  }, [data]);

  const fullHistory = useNetWorthHistory(view?.primary ?? null);
  const series = useMemo(() => {
    const pts = fullHistory.data ?? [];
    const days = RANGES.find((r) => r.key === range)!.days;
    if (days === Infinity) return pts;
    const cut = cutoffISO(days);
    const f = pts.filter((p) => p.date >= cut);
    return f.length >= 2 ? f : pts;
  }, [fullHistory.data, range]);

  if (isLoading || !view || !data) {
    return <Card className="p-10 text-center text-sm text-muted">{t("loading", { defaultValue: "Loading…" })}</Card>;
  }

  const fmtMoney = (n: number) => formatMoney(n, view.primary, locale);
  const netWorthValue = data.netWorth[view.primary] ?? 0;

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
              <div className="flex items-center gap-2">
                {view.net !== 0 && !hidden && (
                  <Badge tone={view.net >= 0 ? "positive" : "negative"}>
                    {view.net >= 0 ? <ArrowUpRight className="h-3 w-3" /> : <ArrowDownLeft className="h-3 w-3" />}
                    {formatSigned(view.net, view.primary, locale)}
                  </Badge>
                )}
                <button
                  onClick={toggleHidden}
                  aria-label={t("toggle_visibility", { defaultValue: "Toggle visibility" })}
                  className="grid h-8 w-8 place-items-center rounded-[var(--radius-control)] text-muted hover:bg-surface-2 hover:text-foreground"
                >
                  {hidden ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
            }
          />
          <CardContent className="pt-2">
            <SlotMoney
              value={netWorthValue}
              text={hidden ? MASK : fmtMoney(netWorthValue)}
              className="num text-4xl font-semibold tracking-tight text-foreground"
            />
            <div className="mt-3 flex items-center justify-between">
              <p className="text-sm text-muted">{t("over_time", { defaultValue: "Over time" })}</p>
              <div className="flex gap-1">
                {RANGES.map((r) => (
                  <button
                    key={r.key}
                    onClick={() => setRange(r.key)}
                    className={cn(
                      "rounded-[var(--radius-control)] px-2 py-0.5 text-xs font-medium transition-colors",
                      range === r.key ? "bg-accent-soft text-primary" : "text-muted hover:text-foreground",
                    )}
                  >
                    {t(r.key, { defaultValue: r.key })}
                  </button>
                ))}
              </div>
            </div>
            <div className="mt-2">
              <LineChart
                points={series}
                height={150}
                format={hidden ? () => MASK : fmtMoney}
                formatDate={(d) => dayLabel(d, locale)}
              />
            </div>
            {view.entries.length > 1 && (
              <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-border pt-3">
                {view.entries.filter(([c]) => c !== view.primary).map(([ccy, amt]) => (
                  <span key={ccy} className="num rounded-[var(--radius-control)] bg-surface-2 px-2.5 py-1 text-sm text-foreground">
                    {hidden ? `${MASK} ${ccy}` : formatMoney(amt, ccy, locale)}
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
                ≈ {hidden ? `${MASK} ${consolidated.data.base}` : formatMoney(consolidated.data.total, consolidated.data.base, locale)}
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
            <Stat label={t("income", { defaultValue: "Income" })} raw={view.flow.income} value={fmtMoney(view.flow.income)} tone="positive" hidden={hidden} icon={ArrowUpRight} />
            <Stat label={t("expense", { defaultValue: "Expense" })} raw={view.flow.expense} value={fmtMoney(view.flow.expense)} tone="negative" hidden={hidden} icon={ArrowDownLeft} />
            <Stat label={t("saved", { defaultValue: "Saved" })} raw={view.saved} value={fmtMoney(view.saved)} tone="primary" hidden={hidden} icon={PiggyBank} />
          </CardContent>
        </Card>

        {/* Monthly flow */}
        <MonthlyFlow comparison={data.comparison} primary={view.primary} locale={locale} />

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
              <RecentMovements items={data.recent} primary={view.primary} locale={locale} />
            )}
          </CardContent>
        </Card>
      </div>
      <ForecastCard />
    </div>
  );
}

function RecentMovements({ items, primary, locale }: {
  items: import("@/db/repo/movements").EnrichedMovement[];
  primary: string;
  locale?: string;
}) {
  const { t } = useTranslation();
  // Already newest-first from the query; group by day so the ordering reads clearly.
  const groups = useMemo(() => {
    const out: { date: string; items: typeof items }[] = [];
    for (const m of items) {
      const last = out[out.length - 1];
      if (last && last.date === m.date) last.items.push(m);
      else out.push({ date: m.date, items: [m] });
    }
    return out;
  }, [items]);

  return (
    <div className="divide-y divide-border">
      {groups.map((g) => (
        <div key={g.date} className="py-1.5 first:pt-0">
          <p className="py-1 text-xs font-medium uppercase tracking-wide text-muted-2">{dayLabel(g.date, locale)}</p>
          <ul className="divide-y divide-border">
            {g.items.map((m) => {
              const transfer = m.transfer_pair_id != null;
              const ccy = m.source_currency ?? primary;
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
                  <p className={cn("num text-sm font-semibold", transfer ? "text-muted" : m.direction === "in" ? "text-positive" : "text-foreground")}>
                    {transfer ? formatMoney(m.amount, ccy, locale) : formatSigned(m.direction === "in" ? m.amount : -m.amount, ccy, locale)}
                  </p>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </div>
  );
}
