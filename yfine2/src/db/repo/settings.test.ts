import { describe, it, expect } from "vitest";
import { makeMemDb } from "@/test/sqlite";
import { getSettings, updateSettings } from "./settings";

describe("settings repo", () => {
  it("lazily creates the singleton row with defaults", async () => {
    const { db } = await makeMemDb();
    const s = await getSettings(db);
    expect(s.id).toBe(1);
    expect(s.locale).toBe("en");
    expect(s.theme).toBe("light");
    expect(s.ui_scale).toBe("normal");
    // idempotent
    await getSettings(db);
    const c = await db.select<{ c: number }>(`SELECT COUNT(*) c FROM settings`);
    expect(c[0].c).toBe(1);
  });

  it("updates preferences and coerces booleans", async () => {
    const { db } = await makeMemDb();
    const s = await updateSettings(db, { theme: "dark", hide_net_worth: true, portfolio_prices_enabled: true, ui_scale: "large" });
    expect(s.theme).toBe("dark");
    expect(s.hide_net_worth).toBe(1);
    expect(s.portfolio_prices_enabled).toBe(1);
    expect(s.ui_scale).toBe("large");
  });

  it("rejects invalid value domains", async () => {
    const { db } = await makeMemDb();
    await expect(updateSettings(db, { theme: "neon" })).rejects.toBeTruthy();
    await expect(updateSettings(db, { ui_scale: "huge" })).rejects.toBeTruthy();
  });
});
