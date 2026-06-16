import { Link, useParams } from "@tanstack/react-router";
import { ArrowDownLeft, ArrowLeftRight, ArrowUpRight, ChevronLeft, TrendingUp, Wallet } from "lucide-react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/badge";
import { BalanceHistoryChart } from "@/components/ui/balance-history-chart";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { isPreviewDb } from "@/db/connection";
import { useMovementCounts, useMovements, usePortfolios, useSources } from "@/db/queries";
import type { EnrichedMovement } from "@/db/repo/movements";
import { groupMovementsHierarchically } from "@/domain/grouping";
import { cn } from "@/lib/cn";
import { dayLabel, monthLabel } from "@/lib/date";
import { formatMoney, formatSigned } from "@/lib/format";

function Row({ m, locale }: { m: EnrichedMovement; locale?: string }) {
  const { t } = useTranslation();
  const transfer = m.transfer_pair_id != null;
  const ccy = m.source_currency;
  return (
    <li className="flex items-center justify-between gap-3 py-2.5">
      <div className="flex min-w-0 items-center gap-3">
        <span className={cn("grid h-8 w-8 shrink-0 place-items-center rounded-full", transfer ? "bg-surface-2 text-muted" : m.direction === "in" ? "bg-positive-soft text-positive" : "bg-negative-soft text-negative")}>
          {transfer ? <ArrowLeftRight className="h-4 w-4" /> : m.direction === "in" ? <ArrowUpRight className="h-4 w-4" /> : <ArrowDownLeft className="h-4 w-4" />}
        </span>
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-foreground">{m.note || (transfer ? t("transfer", { defaultValue: "Transfer" }) : t("movement", { defaultValue: "Movement" }))}</p>
          {transfer && <p className="truncate text-xs text-muted">→ {m.partner_source_name ?? "?"}</p>}
        </div>
      </div>
      <span className={cn("num text-sm font-semibold", transfer ? "text-muted" : m.direction === "in" ? "text-positive" : "text-foreground")}>
        {ccy ? (transfer ? formatMoney(m.amount, ccy, locale) : formatSigned(m.direction === "in" ? m.amount : -m.amount, ccy, locale)) : m.amount.toFixed(2)}
      </span>
    </li>
  );
}

export function SourceDetail() {
  const { t, i18n } = useTranslation();
  const locale = i18n.resolvedLanguage;
  const params = useParams({ strict: false }) as { id?: string };
  const id = Number(params.id);

  const { data: sources } = useSources();
  const { data: counts } = useMovementCounts();
  const { data: portfolios } = usePortfolios();
  const { data: movements, isLoading } = useMovements({ sourceId: id }, 500);

  const source = (sources ?? []).find((s) => s.id === id);
  const groups = useMemo(() => groupMovementsHierarchically(movements?.items ?? []), [movements]);
  const linkedPortfolios = (portfolios ?? []).filter((p) => p.portfolio.source_id === id);

  if (!source) {
    return (
      <div className="space-y-4">
        <Link to="/sources" className="inline-flex items-center gap-1 text-sm text-primary"><ChevronLeft className="h-4 w-4" /> {t("sources", { defaultValue: "Sources" })}</Link>
        <Card className="p-10 text-center text-sm text-muted">{t("not_found", { defaultValue: "Not found." })}</Card>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <Link to="/sources" className="inline-flex items-center gap-1 text-sm text-primary"><ChevronLeft className="h-4 w-4" /> {t("sources", { defaultValue: "Sources" })}</Link>

      <Card>
        <CardHeader
          title={<span className="flex items-center gap-2"><Wallet className="h-5 w-5 text-primary" />{source.name}</span>}
          subtitle={`${source.currency}${source.yield_rate > 0 ? ` · ${source.yield_rate}% / ${source.yield_period_months}m` : ""}`}
          action={
            <div className="text-right">
              <p className={cn("num text-xl font-semibold", source.balance < 0 ? "text-negative" : "text-foreground")}>{formatMoney(source.balance, source.currency, locale)}</p>
              <p className="text-xs text-muted">{t("n_movements", { defaultValue: "{{n}} movements", n: counts?.[id] ?? 0 })}</p>
            </div>
          }
        />
        <CardContent className="pt-2">
          <BalanceHistoryChart sourceId={id} currency={source.currency} locale={locale} height={150} />
        </CardContent>
      </Card>

      {linkedPortfolios.length > 0 && (
        <Card>
          <CardHeader title={t("portfolios", { defaultValue: "Portfolios" })} />
          <CardContent className="pt-2">
            <ul className="divide-y divide-border">
              {linkedPortfolios.map((p) => (
                <li key={p.portfolio.id}>
                  <Link to="/portfolios" className="flex items-center justify-between gap-3 py-2.5">
                    <span className="flex items-center gap-2 text-sm font-medium text-foreground"><TrendingUp className="h-4 w-4 text-primary" />{p.portfolio.name}</span>
                    <span className="flex items-center gap-2">
                      <span className="num text-sm font-semibold text-foreground">{formatMoney(p.total_value, p.portfolio.base_currency, locale)}</span>
                      {p.total_pnl != null && <Badge tone={p.total_pnl >= 0 ? "positive" : "negative"}>{p.total_pnl_pct}%</Badge>}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}

      {isPreviewDb && (
        <div className="rounded-[var(--radius-control)] border border-border bg-warning-soft px-3 py-2 text-xs text-warning">
          {t("preview_db_note", { defaultValue: "Browser preview with seeded sample data." })}
        </div>
      )}
      {isLoading && <Card className="p-8 text-center text-sm text-muted">{t("loading", { defaultValue: "Loading…" })}</Card>}
      {movements && groups.length === 0 && (
        <Card className="p-10 text-center text-sm text-muted">{t("no_movements", { defaultValue: "No movements yet." })}</Card>
      )}

      {groups.map((year) =>
        year.months.map((month) => (
          <Card key={month.month} className="overflow-hidden">
            <div className="flex items-center justify-between border-b border-border bg-surface-2/40 px-5 py-2.5">
              <h3 className="text-sm font-semibold text-foreground">{monthLabel(month.month, locale)}</h3>
              <div className="flex items-center gap-3 text-xs">
                {month.totalIn > 0 && <span className="num text-positive">+{month.totalIn.toFixed(2)}</span>}
                {month.totalOut > 0 && <span className="num text-muted">−{month.totalOut.toFixed(2)}</span>}
              </div>
            </div>
            <div className="px-5">
              {month.days.map((day) => (
                <div key={day.date} className="border-b border-border last:border-0">
                  <p className="pt-3 text-xs font-medium uppercase tracking-wide text-muted-2">{dayLabel(day.date, locale)}</p>
                  <ul className="divide-y divide-border">
                    {day.items.map((m) => <Row key={m.id} m={m} locale={locale} />)}
                  </ul>
                </div>
              ))}
            </div>
          </Card>
        )),
      )}
    </div>
  );
}
