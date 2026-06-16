import { Flag, Pencil, Plus, Trash2, Wallet } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field, Input, Select } from "@/components/ui/input";
import { Modal } from "@/components/ui/modal";
import { isPreviewDb } from "@/db/connection";
import {
  useAllocate,
  useCloseGoal,
  useCreateGoal,
  useDeleteGoal,
  useGoals,
  useSources,
  useUpdateGoal,
  type SourceWithBalance,
} from "@/db/queries";
import type { EnrichedGoal, NewGoal } from "@/db/repo/goals";
import { cn } from "@/lib/cn";
import { todayISO } from "@/lib/date";
import { formatMoney } from "@/lib/format";
import { useErrorText } from "@/lib/use-error-text";

function GoalForm({ initial, onCancel, onSubmit, pending, error }: {
  initial?: EnrichedGoal; onCancel: () => void; onSubmit: (v: NewGoal) => void; pending: boolean; error?: string;
}) {
  const { t } = useTranslation();
  const [name, setName] = useState(initial?.name ?? "");
  const [target, setTarget] = useState(initial ? String(initial.target_amount) : "");
  const [currency, setCurrency] = useState(initial?.currency ?? "EUR");
  const [targetDate, setTargetDate] = useState(initial?.target_date ?? "");
  const [note, setNote] = useState(initial?.note ?? "");
  const submit = (e: FormEvent) => {
    e.preventDefault();
    onSubmit({ name: name.trim(), target_amount: Number(target) || 0, currency: currency.trim().toUpperCase(), target_date: targetDate || null, note: note || null });
  };
  return (
    <form onSubmit={submit} className="space-y-4">
      <Field label={t("name", { defaultValue: "Name" })} htmlFor="g-name"><Input id="g-name" value={name} onChange={(e) => setName(e.target.value)} required autoFocus /></Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label={t("target_amount", { defaultValue: "Target" })} htmlFor="g-target"><Input id="g-target" type="number" step="0.01" min="0.01" value={target} onChange={(e) => setTarget(e.target.value)} required className="num" /></Field>
        <Field label={t("currency", { defaultValue: "Currency" })} htmlFor="g-ccy"><Input id="g-ccy" value={currency} onChange={(e) => setCurrency(e.target.value.toUpperCase())} maxLength={5} disabled={!!initial} /></Field>
      </div>
      <Field label={t("target_date_optional", { defaultValue: "Target date (optional)" })} htmlFor="g-date"><Input id="g-date" type="date" value={targetDate} onChange={(e) => setTargetDate(e.target.value)} /></Field>
      <Field label={t("note", { defaultValue: "Note" })} htmlFor="g-note"><Input id="g-note" value={note} onChange={(e) => setNote(e.target.value)} /></Field>
      {!initial && <p className="text-xs text-muted">{t("goal_fund_hint", { defaultValue: "Money accumulates in your savings fund for this currency." })}</p>}
      {error ? <p className="text-sm text-negative">{error}</p> : null}
      <div className="flex justify-end gap-2 pt-1">
        <Button type="button" variant="ghost" onClick={onCancel}>{t("cancel", { defaultValue: "Cancel" })}</Button>
        <Button type="submit" disabled={pending || !name.trim() || !target}>{t("save", { defaultValue: "Save" })}</Button>
      </div>
    </form>
  );
}

function MoveDialog({ goal, sources, title, label, exclude, onClose, onConfirm, pending, error }: {
  goal: EnrichedGoal; sources: SourceWithBalance[]; title: string; label: string; exclude: boolean;
  onClose: () => void; onConfirm: (sourceId: number, amount: number | null, date: string) => void; pending: boolean; error?: string;
}) {
  const { t } = useTranslation();
  const opts = sources.filter((s) => s.currency === goal.currency && (!exclude || s.id !== goal.source_id));
  const [sourceId, setSourceId] = useState(String(opts[0]?.id ?? ""));
  const [amount, setAmount] = useState("");
  const [date, setDate] = useState(todayISO());
  const withAmount = label === "allocate";
  return (
    <Modal open onClose={onClose} title={title}
      footer={<>
        <Button variant="ghost" onClick={onClose}>{t("cancel", { defaultValue: "Cancel" })}</Button>
        <Button disabled={pending || !sourceId || (withAmount && !amount)} onClick={() => onConfirm(Number(sourceId), withAmount ? Number(amount) || 0 : null, date)}>{t("confirm", { defaultValue: "Confirm" })}</Button>
      </>}>
      <div className="space-y-4">
        <Field label={withAmount ? t("from", { defaultValue: "From" }) : t("to", { defaultValue: "To" })} htmlFor="md-src">
          <Select id="md-src" value={sourceId} onChange={(e) => setSourceId(e.target.value)}>
            {opts.map((s) => <option key={s.id} value={s.id}>{s.name} · {formatMoney(s.balance, s.currency)}</option>)}
          </Select>
        </Field>
        {withAmount && <Field label={t("amount", { defaultValue: "Amount" })} htmlFor="md-amt"><Input id="md-amt" type="number" step="0.01" min="0.01" value={amount} onChange={(e) => setAmount(e.target.value)} autoFocus className="num" /></Field>}
        <Field label={t("date", { defaultValue: "Date" })} htmlFor="md-date"><Input id="md-date" type="date" value={date} onChange={(e) => setDate(e.target.value)} /></Field>
        {opts.length === 0 && <p className="text-xs text-warning">{t("no_compatible_sources", { defaultValue: "No compatible accounts (same currency)." })}</p>}
        {error ? <p className="text-sm text-negative">{error}</p> : null}
      </div>
    </Modal>
  );
}

export function GoalsPage() {
  const { t, i18n } = useTranslation();
  const locale = i18n.resolvedLanguage;
  const errText = useErrorText();
  const { data: gs, isLoading } = useGoals();
  const { data: sources } = useSources();
  const create = useCreateGoal();
  const update = useUpdateGoal();
  const allocate = useAllocate();
  const close = useCloseGoal();
  const del = useDeleteGoal();

  const [form, setForm] = useState<{ open: boolean; editing?: EnrichedGoal }>({ open: false });
  const [allocating, setAllocating] = useState<EnrichedGoal>();
  const [closing, setClosing] = useState<EnrichedGoal>();
  const [formError, setFormError] = useState<string>();
  const [dialogError, setDialogError] = useState<string>();

  const submit = (v: NewGoal) => {
    setFormError(undefined);
    const onErr = (e: unknown) => setFormError(errText(e));
    if (form.editing) update.mutate({ id: form.editing.id, patch: { name: v.name, target_amount: v.target_amount, target_date: v.target_date, note: v.note } }, { onSuccess: () => setForm({ open: false }), onError: onErr });
    else create.mutate(v, { onSuccess: () => setForm({ open: false }), onError: onErr });
  };

  return (
    <div className="space-y-4">
      {isPreviewDb && <div className="rounded-[var(--radius-control)] border border-border bg-warning-soft px-3 py-2 text-xs text-warning">{t("preview_db_note", { defaultValue: "Browser preview with seeded sample data." })}</div>}
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted">{t("goals_subtitle", { defaultValue: "Savings targets funded by real allocations." })}</p>
        <Button onClick={() => { setFormError(undefined); setForm({ open: true }); }}><Plus className="h-4 w-4" /> {t("new_goal", { defaultValue: "New Goal" })}</Button>
      </div>
      {isLoading && <Card className="p-8 text-center text-sm text-muted">{t("loading", { defaultValue: "Loading…" })}</Card>}
      {gs && gs.length === 0 && <Card className="p-10 text-center text-sm text-muted">{t("no_goals", { defaultValue: "No goals yet." })}</Card>}

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        {(gs ?? []).map((g) => (
          <Card key={g.id} className="p-4">
            <div className="flex items-start justify-between gap-3">
              <div className="flex min-w-0 items-center gap-3">
                <span className="grid h-10 w-10 shrink-0 place-items-center rounded-[var(--radius-control)] bg-accent-soft text-primary"><Flag className="h-5 w-5" /></span>
                <div className="min-w-0">
                  <p className="truncate font-medium text-foreground">{g.name}</p>
                  <div className="mt-0.5 flex items-center gap-1.5">
                    <Badge>{g.currency}</Badge>
                    {g.status !== "active" && <Badge tone={g.status === "completed" ? "positive" : "neutral"}>{t(`goal_${g.status}`, { defaultValue: g.status })}</Badge>}
                  </div>
                </div>
              </div>
              <div className="flex shrink-0 items-center gap-1">
                <button onClick={() => { setFormError(undefined); setForm({ open: true, editing: g }); }} className="rounded-md p-1.5 text-muted hover:bg-surface-2 hover:text-foreground"><Pencil className="h-4 w-4" /></button>
                <button onClick={() => del.mutate(g.id)} className="rounded-md p-1.5 text-muted hover:bg-negative-soft hover:text-negative"><Trash2 className="h-4 w-4" /></button>
              </div>
            </div>
            <div className="mt-3 flex items-baseline justify-between text-sm">
              <span className="num font-semibold text-foreground">{formatMoney(g.allocated, g.currency, locale)}</span>
              <span className="num text-muted">/ {formatMoney(g.target_amount, g.currency, locale)} · {g.progress_pct}%</span>
            </div>
            <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-surface-2">
              <div className={cn("h-full rounded-full", g.progress_pct >= 100 ? "bg-positive" : "bg-primary")} style={{ width: `${Math.min(100, g.progress_pct)}%` }} />
            </div>
            {g.status === "active" && (
              <div className="mt-3 flex gap-2">
                <Button size="sm" variant="outline" onClick={() => { setDialogError(undefined); setAllocating(g); }}><Wallet className="h-4 w-4" /> {t("allocate", { defaultValue: "Add money" })}</Button>
                {g.allocated > 0 && <Button size="sm" variant="ghost" onClick={() => { setDialogError(undefined); setClosing(g); }}>{t("close_goal", { defaultValue: "Close & refund" })}</Button>}
              </div>
            )}
          </Card>
        ))}
      </div>

      <Modal open={form.open} onClose={() => setForm({ open: false })} title={form.editing ? t("edit_goal", { defaultValue: "Edit Goal" }) : t("new_goal", { defaultValue: "New Goal" })}>
        <GoalForm initial={form.editing} pending={create.isPending || update.isPending} error={formError} onCancel={() => setForm({ open: false })} onSubmit={submit} />
      </Modal>

      {allocating && (
        <MoveDialog goal={allocating} sources={sources ?? []} exclude title={t("allocate_to", { defaultValue: "Add to goal" })} label="allocate"
          pending={allocate.isPending} error={dialogError}
          onClose={() => setAllocating(undefined)}
          onConfirm={(sourceId, amount, date) => allocate.mutate({ goalId: allocating.id, input: { fromSourceId: sourceId, amount: amount!, date } }, { onSuccess: () => setAllocating(undefined), onError: (e) => setDialogError(errText(e)) })} />
      )}
      {closing && (
        <MoveDialog goal={closing} sources={sources ?? []} exclude={false} title={t("close_goal", { defaultValue: "Close & refund" })} label="close"
          pending={close.isPending} error={dialogError}
          onClose={() => setClosing(undefined)}
          onConfirm={(sourceId, _a, date) => close.mutate({ id: closing.id, toSourceId: sourceId, date }, { onSuccess: () => setClosing(undefined), onError: (e) => setDialogError(errText(e)) })} />
      )}
    </div>
  );
}
