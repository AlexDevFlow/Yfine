import { Download, FileSpreadsheet, FileJson, Monitor, Moon, Sun, Upload, FileUp } from "lucide-react";
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Field, Select } from "@/components/ui/input";
import { Slot } from "@/components/ui/slot";
import { useTheme, type Theme } from "@/components/theme/theme-provider";
import { SUPPORTED_LANGS } from "@/i18n";
import { getDb, isPreviewDb } from "@/db/connection";
import { exportArchive, exportJson, exportMovementsCsv } from "@/db/backup";
import { previewCsv, type PreviewResult } from "@/db/importers/csv";
import { useCommitCsv, useImportBackup, usePreferences, useSources, useUpdatePreferences } from "@/db/queries";
import { cn } from "@/lib/cn";
import { todayISO } from "@/lib/date";
import { downloadBytes, downloadText } from "@/lib/download";
import { formatMoney } from "@/lib/format";
import { applyUiScale } from "@/lib/ui-scale";
import { useErrorText } from "@/lib/use-error-text";

const THEME_OPTS: { value: Theme; icon: typeof Sun; label: string }[] = [
  { value: "light", icon: Sun, label: "Light" },
  { value: "dark", icon: Moon, label: "Dark" },
  { value: "system", icon: Monitor, label: "System" },
];

function PreferencesCard() {
  const { t, i18n } = useTranslation();
  const { theme, setTheme } = useTheme();
  const { data: prefs } = usePreferences();
  const update = useUpdatePreferences();

  return (
    <Card>
      <CardHeader title={t("preferences", { defaultValue: "Preferences" })} subtitle={t("preferences_hint", { defaultValue: "Appearance and locale." })} />
      <CardContent className="space-y-4 pt-3">
        <Field label={t("theme", { defaultValue: "Theme" })}>
          <div className="flex gap-2">
            {THEME_OPTS.map((o) => {
              const Icon = o.icon;
              return (
                <button key={o.value} type="button"
                  onClick={() => { setTheme(o.value); update.mutate({ theme: o.value }); }}
                  className={cn("flex h-9 items-center gap-1.5 rounded-[var(--radius-control)] border px-3 text-sm", theme === o.value ? "border-primary bg-accent-soft text-primary" : "border-border text-muted hover:text-foreground")}>
                  <Icon className="h-4 w-4" /> {t(`theme_${o.value}`, { defaultValue: o.label })}
                </button>
              );
            })}
          </div>
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label={t("language", { defaultValue: "Language" })} htmlFor="pref-lang">
            <Select id="pref-lang" value={i18n.resolvedLanguage} onChange={(e) => { void i18n.changeLanguage(e.target.value); update.mutate({ locale: e.target.value }); }}>
              {SUPPORTED_LANGS.map((l) => <option key={l.code} value={l.code}>{l.label}</option>)}
            </Select>
          </Field>
          <Field label={t("interface_size", { defaultValue: "Interface size" })} htmlFor="pref-scale">
            <Select id="pref-scale" value={prefs?.ui_scale ?? "normal"} onChange={(e) => { applyUiScale(e.target.value); update.mutate({ ui_scale: e.target.value }); }}>
              <option value="small">{t("scale_small", { defaultValue: "Compact" })}</option>
              <option value="normal">{t("scale_normal", { defaultValue: "Normal" })}</option>
              <option value="large">{t("scale_large", { defaultValue: "Large" })}</option>
              <option value="xlarge">{t("scale_xlarge", { defaultValue: "Extra large" })}</option>
            </Select>
          </Field>
        </div>
        <label className="flex items-center gap-2 text-sm text-foreground">
          <input type="checkbox" checked={(prefs?.hide_net_worth ?? 0) === 1} onChange={(e) => update.mutate({ hide_net_worth: e.target.checked })} />
          {t("hide_net_worth", { defaultValue: "Hide net worth by default" })}
        </label>
        <label className="flex items-center gap-2 text-sm text-foreground">
          <input type="checkbox" checked={(prefs?.portfolio_prices_enabled ?? 0) === 1} onChange={(e) => update.mutate({ portfolio_prices_enabled: e.target.checked, portfolio_prices_prompted: true })} />
          {t("enable_live_prices", { defaultValue: "Enable live portfolio prices (opt-in)" })}
        </label>
      </CardContent>
    </Card>
  );
}

function ExportCard() {
  const { t } = useTranslation();
  const [busy, setBusy] = useState(false);
  const run = async (fn: () => Promise<void>) => { setBusy(true); try { await fn(); } finally { setBusy(false); } };
  return (
    <Card>
      <CardHeader title={t("export_data", { defaultValue: "Export" })} subtitle={t("export_hint", { defaultValue: "Download a full backup or a spreadsheet." })} />
      <CardContent className="flex flex-wrap gap-2 pt-3">
        <Button variant="outline" disabled={busy} onClick={() => run(async () => downloadBytes(`yfine-export-${todayISO()}.yfine`, await exportArchive(await getDb(), new Date().toISOString()), "application/zip"))}>
          <Download className="h-4 w-4" /> {t("export_archive", { defaultValue: ".yfine archive" })}
        </Button>
        <Button variant="outline" disabled={busy} onClick={() => run(async () => downloadText(`yfine-export-${todayISO()}.json`, await exportJson(await getDb()), "application/json"))}>
          <FileJson className="h-4 w-4" /> JSON
        </Button>
        <Button variant="outline" disabled={busy} onClick={() => run(async () => downloadText(`yfine-movements-${todayISO()}.csv`, await exportMovementsCsv(await getDb()), "text/csv"))}>
          <FileSpreadsheet className="h-4 w-4" /> {t("movements_csv", { defaultValue: "Movements CSV" })}
        </Button>
      </CardContent>
    </Card>
  );
}

function RestoreCard() {
  const { t } = useTranslation();
  const errText = useErrorText();
  const importBackup = useImportBackup();
  const fileRef = useRef<HTMLInputElement>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string }>();

  const onFile = async (file: File) => {
    if (!window.confirm(t("restore_confirm", { defaultValue: "Restoring replaces ALL current data. Continue?" }))) return;
    const bytes = new Uint8Array(await file.arrayBuffer());
    importBackup.mutate(bytes, {
      onSuccess: () => setMsg({ ok: true, text: t("restore_ok", { defaultValue: "Backup restored." }) }),
      onError: (e) => setMsg({ ok: false, text: errText(e) }),
    });
  };

  return (
    <Card>
      <CardHeader title={t("restore_data", { defaultValue: "Restore" })} subtitle={t("restore_hint", { defaultValue: "Import a .yfine archive or JSON backup (replaces everything)." })} />
      <CardContent className="pt-3">
        <input ref={fileRef} type="file" accept=".yfine,.json,application/zip,application/json" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) void onFile(f); e.target.value = ""; }} />
        <Button variant="outline" disabled={importBackup.isPending} onClick={() => fileRef.current?.click()}>
          <Upload className="h-4 w-4" />{" "}
          <Slot
            text={importBackup.isPending ? t("restoring", { defaultValue: "Restoring…" }) : t("choose_backup", { defaultValue: "Choose backup file" })}
            options={{ direction: importBackup.isPending ? "up" : "down" }}
          />
        </Button>
        {msg && <p className={cn("mt-2 text-sm", msg.ok ? "text-positive" : "text-negative")}>{msg.text}</p>}
      </CardContent>
    </Card>
  );
}

function CsvImportCard() {
  const { t, i18n } = useTranslation();
  const errText = useErrorText();
  const { data: sources } = useSources();
  const commit = useCommitCsv();
  const fileRef = useRef<HTMLInputElement>(null);
  const [text, setText] = useState<string>();
  const [sourceId, setSourceId] = useState<string>("");
  const [preview, setPreview] = useState<PreviewResult>();
  const [result, setResult] = useState<string>();
  const [busy, setBusy] = useState(false);

  const doPreview = async (csv: string, sid: string) => {
    setBusy(true);
    setResult(undefined);
    try {
      const p = await previewCsv(await getDb(), csv, { sourceId: sid ? Number(sid) : null });
      setPreview(p);
    } catch (e) {
      setResult(errText(e));
    } finally {
      setBusy(false);
    }
  };

  const onFile = async (file: File) => {
    const csv = await file.text();
    setText(csv);
    setPreview(undefined);
    await doPreview(csv, sourceId);
  };

  const doImport = () => {
    if (!preview || !sourceId) return;
    const rows = preview.rows.filter((r) => !r.isDuplicate).map(({ index, isDuplicate, ...m }) => { void index; void isDuplicate; return m; });
    commit.mutate(
      { movements: rows, sourceId: Number(sourceId) },
      {
        onSuccess: (r) => { setResult(t("csv_imported", { defaultValue: "Imported {{n}}, skipped {{s}}.", n: r.imported, s: r.skipped }) + (r.currencyWarning ? ` ${r.currencyWarning}` : "")); setPreview(undefined); setText(undefined); },
        onError: (e) => setResult(errText(e)),
      },
    );
  };

  return (
    <Card>
      <CardHeader title={t("import_csv", { defaultValue: "Import transactions (CSV)" })} subtitle={t("import_csv_hint", { defaultValue: "Bank/app CSV export — presets for Revolut, N26, YNAB, PayPal, Firefly." })} />
      <CardContent className="space-y-3 pt-3">
        <div className="flex flex-wrap items-end gap-2">
          <Field label={t("target_account", { defaultValue: "Into account" })} htmlFor="csv-src">
            <Select id="csv-src" value={sourceId} onChange={(e) => { setSourceId(e.target.value); if (text) void doPreview(text, e.target.value); }} className="min-w-[200px]">
              <option value="">{t("select_account", { defaultValue: "Select an account…" })}</option>
              {(sources ?? []).map((s) => <option key={s.id} value={s.id}>{s.name} · {s.currency}</option>)}
            </Select>
          </Field>
          <input ref={fileRef} type="file" accept=".csv,text/csv" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) void onFile(f); e.target.value = ""; }} />
          <Button variant="outline" disabled={busy} onClick={() => fileRef.current?.click()}><FileUp className="h-4 w-4" /> {t("choose_csv", { defaultValue: "Choose CSV" })}</Button>
        </div>

        {preview?.needsMapping && <p className="text-sm text-warning">{t("needs_mapping", { defaultValue: "Couldn't auto-detect columns for this file." })}</p>}

        {preview && !preview.needsMapping && (
          <>
            <div className="flex flex-wrap gap-4 text-sm">
              <span className="text-muted">{t("rows", { defaultValue: "Rows" })}: <b className="text-foreground">{preview.rows.length}</b></span>
              <span className="num text-positive">+{preview.totalIn}</span>
              <span className="num text-negative">−{preview.totalOut}</span>
              {preview.duplicateCount > 0 && <span className="text-warning">{t("duplicates", { defaultValue: "Duplicates" })}: {preview.duplicateCount}</span>}
              {preview.preset && <span className="text-muted">{t("preset", { defaultValue: "Preset" })}: {preview.preset.display_name}</span>}
            </div>
            <div className="max-h-64 overflow-y-auto rounded-[var(--radius-control)] border border-border">
              <table className="w-full text-sm">
                <tbody>
                  {preview.rows.slice(0, 100).map((r) => (
                    <tr key={r.index} className={cn("border-b border-border last:border-0", r.isDuplicate && "opacity-40")}>
                      <td className="px-3 py-1.5 text-muted">{r.date}</td>
                      <td className="px-3 py-1.5 truncate">{r.note}</td>
                      <td className={cn("num px-3 py-1.5 text-right", r.direction === "in" ? "text-positive" : "text-foreground")}>{r.direction === "in" ? "+" : "−"}{formatMoney(r.amount, r.currency ?? "", i18n.resolvedLanguage).replace(/[^\d.,\s-]/g, "").trim() || r.amount}</td>
                      <td className="px-2 py-1.5 text-xs text-muted-2">{r.isDuplicate ? t("dup", { defaultValue: "dup" }) : ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Button disabled={!sourceId || commit.isPending} onClick={doImport}>
              {t("import_n", { defaultValue: "Import {{n}}", n: preview.rows.filter((r) => !r.isDuplicate).length })}
            </Button>
            {!sourceId && <p className="text-xs text-muted">{t("pick_account_first", { defaultValue: "Pick an account to import into." })}</p>}
          </>
        )}
        {result && <p className="text-sm text-foreground">{result}</p>}
      </CardContent>
    </Card>
  );
}

export function SettingsPage() {
  const { t } = useTranslation();
  return (
    <div className="space-y-4">
      {isPreviewDb && <div className="rounded-[var(--radius-control)] border border-border bg-warning-soft px-3 py-2 text-xs text-warning">{t("preview_db_note", { defaultValue: "Browser preview with seeded sample data — changes are in-memory only." })}</div>}
      <p className="text-sm text-muted">{t("settings_hint", { defaultValue: "Preferences, backup, restore, and import." })}</p>
      <PreferencesCard />
      <ExportCard />
      <RestoreCard />
      <CsvImportCard />
    </div>
  );
}
