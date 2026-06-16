import { CheckCircle2, Pencil, Plus, Repeat, Trash2 } from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Field, Input, Select } from "@/components/ui/input";
import { Modal } from "@/components/ui/modal";
import { isPreviewDb } from "@/db/connection";
import {
  useApplyRecurring,
  useCreateRecurring,
  useDeleteRecurring,
  useRecurring,
  useSources,
  useUpdateRecurring,
} from "@/db/queries";
import type { EnrichedRecurring, NewRecurring } from "@/db/repo/recurring";
import { cn } from "@/lib/cn";
import { dayLabel, todayISO } from "@/lib/date";
import { formatSigned } from "@/lib/format";
import { useErrorText } from "@/lib/use-error-text";
import type { SourceWithBalance } from "@/db/queries";

const FREQUENCIES = ["daily", "weekly", "monthly", "yearly"] as const;

function RecurringForm({
  initial,
  sources,
  onCancel,
  onSubmit,
  pending,
  error,
}: {
  initial?: EnrichedRecurring;
  sources: SourceWithBalance[];
  onCancel: () => void;
  onSubmit: (v: NewRecurring) => void;
  pending: boolean;
  error?: string;
}) {
  const { t } = useTranslation();
  const [name, setName] = useState(initial?.name ?? "");
  const [amount, setAmount] = useState(initial ? String(initial.amount) : "");
  const [direction, setDirection] = useState<"in" | "out">(initial?.direction ?? "out");
  const [sourceId, setSourceId] = useState<string>(initial?.source_id != null ? String(initial.source_id) : "");
  const [currency, setCurrency] = useState(initial?.currency ?? "EUR");
  const [frequency, setFrequency] = useState(initial?.frequency ?? "monthly");
  const [start, setStart] = useState(initial?.start_date ?? todayISO());
  const [end, setEnd] = useState(initial?.end_date ?? "");
  const [mode, setMode] = useState<"auto" | "confirm">(initial?.apply_mode ?? "confirm");
  const [alertDays, setAlertDays] = useState(String(initial?.alert_days_before ?? 7));
  const [alertInsufficient, setAlertInsufficient] = useState((initial?.alert_if_insufficient ?? 1) === 1);

  const selectedSource = sources.find((s) => s.id === Number(sourceId));
  const effectiveCurrency = selectedSource ? selectedSource.currency : currency.trim().toUpperCase();

  const submit = (e: FormEvent) => {
    e.preventDefault();
    onSubmit({
      name: name.trim(),
      amount: Number(amount) || 0,
      direction,
      currency: effectiveCurrency,
      frequency,
      start_date: start,
      end_date: end || null,
      source_id: sourceId === "" ? null : Number(sourceId),
      apply_mode: mode,
      alert_days_before: Number(alertDays) || 0,
      alert_if_insufficient: alertInsufficient,
    });
  };

  return (
    <form onSubmit={submit} className="space-y-4">
      <Field label={t("name", { defaultValue: "Name" })} htmlFor="rc-name">
        <Input id="rc-name" value={name} onChange={(e) => setName(e.target.value)} required autoFocus />
      </Field>
      <div className="grid grid-cols-2 gap-2">
        {(["out", "in"] as const).map((d) => (
          <button type="button" key={d} onClick={() => setDirection(d)}
            className={cn("h-10 rounded-[var(--radius-control)] border text-sm font-medium transition-colors",
              direction === d ? (d === "in" ? "border-positive bg-positive-soft text-positive" : "border-negative bg-negative-soft text-negative") : "border-border text-muted hover:text-foreground")}>
            {d === "in" ? t("income", { defaultValue: "Income" }) : t("expense", { defaultValue: "Expense" })}
          </button>
        ))}
      </div>
      <div className="grid grid-cols-2 gap-3">
        <Field label={t("amount", { defaultValue: "Amount" })} htmlFor="rc-amt">
          <Input id="rc-amt" type="number" step="0.01" min="0.01" value={amount} onChange={(e) => setAmount(e.target.value)} required className="num" />
        </Field>
        <Field label={t("frequency", { defaultValue: "Frequency" })} htmlFor="rc-freq">
          <Select id="rc-freq" value={frequency} onChange={(e) => setFrequency(e.target.value)}>
            {FREQUENCIES.map((f) => <option key={f} value={f}>{t(`freq_${f}`, { defaultValue: f })}</option>)}
          </Select>
        </Field>
      </div>
      <Field label={t("source", { defaultValue: "Source" })} htmlFor="rc-src">
        <Select id="rc-src" value={sourceId} onChange={(e) => setSourceId(e.target.value)}>
          <option value="">{t("external", { defaultValue: "External (no account)" })}</option>
          {sources.map((s) => <option key={s.id} value={s.id}>{s.name} · {s.currency}</option>)}
        </Select>
      </Field>
      {!selectedSource && (
        <Field label={t("currency", { defaultValue: "Currency" })} htmlFor="rc-ccy">
          <Input id="rc-ccy" value={currency} onChange={(e) => setCurrency(e.target.value.toUpperCase())} maxLength={5} />
        </Field>
      )}
      <div className="grid grid-cols-2 gap-3">
        <Field label={t("start_date", { defaultValue: "Start date" })} htmlFor="rc-start">
          <Input id="rc-start" type="date" value={start} onChange={(e) => setStart(e.target.value)} required />
        </Field>
        <Field label={t("end_date_optional", { defaultValue: "End date (optional)" })} htmlFor="rc-end">
          <Input id="rc-end" type="date" value={end} onChange={(e) => setEnd(e.target.value)} />
        </Field>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <Field label={t("apply_mode", { defaultValue: "When due" })} htmlFor="rc-mode">
          <Select id="rc-mode" value={mode} onChange={(e) => setMode(e.target.value as "auto" | "confirm")}>
            <option value="confirm">{t("mode_confirm", { defaultValue: "Ask me to confirm" })}</option>
            <option value="auto">{t("mode_auto", { defaultValue: "Apply automatically" })}</option>
          </Select>
        </Field>
        <Field label={t("alert_days", { defaultValue: "Remind days before" })} htmlFor="rc-alert">
          <Input id="rc-alert" type="number" min="0" max="365" value={alertDays} onChange={(e) => setAlertDays(e.target.value)} className="num" />
        </Field>
      </div>
      {direction === "out" && (
        <label className="flex items-center gap-2 text-sm text-foreground">
          <input type="checkbox" checked={alertInsufficient} onChange={(e) => setAlertInsufficient(e.target.checked)} />
          {t("alert_insufficient", { defaultValue: "Warn me if the balance is too low" })}
        </label>
      )}
      {error ? <p className="text-sm text-negative">{error}</p> : null}
      <div className="flex justify-end gap-2 pt-1">
        <Button type="button" variant="ghost" onClick={onCancel}>{t("cancel", { defaultValue: "Cancel" })}</Button>
        <Button type="submit" disabled={pending || !name.trim() || !amount}>{t("save", { defaultValue: "Save" })}</Button>
      </div>
    </form>
  );
}

export function RecurringPage() {
  const { t, i18n } = useTranslation();
  const locale = i18n.resolvedLanguage;
  const errText = useErrorText();
  const { data, isLoading } = useRecurring();
  const { data: sources } = useSources();
  const create = useCreateRecurring();
  const update = useUpdateRecurring();
  const del = useDeleteRecurring();
  const apply = useApplyRecurring();

  const [modal, setModal] = useState<{ open: boolean; editing?: EnrichedRecurring }>({ open: false });
  const [formError, setFormError] = useState<string>();
  const [dirFilter, setDirFilter] = useState<"all" | "in" | "out">("all");
  const [freqFilter, setFreqFilter] = useState<string>("all");

  const summaryChips = useMemo(() => Object.entries(data?.summary.byCurrency ?? {}), [data]);
  const items = useMemo(() => {
    let list = data?.items ?? [];
    if (dirFilter !== "all") list = list.filter((r) => r.direction === dirFilter);
    if (freqFilter !== "all") list = list.filter((r) => r.frequency === freqFilter);
    return list;
  }, [data, dirFilter, freqFilter]);

  const submit = (v: NewRecurring) => {
    setFormError(undefined);
    const onErr = (e: unknown) => setFormError(errText(e));
    if (modal.editing) update.mutate({ id: modal.editing.id, patch: v }, { onSuccess: () => setModal({ open: false }), onError: onErr });
    else create.mutate(v, { onSuccess: () => setModal({ open: false }), onError: onErr });
  };

  return (
    <div className="space-y-4">
      {isPreviewDb && (
        <div className="rounded-[var(--radius-control)] border border-border bg-warning-soft px-3 py-2 text-xs text-warning">
          {t("preview_db_note", { defaultValue: "Browser preview with seeded sample data (in-memory)." })}
        </div>
      )}

      {summaryChips.length > 0 && (
        <Card>
          <CardHeader title={t("monthly_summary", { defaultValue: "Monthly equivalent" })} />
          <CardContent className="flex flex-wrap gap-3 pt-2">
            {summaryChips.map(([ccy, b]) => (
              <div key={ccy} className="rounded-[var(--radius-control)] bg-surface-2 px-3 py-2">
                <p className="text-xs text-muted">{ccy}</p>
                <p className={cn("num text-sm font-semibold", b.net >= 0 ? "text-positive" : "text-foreground")}>
                  {formatSigned(b.net, ccy, locale)}<span className="text-muted">/mo</span>
                </p>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      <div className="flex items-center justify-between">
        <p className="text-sm text-muted">{t("recurring_subtitle", { defaultValue: "Bills, subscriptions and income on a schedule." })}</p>
        <Button onClick={() => { setFormError(undefined); setModal({ open: true }); }}>
          <Plus className="h-4 w-4" /> {t("new_recurring", { defaultValue: "New Recurring Item" })}
        </Button>
      </div>

      {data && data.items.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex gap-1.5">
            {(["all", "in", "out"] as const).map((d) => (
              <button key={d} onClick={() => setDirFilter(d)} className={cn("rounded-full px-3 py-1 text-xs font-medium transition-colors", dirFilter === d ? "bg-accent-soft text-primary" : "text-muted hover:bg-surface-2 hover:text-foreground")}>
                {d === "all" ? t("all", { defaultValue: "All" }) : d === "in" ? t("income", { defaultValue: "Income" }) : t("expense", { defaultValue: "Expense" })}
              </button>
            ))}
          </div>
          <Select value={freqFilter} onChange={(e) => setFreqFilter(e.target.value)} className="w-auto">
            <option value="all">{t("all_frequencies", { defaultValue: "All frequencies" })}</option>
            {FREQUENCIES.map((f) => <option key={f} value={f}>{t(`freq_${f}`, { defaultValue: f })}</option>)}
          </Select>
        </div>
      )}

      {isLoading && <Card className="p-8 text-center text-sm text-muted">{t("loading", { defaultValue: "Loading…" })}</Card>}
      {data && data.items.length === 0 && (
        <Card className="p-10 text-center text-sm text-muted">{t("no_recurring", { defaultValue: "No recurring items yet." })}</Card>
      )}
      {data && data.items.length > 0 && items.length === 0 && (
        <Card className="p-8 text-center text-sm text-muted">{t("no_match", { defaultValue: "Nothing matches these filters." })}</Card>
      )}

      <div className="space-y-3">
        {items.map((r) => {
          const due = r.days_until <= 0;
          return (
            <Card key={r.id} className="flex items-center justify-between gap-4 p-4">
              <div className="flex min-w-0 items-center gap-3">
                <span className="grid h-10 w-10 shrink-0 place-items-center rounded-[var(--radius-control)] bg-accent-soft text-primary">
                  <Repeat className="h-5 w-5" />
                </span>
                <div className="min-w-0">
                  <p className="truncate font-medium text-foreground">{r.name}</p>
                  <div className="mt-0.5 flex flex-wrap items-center gap-1.5">
                    <Badge>{t(`freq_${r.frequency}`, { defaultValue: r.frequency })}</Badge>
                    <Badge tone={r.apply_mode === "auto" ? "primary" : "neutral"}>{t(`mode_${r.apply_mode}`, { defaultValue: r.apply_mode })}</Badge>
                    <span className={cn("text-xs", r.days_until < 0 ? "text-negative" : r.days_until <= 3 ? "text-warning" : "text-muted")}>
                      {dayLabel(r.next_due_date, locale)}{r.days_until < 0 ? ` · ${t("overdue", { defaultValue: "overdue" })}` : ""}
                    </span>
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <span className={cn("num text-sm font-semibold", r.direction === "in" ? "text-positive" : "text-foreground")}>
                  {formatSigned(r.direction === "in" ? r.amount : -r.amount, r.currency, locale)}
                </span>
                {due && (
                  <Button size="sm" variant="outline" onClick={() => apply.mutate({ id: r.id })} title={t("apply", { defaultValue: "Apply now" })}>
                    <CheckCircle2 className="h-4 w-4" /> {t("apply", { defaultValue: "Apply" })}
                  </Button>
                )}
                <button onClick={() => { setFormError(undefined); setModal({ open: true, editing: r }); }} aria-label={t("edit", { defaultValue: "Edit" })} className="rounded-md p-2 text-muted hover:bg-surface-2 hover:text-foreground">
                  <Pencil className="h-4 w-4" />
                </button>
                <button onClick={() => del.mutate(r.id)} aria-label={t("delete", { defaultValue: "Delete" })} className="rounded-md p-2 text-muted hover:bg-negative-soft hover:text-negative">
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            </Card>
          );
        })}
      </div>

      <Modal open={modal.open} onClose={() => setModal({ open: false })} title={modal.editing ? t("edit_recurring", { defaultValue: "Edit Recurring Item" }) : t("new_recurring", { defaultValue: "New Recurring Item" })}>
        <RecurringForm initial={modal.editing} sources={sources ?? []} pending={create.isPending || update.isPending} error={formError} onCancel={() => setModal({ open: false })} onSubmit={submit} />
      </Modal>
    </div>
  );
}
