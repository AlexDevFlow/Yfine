import { AlertTriangle, TrendingDown, TrendingUp } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { useForecast } from "@/db/queries";
import { cn } from "@/lib/cn";
import { dayLabel } from "@/lib/date";
import { formatMoney } from "@/lib/format";

function MiniLine({ values }: { values: number[] }) {
  if (values.length < 2) return null;
  const w = 100;
  const h = 28;
  const min = Math.min(...values, 0);
  const max = Math.max(...values, 0);
  const span = max - min || 1;
  const pts = values.map((v, i) => `${((i / (values.length - 1)) * w).toFixed(1)},${(h - ((v - min) / span) * h).toFixed(1)}`).join(" ");
  const zeroY = (h - ((0 - min) / span) * h).toFixed(1);
  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" className="h-8 w-full">
      <line x1="0" y1={zeroY} x2={w} y2={zeroY} stroke="var(--border-strong)" strokeWidth="1" strokeDasharray="2 2" vectorEffect="non-scaling-stroke" />
      <polyline points={pts} fill="none" stroke="var(--primary)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

export function ForecastCard() {
  const { t, i18n } = useTranslation();
  const locale = i18n.resolvedLanguage;
  const { data, isLoading } = useForecast(90);

  if (isLoading || !data || data.length === 0) return null;

  return (
    <Card>
      <CardHeader
        title={t("cashflow_forecast", { defaultValue: "90-day forecast" })}
        subtitle={t("forecast_hint", { defaultValue: "Projected from your recurring items" })}
      />
      <CardContent className="space-y-4 pt-3">
        {data.map((f) => (
          <div key={f.currency}>
            <div className="flex items-baseline justify-between text-sm">
              <span className="font-medium text-foreground">{f.currency}</span>
              <span className={cn("num font-semibold", f.end >= 0 ? "text-foreground" : "text-negative")}>
                {formatMoney(f.end, f.currency, locale)}
                <span className="ml-1 text-xs text-muted">
                  {f.end >= f.start ? <TrendingUp className="inline h-3 w-3 text-positive" /> : <TrendingDown className="inline h-3 w-3 text-negative" />}
                </span>
              </span>
            </div>
            <MiniLine values={f.points.map((p) => p.balance)} />
            {f.negativeFrom ? (
              <p className="mt-1 flex items-center gap-1.5 text-xs text-negative">
                <AlertTriangle className="h-3.5 w-3.5" />
                {t("runs_low_on", { defaultValue: "Goes negative on {{date}}", date: dayLabel(f.negativeFrom, locale) })}
              </p>
            ) : (
              <p className="num mt-1 text-xs text-muted">
                {t("lowest_point", { defaultValue: "Low: {{amt}}", amt: formatMoney(f.lowest, f.currency, locale) })}
              </p>
            )}
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
