import { Link, useRouterState } from "@tanstack/react-router";
import { Bell, Search } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Brand } from "./brand";
import { ALL_NAV } from "./nav";
import { ThemeToggle } from "@/components/theme/theme-toggle";
import { useUnreadCount } from "@/db/queries";

function NotificationBell() {
  const { data: unread = 0 } = useUnreadCount();
  return (
    <Link
      to="/notifications"
      aria-label="Notifications"
      className="relative inline-flex h-9 w-9 items-center justify-center rounded-[var(--radius-control)] text-muted transition-colors hover:bg-surface-2 hover:text-foreground"
    >
      <Bell className="h-[18px] w-[18px]" />
      {unread > 0 && (
        <span className="absolute -right-0.5 -top-0.5 grid h-4 min-w-4 place-items-center rounded-full bg-negative px-1 text-[10px] font-semibold text-white">
          {unread > 99 ? "99+" : unread}
        </span>
      )}
    </Link>
  );
}

function usePageTitle(): string {
  const { t } = useTranslation();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const match =
    pathname === "/"
      ? ALL_NAV[0]
      : ALL_NAV.find((i) => i.to !== "/" && pathname.startsWith(i.to));
  if (!match) return "Yfine";
  return t(match.key, { defaultValue: match.label });
}

export function Topbar({ onOpenSearch }: { onOpenSearch: () => void }) {
  const { t } = useTranslation();
  const title = usePageTitle();
  const mod = navigator.platform.toLowerCase().includes("mac") ? "⌘" : "Ctrl";

  return (
    <header className="sticky top-0 z-30 flex h-16 items-center gap-3 border-b border-border bg-background/80 px-4 backdrop-blur-md md:px-6">
      <div className="flex items-center gap-3 md:hidden">
        <Brand />
      </div>
      <h1 className="hidden text-lg font-semibold tracking-tight text-foreground md:block">
        {title}
      </h1>

      <div className="flex flex-1 justify-end md:justify-center">
        <button
          type="button"
          onClick={onOpenSearch}
          className="group flex h-9 w-full max-w-sm items-center gap-2.5 rounded-[var(--radius-control)] border border-border bg-surface px-3 text-sm text-muted transition-colors hover:border-border-strong"
        >
          <Search className="h-4 w-4" />
          <span className="flex-1 text-left">{t("search", { defaultValue: "Search" })}…</span>
          <kbd className="hidden rounded border border-border bg-surface-2 px-1.5 py-0.5 text-[11px] font-medium text-muted-2 sm:inline">
            {mod} K
          </kbd>
        </button>
      </div>

      <div className="flex items-center gap-1">
        <NotificationBell />
        <ThemeToggle />
      </div>
    </header>
  );
}
