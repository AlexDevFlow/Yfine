import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { LineChart, type ChartPoint } from "@/components/ui/line-chart";
import { cn } from "@/lib/cn";

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

/** LineChart with 30d/90d/1y/all range buttons and client-side slicing. */
export function RangeChart({
  points,
  format,
  formatDate,
  height = 150,
  defaultRange = "1y",
}: {
  points: ChartPoint[];
  format?: (n: number) => string;
  formatDate?: (d: string) => string;
  height?: number;
  defaultRange?: RangeKey;
}) {
  const { t } = useTranslation();
  const [range, setRange] = useState<RangeKey>(defaultRange);
  const series = useMemo(() => {
    const days = RANGES.find((r) => r.key === range)!.days;
    if (days === Infinity) return points;
    const cut = cutoffISO(days);
    const f = points.filter((p) => p.date >= cut);
    return f.length >= 2 ? f : points;
  }, [points, range]);

  return (
    <div>
      <div className="mb-2 flex justify-end gap-1">
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
      <LineChart points={series} height={height} format={format} formatDate={formatDate} />
    </div>
  );
}
