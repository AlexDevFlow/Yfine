/**
 * Settings: the singleton preferences row (id=1), lazily created. Matches the
 * legacy `settings` table exactly (refactor-analysis/settings-i18n.md). Server-side
 * value-domain validation (a gap the old app lacked) keeps bad values out.
 */
import type { SqlExecutor } from "../types";

export type Theme = "light" | "dark" | "system";
export type UiScale = "small" | "normal" | "large" | "xlarge";

export interface SettingsRow {
  id: number;
  locale: string;
  date_format: string;
  base_currency: string | null;
  theme: string;
  hide_net_worth: number;
  last_source_id: number | null;
  mobile_nav_mode: string;
  ui_scale: string;
  hotkeys_enabled: number;
  hotkeys_json: string;
  nav_layout_json: string;
  lan_access: number;
  portfolio_prices_enabled: number;
  portfolio_prices_prompted: number;
  saved_views_json: string;
  movement_templates_json: string;
  created_at: string;
  updated_at: string;
}

const now = () => new Date().toISOString();

const VALID = {
  theme: ["light", "dark", "system"],
  date_format: ["dd/mm/yyyy", "mm/dd/yyyy", "yyyy-mm-dd"],
  ui_scale: ["small", "normal", "large", "xlarge"],
  mobile_nav_mode: ["sidebar", "bottom"],
};

export async function getSettings(db: SqlExecutor): Promise<SettingsRow> {
  const ts = now();
  await db.execute(
    `INSERT OR IGNORE INTO settings
      (id,locale,date_format,base_currency,theme,hide_net_worth,last_source_id,mobile_nav_mode,ui_scale,hotkeys_enabled,hotkeys_json,nav_layout_json,lan_access,portfolio_prices_enabled,portfolio_prices_prompted,saved_views_json,movement_templates_json,created_at,updated_at)
     VALUES (1,'en','dd/mm/yyyy',NULL,'light',0,NULL,'sidebar','normal',1,'{}','[]',0,0,0,'[]','[]',?,?)`,
    [ts, ts],
  );
  return (await db.select<SettingsRow>(`SELECT * FROM settings WHERE id = 1`))[0];
}

export interface SettingsPatch {
  locale?: string;
  date_format?: string;
  base_currency?: string | null;
  theme?: string;
  hide_net_worth?: boolean;
  last_source_id?: number | null;
  mobile_nav_mode?: string;
  ui_scale?: string;
  hotkeys_enabled?: boolean;
  lan_access?: boolean;
  portfolio_prices_enabled?: boolean;
  portfolio_prices_prompted?: boolean;
  saved_views_json?: string;
  movement_templates_json?: string;
  nav_layout_json?: string;
  hotkeys_json?: string;
}

function validate(patch: SettingsPatch): void {
  for (const [k, allowed] of Object.entries(VALID)) {
    const v = (patch as Record<string, unknown>)[k];
    if (v !== undefined && !allowed.includes(v as string)) {
      throw new Error(`invalid ${k}: ${String(v)}`);
    }
  }
}

export async function updateSettings(db: SqlExecutor, patch: SettingsPatch): Promise<SettingsRow> {
  validate(patch);
  await getSettings(db); // ensure the row exists
  const sets: string[] = [];
  const params: unknown[] = [];
  const set = (c: string, v: unknown) => (sets.push(`${c} = ?`), params.push(v));
  const bools = new Set(["hide_net_worth", "hotkeys_enabled", "lan_access", "portfolio_prices_enabled", "portfolio_prices_prompted"]);
  for (const [k, v] of Object.entries(patch)) {
    if (v === undefined) continue;
    set(k, bools.has(k) ? (v ? 1 : 0) : v);
  }
  if (sets.length) {
    set("updated_at", now());
    await db.execute(`UPDATE settings SET ${sets.join(", ")} WHERE id = 1`, params);
  }
  return (await db.select<SettingsRow>(`SELECT * FROM settings WHERE id = 1`))[0];
}
