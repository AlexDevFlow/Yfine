import { cn } from "@/lib/cn";

/** Yfine wordmark + gradient mark. */
export function Brand({ collapsed = false }: { collapsed?: boolean }) {
  return (
    <div className="flex items-center gap-2.5">
      <div
        className="grid h-8 w-8 shrink-0 place-items-center rounded-[0.6rem] text-[15px] font-bold text-white shadow-sm"
        style={{
          background: "linear-gradient(135deg, #6366f1 0%, #22d3ee 100%)",
        }}
        aria-hidden
      >
        Y
      </div>
      <span
        className={cn(
          "text-[17px] font-semibold tracking-tight text-foreground transition-opacity",
          collapsed && "pointer-events-none w-0 opacity-0",
        )}
      >
        Yfine
      </span>
    </div>
  );
}
