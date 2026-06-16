import { Outlet } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { BottomNav } from "./bottom-nav";
import { CommandPalette } from "./command-palette";
import { Sidebar } from "./sidebar";
import { Topbar } from "./topbar";
import { usePreferences } from "@/db/queries";
import { applyUiScale } from "@/lib/ui-scale";

export function AppShell() {
  const [collapsed, setCollapsed] = useState(
    () => localStorage.getItem("yfine.sidebar") === "1",
  );
  const [searchOpen, setSearchOpen] = useState(false);

  // Apply the saved interface-size preference once it loads from the DB.
  const { data: prefs } = usePreferences();
  useEffect(() => {
    if (prefs?.ui_scale) applyUiScale(prefs.ui_scale);
  }, [prefs?.ui_scale]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setSearchOpen((o) => !o);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const toggle = () =>
    setCollapsed((c) => {
      const next = !c;
      localStorage.setItem("yfine.sidebar", next ? "1" : "0");
      return next;
    });

  return (
    <div className="flex h-full overflow-hidden">
      <Sidebar collapsed={collapsed} onToggle={toggle} />
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar onOpenSearch={() => setSearchOpen(true)} />
        <main className="flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-[1200px] p-4 md:p-6">
            <Outlet />
          </div>
        </main>
        <BottomNav />
      </div>
      <CommandPalette open={searchOpen} onClose={() => setSearchOpen(false)} />
    </div>
  );
}
