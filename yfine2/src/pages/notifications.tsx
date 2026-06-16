import { AlertTriangle, Bell, CheckCheck, Info, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/cn";
import {
  useDeleteAllRead,
  useDeleteNotification,
  useMarkAllRead,
  useMarkRead,
  useNotifications,
} from "@/db/queries";
import type { NotificationType } from "@/db/repo/notifications";

type Filter = "all" | "unread" | NotificationType;

const ICON: Record<NotificationType, typeof Info> = {
  info: Info,
  alert: Bell,
  warning: AlertTriangle,
};
const TONE: Record<NotificationType, string> = {
  info: "bg-accent-soft text-primary",
  alert: "bg-warning-soft text-warning",
  warning: "bg-negative-soft text-negative",
};

export function NotificationsPage() {
  const { t, i18n } = useTranslation();
  const { data, isLoading } = useNotifications();
  const markRead = useMarkRead();
  const markAll = useMarkAllRead();
  const del = useDeleteNotification();
  const delAllRead = useDeleteAllRead();
  const [filter, setFilter] = useState<Filter>("all");

  const hasUnread = (data ?? []).some((n) => n.is_read === 0);
  const hasRead = (data ?? []).some((n) => n.is_read === 1);

  const filtered = useMemo(() => {
    const all = data ?? [];
    if (filter === "all") return all;
    if (filter === "unread") return all.filter((n) => n.is_read === 0);
    return all.filter((n) => n.type === filter);
  }, [data, filter]);

  const TABS: { key: Filter; label: string }[] = [
    { key: "all", label: t("all", { defaultValue: "All" }) },
    { key: "unread", label: t("unread", { defaultValue: "Unread" }) },
    { key: "alert", label: t("alert", { defaultValue: "Alert" }) },
    { key: "info", label: t("info", { defaultValue: "Info" }) },
    { key: "warning", label: t("warning", { defaultValue: "Warning" }) },
  ];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted">{t("notifications_subtitle", { defaultValue: "Alerts, confirmations and warnings." })}</p>
        <div className="flex items-center gap-2">
          {hasRead && (
            <Button variant="ghost" onClick={() => delAllRead.mutate()}>
              <Trash2 className="h-4 w-4" /> {t("clear_read", { defaultValue: "Clear read" })}
            </Button>
          )}
          {hasUnread && (
            <Button variant="outline" onClick={() => markAll.mutate()}>
              <CheckCheck className="h-4 w-4" /> {t("mark_all_read", { defaultValue: "Mark all read" })}
            </Button>
          )}
        </div>
      </div>

      <div className="flex flex-wrap gap-1.5">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setFilter(tab.key)}
            className={cn(
              "rounded-full px-3 py-1 text-xs font-medium transition-colors",
              filter === tab.key ? "bg-accent-soft text-primary" : "text-muted hover:bg-surface-2 hover:text-foreground",
            )}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {isLoading && <Card className="p-8 text-center text-sm text-muted">{t("loading", { defaultValue: "Loading…" })}</Card>}
      {data && filtered.length === 0 && (
        <Card className="p-10 text-center text-sm text-muted">{t("no_notifications", { defaultValue: "No notifications." })}</Card>
      )}

      <div className="space-y-2">
        {filtered.map((n) => {
          const Icon = ICON[n.type] ?? Info;
          return (
            <Card key={n.id} className={cn("flex items-start gap-3 p-4", n.is_read === 0 && "border-l-2 border-l-primary")}>
              <span className={cn("grid h-9 w-9 shrink-0 place-items-center rounded-[var(--radius-control)]", TONE[n.type] ?? TONE.info)}>
                <Icon className="h-[18px] w-[18px]" />
              </span>
              <div className="min-w-0 flex-1">
                <p className={cn("text-sm", n.is_read === 0 ? "font-semibold text-foreground" : "text-foreground")}>{n.title}</p>
                <p className="text-sm text-muted">{n.body}</p>
                <p className="mt-0.5 text-xs text-muted-2">
                  {new Date(n.created_at).toLocaleString(i18n.resolvedLanguage)}
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-1">
                {n.is_read === 0 && (
                  <button onClick={() => markRead.mutate(n.id)} aria-label={t("mark_read", { defaultValue: "Mark read" })} className="rounded-md p-1.5 text-muted hover:bg-surface-2 hover:text-foreground">
                    <CheckCheck className="h-4 w-4" />
                  </button>
                )}
                <button onClick={() => del.mutate(n.id)} aria-label={t("delete", { defaultValue: "Delete" })} className="rounded-md p-1.5 text-muted hover:bg-negative-soft hover:text-negative">
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            </Card>
          );
        })}
      </div>
    </div>
  );
}
