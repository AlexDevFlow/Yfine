import { useNavigate } from "@tanstack/react-router";
import {
  ArrowLeftRight,
  CornerDownLeft,
  Repeat,
  Search,
  Sparkles,
  Tag,
  Target,
  Wallet,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useSearch } from "@/db/queries";
import { SEARCH_ROUTES, type SearchType } from "@/db/repo/search";
import { cn } from "@/lib/cn";
import { ALL_NAV } from "./nav";

const TYPE_ICON: Record<SearchType, LucideIcon> = {
  movement: ArrowLeftRight,
  source: Wallet,
  tag: Tag,
  whim: Sparkles,
  recurring: Repeat,
  goal: Target,
};

interface FlatItem {
  key: string;
  label: string;
  sublabel?: string;
  icon: LucideIcon;
  typeLabel?: string;
  onSelect: () => void;
}

export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  // 220ms debounce (matches legacy)
  useEffect(() => {
    const id = window.setTimeout(() => setDebounced(query), 220);
    return () => window.clearTimeout(id);
  }, [query]);

  const search = useSearch(debounced);

  useEffect(() => {
    if (open) {
      setQuery("");
      setDebounced("");
      setActive(0);
      const id = window.setTimeout(() => inputRef.current?.focus(), 10);
      return () => window.clearTimeout(id);
    }
  }, [open]);

  const go = (to: string) => {
    onClose();
    void navigate({ to });
  };

  const flat = useMemo<FlatItem[]>(() => {
    const q = query.trim().toLowerCase();
    const pages = ALL_NAV.map((i) => ({ ...i, name: t(i.key, { defaultValue: i.label }) }))
      .filter((i) => !q || i.name.toLowerCase().includes(q))
      .map<FlatItem>((i) => ({
        key: `page:${i.to}`,
        label: i.name,
        sublabel: t("page", { defaultValue: "Page" }),
        icon: i.icon,
        onSelect: () => go(i.to),
      }));
    const entities = (search.data ?? []).map<FlatItem>((r) => ({
      key: `${r.type}:${r.id}`,
      label: r.label,
      sublabel: r.sublabel,
      icon: TYPE_ICON[r.type],
      typeLabel: t(r.type, { defaultValue: r.type }),
      onSelect: () => go(SEARCH_ROUTES[r.type]),
    }));
    return [...pages, ...entities];
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, search.data, t]);

  useEffect(() => {
    setActive((a) => Math.min(a, Math.max(0, flat.length - 1)));
  }, [flat.length]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 px-4 pt-[12vh] backdrop-blur-sm"
      onMouseDown={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        className="w-full max-w-lg overflow-hidden rounded-[var(--radius-card)] border border-border bg-surface shadow-[var(--shadow-pop)]"
        onMouseDown={(e) => e.stopPropagation()}
        onKeyDown={(e) => {
          if (e.key === "Escape") onClose();
          else if (e.key === "ArrowDown") {
            e.preventDefault();
            setActive((a) => (a + 1) % Math.max(1, flat.length));
          } else if (e.key === "ArrowUp") {
            e.preventDefault();
            setActive((a) => (a - 1 + flat.length) % Math.max(1, flat.length));
          } else if (e.key === "Enter" && flat[active]) {
            e.preventDefault();
            flat[active].onSelect();
          }
        }}
      >
        <div className="flex items-center gap-2.5 border-b border-border px-4">
          <Search className="h-4 w-4 shrink-0 text-muted" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t("search", { defaultValue: "Search" }) + "…"}
            className="h-12 w-full bg-transparent text-sm outline-none placeholder:text-muted-2"
          />
        </div>
        <ul className="max-h-[340px] overflow-y-auto p-2">
          {flat.length === 0 ? (
            <li className="px-3 py-6 text-center text-sm text-muted">
              {t("no_results", { defaultValue: "No results" })}
            </li>
          ) : (
            flat.map((item, i) => {
              const Icon = item.icon;
              return (
                <li key={item.key}>
                  <button
                    type="button"
                    onMouseEnter={() => setActive(i)}
                    onClick={item.onSelect}
                    className={cn(
                      "flex w-full items-center gap-3 rounded-[var(--radius-control)] px-3 py-2 text-left text-sm",
                      i === active ? "bg-accent-soft text-primary" : "text-foreground",
                    )}
                  >
                    <Icon className="h-[18px] w-[18px] shrink-0 text-muted" />
                    <span className="min-w-0 flex-1 truncate">{item.label}</span>
                    {item.sublabel && <span className="shrink-0 truncate text-xs text-muted-2">{item.sublabel}</span>}
                    {i === active && <CornerDownLeft className="h-3.5 w-3.5 shrink-0 text-muted-2" />}
                  </button>
                </li>
              );
            })
          )}
        </ul>
      </div>
    </div>
  );
}
