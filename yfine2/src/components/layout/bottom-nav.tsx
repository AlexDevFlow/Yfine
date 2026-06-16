import { Link, useRouterState } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/cn";
import { MOBILE_NAV } from "./nav";

export function BottomNav() {
  const { t } = useTranslation();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  return (
    <nav className="flex shrink-0 items-stretch border-t border-border bg-surface md:hidden">
      {MOBILE_NAV.map((item) => {
        const active = item.to === "/" ? pathname === "/" : pathname.startsWith(item.to);
        const Icon = item.icon;
        return (
          <Link
            key={item.to}
            to={item.to}
            className={cn(
              "flex flex-1 flex-col items-center gap-1 py-2 text-[11px] font-medium transition-colors",
              active ? "text-primary" : "text-muted",
            )}
          >
            <Icon className="h-5 w-5" />
            {t(item.key, { defaultValue: item.label })}
          </Link>
        );
      })}
    </nav>
  );
}
