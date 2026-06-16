import { LineChart as LineChartIcon, PiggyBank, Plus, Trash2 } from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { BalanceHistoryChart } from "@/components/ui/balance-history-chart";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field, Input, Select } from "@/components/ui/input";
import { Modal } from "@/components/ui/modal";
import { SlotMoney } from "@/components/ui/slot";
import { isPreviewDb } from "@/db/connection";
import {
  useCreateSaving,
  useDeleteSaving,
  useSavings,
  useSources,
  useTags,
  type SourceWithBalance,
} from "@/db/queries";
import type { EnrichedSaving, NewSaving } from "@/db/repo/savings";
import type { TagRow } from "@/db/schema-types";
import { round2 } from "@/domain/money";
import { cn } from "@/lib/cn";
import { dayLabel, monthLabel, todayISO } from "@/lib/date";
import { formatMoney } from "@/lib/format";
import { useErrorText } from "@/lib/use-error-text";

/** Fund balance card with an expandable balance-over-time chart. */
function FundCard({ fund, locale }: { fund: SourceWithBalance; locale?: string }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  return (
    <Card className="overflow-hidden">
      <div className="flex items-center gap-3 p-4">
        <span className="grid h-10 w-10 shrink-0 place-items-center rounded-[var(--radius-control)] bg-accent-soft text-primary">
          <PiggyBank className="h-5 w-5" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-xs text-muted">{fund.name} · {fund.currency}</p>
          <SlotMoney value={fund.balance} text={formatMoney(fund.balance, fund.currency, locale)} className="num text-xl font-semibold text-foreground" />
        </div>
        <button
          onClick={() => setOpen((o) => !o)}
          aria-label={t("history", { defaultValue: "History" })}
          aria-expanded={open}
          className={cn("rounded-md p-2 hover:bg-surface-2 hover:text-foreground", open ? "text-primary" : "text-muted")}
        >
          <LineChartIcon className="h-4 w-4" />
        </button>
      </div>
      {open && (
        <div className="border-t border-border pt-2">
          <BalanceHistoryChart sourceId={fund.id} currency={fund.currency} locale={locale} />
        </div>
      )}
    </Card>
  );
}

function TagChips({ tags, selected, onChange }: { tags: TagRow[]; selected: number[]; onChange: (ids: number[]) => void }) {
  if (tags.length === 0) return null;
  const toggle = (id: number) => onChange(selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id]);
  return (
    <div className="flex flex-wrap gap-1.5">
      {tags.map((t) => {
        const on = selected.includes(t.id);
        return (
          <button
            type="button"
            key={t.id}
            onClick={() => toggle(t.id)}
            className={cn(
              "rounded-full border px-2.5 py-1 text-xs font-medium transition-colors",
              on ? "border-primary bg-accent-soft text-primary" : "border-border text-muted hover:text-foreground",
            )}
          >
            <span className="mr-1 inline-block h-2 w-2 rounded-full align-middle" style={{ background: t.color ?? "var(--muted-2)" }} />
            {t.name}
          </button>
        );
      })}
    </div>
  );
}

function SavingForm({ sources, tags, onCancel, onSubmit, pending, error }: {
  sources: SourceWithBalance[];
  tags: TagRow[];
  onCancel: () => void;
  onSubmit: (v: NewSaving) => void;
  pending: boolean;
  error?: string;
}) {
  const { t } = useTranslation();
  // Funds can't fund a saving — only regular accounts.
  const accounts = sources.filter((s) => s.is_savings_fund === 0);
  const [fromSourceId, setFromSourceId] = useState(String(accounts[0]?.id ?? ""));
  const [amount, setAmount] = useState("");
  const [date, setDate] = useState(todayISO());
  const [note, setNote] = useState("");
  const [tagIds, setTagIds] = useState<number[]>([]);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    onSubmit({ fromSourceId: Number(fromSourceId), amount: Number(amount) || 0, date, note: note || null, tagIds });
  };

  return (
    <form onSubmit={submit} className="space-y-4">
      <Field label={t("from", { defaultValue: "From" })} htmlFor="sv-src">
        <Select id="sv-src" value={fromSourceId} onChange={(e) => setFromSourceId(e.target.value)} required>
          {accounts.map((s) => (
            <option key={s.id} value={s.id}>{s.name} · {formatMoney(s.balance, s.currency)}</option>
          ))}
        </Select>
      </Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label={t("amount", { defaultValue: "Amount" })} htmlFor="sv-amt">
          <Input id="sv-amt" type="number" step="0.01" min="0.01" value={amount} onChange={(e) => setAmount(e.target.value)} required autoFocus className="num" />
        </Field>
        <Field label={t("date", { defaultValue: "Date" })} htmlFor="sv-date">
          <Input id="sv-date" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
        </Field>
      </div>
      <Field label={t("note", { defaultValue: "Note" })} htmlFor="sv-note">
        <Input id="sv-note" value={note} onChange={(e) => setNote(e.target.value)} />
      </Field>
      {tags.length > 0 && <TagChips tags={tags} selected={tagIds} onChange={setTagIds} />}
      <p className="text-xs text-muted">{t("saving_fund_hint", { defaultValue: "Money moves into your savings fund for that currency — your net worth is unchanged." })}</p>
      {accounts.length === 0 && <p className="text-xs text-warning">{t("no_accounts", { defaultValue: "Add a regular account first." })}</p>}
      {error ? <p className="text-sm text-negative">{error}</p> : null}
      <div className="flex justify-end gap-2 pt-1">
        <Button type="button" variant="ghost" onClick={onCancel}>{t("cancel", { defaultValue: "Cancel" })}</Button>
        <Button type="submit" disabled={pending || !fromSourceId || !amount}>{t("save", { defaultValue: "Save" })}</Button>
      </div>
    </form>
  );
}

export function SavingsPage() {
  const { t, i18n } = useTranslation();
  const locale = i18n.resolvedLanguage;
  const errText = useErrorText();
  const { data: savings, isLoading } = useSavings();
  const { data: sources } = useSources();
  const { data: tags } = useTags();
  const create = useCreateSaving();
  const del = useDeleteSaving();

  const [form, setForm] = useState(false);
  const [formError, setFormError] = useState<string>();

  const funds = (sources ?? []).filter((s) => s.is_savings_fund === 1 && s.balance !== 0);

  // Group deposits by month (newest first) with per-currency month totals.
  const months = useMemo(() => {
    const out: { ym: string; items: EnrichedSaving[]; totals: Map<string, number> }[] = [];
    for (const s of savings ?? []) {
      const ym = s.date.slice(0, 7);
      let g = out[out.length - 1];
      if (!g || g.ym !== ym) {
        g = { ym, items: [], totals: new Map() };
        out.push(g);
      }
      g.items.push(s);
      g.totals.set(s.currency, round2((g.totals.get(s.currency) ?? 0) + s.amount));
    }
    return out;
  }, [savings]);

  const submit = (v: NewSaving) => {
    setFormError(undefined);
    create.mutate(v, { onSuccess: () => setForm(false), onError: (e) => setFormError(errText(e)) });
  };

  const remove = (id: number) => {
    if (window.confirm(t("delete_saving_confirm", { defaultValue: "Delete this saving? The money is refunded to the source account." }))) {
      del.mutate(id);
    }
  };

  return (
    <div className="space-y-4">
      {isPreviewDb && (
        <div className="rounded-[var(--radius-control)] border border-border bg-warning-soft px-3 py-2 text-xs text-warning">
          {t("preview_db_note", { defaultValue: "Browser preview with seeded sample data." })}
        </div>
      )}
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted">{t("savings_subtitle", { defaultValue: "Set money aside into a savings fund — conserving, not spending." })}</p>
        <Button onClick={() => { setFormError(undefined); setForm(true); }}>
          <Plus className="h-4 w-4" /> {t("new_saving", { defaultValue: "New Saving" })}
        </Button>
      </div>

      {funds.length > 0 && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {funds.map((f) => (
            <FundCard key={f.id} fund={f} locale={locale} />
          ))}
        </div>
      )}

      {isLoading && <Card className="p-8 text-center text-sm text-muted">{t("loading", { defaultValue: "Loading…" })}</Card>}
      {savings && savings.length === 0 && (
        <Card className="p-10 text-center text-sm text-muted">{t("no_savings", { defaultValue: "No savings logged yet. Start tracking what you save!" })}</Card>
      )}

      {months.length > 0 && (
        <div className="space-y-3">
          {months.map((g) => (
            <Card key={g.ym} className="overflow-hidden">
              <div className="flex items-center justify-between border-b border-border bg-surface-2/40 px-4 py-2.5">
                <h3 className="text-sm font-semibold text-foreground">{monthLabel(g.ym, locale)}</h3>
                <div className="flex items-center gap-2 text-xs">
                  {[...g.totals.entries()].map(([ccy, total]) => (
                    <span key={ccy} className="num text-positive">+{formatMoney(total, ccy, locale)}</span>
                  ))}
                </div>
              </div>
              <ul className="divide-y divide-border">
                {g.items.map((s) => (
                  <li key={s.id} className="flex items-center justify-between gap-3 px-4 py-3">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium text-foreground">
                        {s.from_source_name ?? t("deleted", { defaultValue: "Deleted" })}
                        {s.note && <span className="text-muted"> · {s.note}</span>}
                      </p>
                      <div className="mt-0.5 flex items-center gap-2 text-xs text-muted">
                        <span>{dayLabel(s.date, locale)}</span>
                        {s.tags.map((tag) => (
                          <span key={tag.id} className="inline-flex items-center">
                            <span className="mr-0.5 inline-block h-1.5 w-1.5 rounded-full align-middle" style={{ background: tag.color ?? "var(--muted-2)" }} />
                            {tag.name}
                          </span>
                        ))}
                      </div>
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                      <span className="num text-sm font-semibold text-positive">{formatMoney(s.amount, s.currency, locale)}</span>
                      <button onClick={() => remove(s.id)} className="rounded-md p-1.5 text-muted hover:bg-negative-soft hover:text-negative" aria-label={t("delete", { defaultValue: "Delete" })}>
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            </Card>
          ))}
        </div>
      )}

      <Modal open={form} onClose={() => setForm(false)} title={t("new_saving", { defaultValue: "New Saving" })}>
        <SavingForm sources={sources ?? []} tags={tags ?? []} pending={create.isPending} error={formError} onCancel={() => setForm(false)} onSubmit={submit} />
      </Modal>
    </div>
  );
}
