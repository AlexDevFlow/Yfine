import { useLayoutEffect, useRef, useState, type PointerEvent } from "react";
import { cn } from "@/lib/cn";

export interface ChartPoint {
  date: string;
  value: number;
}

/**
 * Dependency-free interactive line/area chart. Hover (or touch-drag) anywhere
 * to read the date + value at the nearest point via a crosshair + tooltip.
 * Renders in real pixels (ResizeObserver) so the dot stays circular.
 */
export function LineChart({
  points,
  format = (n) => n.toFixed(2),
  formatDate = (d) => d,
  height = 160,
  className,
}: {
  points: ChartPoint[];
  format?: (n: number) => string;
  formatDate?: (d: string) => string;
  height?: number;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(0);
  const [hover, setHover] = useState<number | null>(null);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => setW(entries[0].contentRect.width));
    ro.observe(el);
    setW(el.clientWidth);
    return () => ro.disconnect();
  }, []);

  const padX = 6;
  const padY = 12;
  const n = points.length;
  const min = Math.min(...points.map((p) => p.value));
  const max = Math.max(...points.map((p) => p.value));
  const span = max - min || 1;
  const innerW = Math.max(1, w - padX * 2);
  const innerH = height - padY * 2;

  const x = (i: number) => (n <= 1 ? padX + innerW / 2 : padX + (i / (n - 1)) * innerW);
  const y = (v: number) => padY + innerH - ((v - min) / span) * innerH;

  if (n < 2 || w === 0) {
    // Still mount the ref container so width can be measured on next paint.
    return <div ref={ref} className={className} style={{ height }} />;
  }

  const linePts = points.map((p, i) => `${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join(" ");
  const areaPts = `${padX},${height - padY} ${linePts} ${(padX + innerW).toFixed(1)},${height - padY}`;
  const gid = `lc-${n}-${Math.round(min)}-${Math.round(max)}`;

  const onMove = (e: PointerEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const px = e.clientX - rect.left;
    const i = Math.round(((px - padX) / innerW) * (n - 1));
    setHover(Math.max(0, Math.min(n - 1, i)));
  };

  const hp = hover != null ? points[hover] : null;
  const hx = hover != null ? x(hover) : 0;
  const hy = hp ? y(hp.value) : 0;
  // Keep the tooltip inside the container.
  const tipLeft = Math.max(4, Math.min(w - 4, hx));
  const tipAlign = hx > w * 0.6 ? "translateX(-100%)" : hx < w * 0.4 ? "translateX(0)" : "translateX(-50%)";

  return (
    <div ref={ref} className={cn("relative", className)} style={{ height }}>
      <svg
        width={w}
        height={height}
        className="block touch-none"
        onPointerMove={onMove}
        onPointerDown={onMove}
        onPointerLeave={() => setHover(null)}
      >
        <defs>
          <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--primary)" stopOpacity="0.22" />
            <stop offset="100%" stopColor="var(--primary)" stopOpacity="0" />
          </linearGradient>
        </defs>
        <polyline points={areaPts} fill={`url(#${gid})`} stroke="none" />
        <polyline
          points={linePts}
          fill="none"
          stroke="var(--primary)"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        {hp && (
          <>
            <line x1={hx} y1={padY} x2={hx} y2={height - padY} stroke="var(--border-strong)" strokeWidth="1" strokeDasharray="3 3" />
            <circle cx={hx} cy={hy} r="4" fill="var(--primary)" stroke="var(--surface)" strokeWidth="2" />
          </>
        )}
      </svg>
      {hp && (
        <div
          className="pointer-events-none absolute top-0 z-10 whitespace-nowrap rounded-[var(--radius-control)] border border-border bg-surface px-2 py-1 text-xs shadow-[var(--shadow-pop)]"
          style={{ left: tipLeft, transform: tipAlign }}
        >
          <span className="block text-muted-2">{formatDate(hp.date)}</span>
          <span className="num font-semibold text-foreground">{format(hp.value)}</span>
        </div>
      )}
    </div>
  );
}
