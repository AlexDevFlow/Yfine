import { ChevronLeft, ChevronRight, Pencil, Plus, Trash2 } from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field, Input, Select } from "@/components/ui/input";
import { Modal } from "@/components/ui/modal";
import { isPreviewDb } from "@/db/connection";
import { useBudgets, useCreateBudget, useDeleteBudget, useTags, useUpdateBudget } from "@/db/queries";
import type { BudgetStatus, NewBudget } from "@/db/repo/budgets";
import type { Period } from "@/domain/period";
import { round2 } from "@/domain/money";
import { cn } from "@/lib/cn";
import { formatMoney } from "@/lib/format";
import { useErrorText } from "@/lib/use-error-text";
import type { TagRow } from "@/db/schema-types";

const PERIODS: Period[] = ["weekly", "monthly", "quarterly", "yearly"];

function BudgetForm({ initial, tags, onCancel, onSubmit, pending, error }: {
  initial?: BudgetStatus; tags: TagRow[]; onCancel: () => void; onSubmit: (v: NewBudget) => void; pending: boolean; error?: string;
}) {
  const { t } = useTranslation();
  const b = initial?.budget;
  const [tagId, setTagId] = useState(String(b?.tag_id ?? tags[0]?.id ?? ""));
  const [amount, setAmount] = useState(b ? String(b.amount) : "");
  const [currency, setCurrency] = useState(b?.currency ?? "EUR");
  const [period, setPeriod] = useState<Period>(b?.period ?? "monthly");
  const [direction, setDirection] = useState<"in" | "out">(b?.direction ?? "out");
  const [rollover, setRollover] = useState((b?.rollover ?? 0) === 1);
  const [threshold, setThreshold] = useState(String(b?.alert_threshold_pct ?? 80));

  const submit = (e: FormEvent) => {
    e.preventDefault();
    onSubmit({ tag_id: Number(tagId), amount: Number(amount) || 0, currency: currency.trim().toUpperCase(), period, direction, rollover, alert_threshold_pct: Number(threshold) || 0 });
  };
  return (
    <form onSubmit={submit} className="space-y-4">
      <Field label={t("tag", { defaultValue: "Tag" })} htmlFor="b-tag">
        <Select id="b-tag" value={tagId} onChange={(e) => setTagId(e.target.value)} required>
          {tags.map((tg) => <option key={tg.id} value={tg.id}>{tg.name}</option>)}
        </Select>
      </Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label={t("amount", { defaultValue: "Amount" })} htmlFor="b-amt"><Input id="b-amt" type="number" step="0.01" min="0.01" value={amount} onChange={(e) => setAmount(e.target.value)} required className="num" /></Field>
        <Field label={t("currency", { defaultValue: "Currency" })} htmlFor="b-ccy"><Input id="b-ccy" value={currency} onChange={(e) => setCurrency(e.target.value.toUpperCase())} maxLength={5} /></Field>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <Field label={t("period", { defaultValue: "Period" })} htmlFor="b-period">
          <Select id="b-period" value={period} onChange={(e) => setPeriod(e.target.value as Period)}>
            {PERIODS.map((p) => <option key={p} value={p}>{t(`period_${p}`, { defaultValue: p })}</option>)}
          </Select>
        </Field>
        <Field label={t("alert_threshold", { defaultValue: "Alert at %" })} htmlFor="b-thr"><Input id="b-thr" type="number" min="0" max="100" value={threshold} onChange={(e) => setThreshold(e.target.value)} className="num" /></Field>
      </div>
      <div className="grid grid-cols-2 gap-2">
        {(["out", "in"] as const).map((d) => (
          <button type="button" key={d} onClick={() => setDirection(d)} className={cn("h-10 rounded-[var(--radius-control)] border text-sm font-medium", direction === d ? "border-primary bg-accent-soft text-primary" : "border-border text-muted")}>
            {d === "out" ? t("spending", { defaultValue: "Spending" }) : t("income", { defaultValue: "Income" })}
          </button>
        ))}
      </div>
      <label className="flex items-center gap-2 text-sm text-foreground">
        <input type="checkbox" checked={rollover} onChange={(e) => setRollover(e.target.checked)} />
        {t("rollover", { defaultValue: "Roll over unused budget (envelope)" })}
      </label>
      {error ? <p className="text-sm text-negative">{error}</p> : null}
      <div className="flex justify-end gap-2 pt-1">
        <Button type="button" variant="ghost" onClick={onCancel}>{t("cancel", { defaultValue: "Cancel" })}</Button>
        <Button type="submit" disabled={pending || !tagId || !amount}>{t("save", { defaultValue: "Save" })}</Button>
      </div>
    </form>
  );
}

export function BudgetsPage() {
  const { t, i18n } = useTranslation();
  const locale = i18n.resolvedLanguage;
  const errText = useErrorText();
  const [offset, setOffset] = useState(0);
  const { data, isLoading } = useBudgets(offset);
  const { data: tags } = useTags();
  const create = useCreateBudget();
  const update = useUpdateBudget();
  const del = useDeleteBudget();
  const [modal, setModal] = useState<{ open: boolean; editing?: BudgetStatus }>({ open: false });
  const [formError, setFormError] = useState<string>();
  const tagName = useMemo(() => new Map((tags ?? []).map((tg) => [tg.id, tg.name])), [tags]);

  // Per-currency rollup across all budgets in the viewed period.
  const summary = useMemo(() => {
    const m = new Map<string, { actual: number; available: number; remaining: number }>();
    for (const st of data ?? []) {
      const e = m.get(st.budget.currency) ?? { actual: 0, available: 0, remaining: 0 };
      e.actual = round2(e.actual + st.actual);
      e.available = round2(e.available + st.available);
      e.remaining = round2(e.remaining + st.remaining);
      m.set(st.budget.currency, e);
    }
    return [...m.entries()];
  }, [data]);

  const submit = (v: NewBudget) => {
    setFormError(undefined);
    const onErr = (e: unknown) => setFormError(errText(e));
    if (modal.editing) update.mutate({ id: modal.editing.budget.id, patch: v }, { onSuccess: () => setModal({ open: false }), onError: onErr });
    else create.mutate(v, { onSuccess: () => setModal({ open: false }), onError: onErr });
  };

  const TONE = { over: "bg-negative", warning: "bg-warning", ok: "bg-primary" } as const;

  return (
    <div className="space-y-4">
      {isPreviewDb && <div className="rounded-[var(--radius-control)] border border-border bg-warning-soft px-3 py-2 text-xs text-warning">{t("preview_db_note", { defaultValue: "Browser preview with seeded sample data." })}</div>}
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted">{t("budgets_subtitle", { defaultValue: "Per-tag spending limits with live tracking." })}</p>
        <Button onClick={() => { setFormError(undefined); setModal({ open: true }); }} disabled={(tags?.length ?? 0) === 0}>
          <Plus className="h-4 w-4" /> {t("new_budget", { defaultValue: "New Budget" })}
        </Button>
      </div>

      {/* Period navigation + per-currency rollup */}
      {data && data.length > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-[var(--radius-card)] border border-border bg-surface p-3">
          <div className="flex items-center gap-1.5">
            <button onClick={() => setOffset((o) => o - 1)} aria-label={t("previous", { defaultValue: "Previous" })} className="grid h-8 w-8 place-items-center rounded-[var(--radius-control)] text-muted hover:bg-surface-2 hover:text-foreground"><ChevronLeft className="h-4 w-4" /></button>
            <button onClick={() => setOffset(0)} className={cn("rounded-[var(--radius-control)] px-3 py-1 text-sm font-medium", offset === 0 ? "text-foreground" : "text-primary hover:bg-surface-2")}>
              {offset === 0 ? t("current_period", { defaultValue: "Current period" }) : offset > 0 ? t("periods_ahead", { defaultValue: "+{{n}} period", n: offset }) : t("periods_ago", { defaultValue: "{{n}} period", n: offset })}
            </button>
            <button onClick={() => setOffset((o) => o + 1)} aria-label={t("next", { defaultValue: "Next" })} className="grid h-8 w-8 place-items-center rounded-[var(--radius-control)] text-muted hover:bg-surface-2 hover:text-foreground"><ChevronRight className="h-4 w-4" /></button>
          </div>
          <div className="flex flex-wrap items-center gap-3 text-sm">
            {summary.map(([ccy, s]) => (
              <span key={ccy} className="num rounded-[var(--radius-control)] bg-surface-2 px-2.5 py-1">
                <span className={cn("font-semibold", s.remaining < 0 ? "text-negative" : "text-foreground")}>{formatMoney(s.actual, ccy, locale)}</span>
                <span className="text-muted"> / {formatMoney(s.available, ccy, locale)}</span>
              </span>
            ))}
          </div>
        </div>
      )}

      {isLoading && <Card className="p-8 text-center text-sm text-muted">{t("loading", { defaultValue: "Loading…" })}</Card>}
      {data && data.length === 0 && <Card className="p-10 text-center text-sm text-muted">{t("no_budgets", { defaultValue: "No budgets yet." })}</Card>}

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        {(data ?? []).map((st) => (
          <Card key={st.budget.id} className="p-4">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="truncate font-medium text-foreground">{tagName.get(st.budget.tag_id) ?? `#${st.budget.tag_id}`}</p>
                <div className="mt-0.5 flex items-center gap-1.5">
                  <Badge>{t(`period_${st.budget.period}`, { defaultValue: st.budget.period })}</Badge>
                  {st.budget.rollover === 1 && <Badge tone="primary">{t("rollover_short", { defaultValue: "rollover" })}</Badge>}
                  {st.status === "over" && <Badge tone="negative">{t("over_budget", { defaultValue: "over" })}</Badge>}
                </div>
              </div>
              <div className="flex shrink-0 items-center gap-1">
                <button onClick={() => { setFormError(undefined); setModal({ open: true, editing: st }); }} className="rounded-md p-1.5 text-muted hover:bg-surface-2 hover:text-foreground"><Pencil className="h-4 w-4" /></button>
                <button onClick={() => del.mutate(st.budget.id)} className="rounded-md p-1.5 text-muted hover:bg-negative-soft hover:text-negative"><Trash2 className="h-4 w-4" /></button>
              </div>
            </div>
            <div className="mt-3 flex items-baseline justify-between text-sm">
              <span className="num font-semibold text-foreground">{formatMoney(st.actual, st.budget.currency, locale)}</span>
              <span className="num text-muted">/ {formatMoney(st.available, st.budget.currency, locale)}</span>
            </div>
            <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-surface-2">
              <div className={cn("h-full rounded-full", TONE[st.status])} style={{ width: `${Math.min(100, Math.max(0, st.spentPct))}%` }} />
            </div>
            <div className="mt-1 flex items-center justify-between text-xs text-muted">
              <span className="num">
                {st.remaining >= 0
                  ? t("remaining_amt", { defaultValue: "{{amt}} left", amt: formatMoney(st.remaining, st.budget.currency, locale) })
                  : t("over_by", { defaultValue: "{{amt}} over", amt: formatMoney(-st.remaining, st.budget.currency, locale) })}
              </span>
              {st.daysRemaining > 0 && <span>{t("days_left", { defaultValue: "{{n}}d left", n: st.daysRemaining })}</span>}
            </div>
            {st.projected > 0 && st.daysRemaining > 0 && (
              <p className={cn("num mt-0.5 text-xs", st.projected > st.available ? "text-negative" : "text-muted-2")}>
                {t("projected_spend", { defaultValue: "Projected: {{amt}}", amt: formatMoney(st.projected, st.budget.currency, locale) })}
              </p>
            )}
          </Card>
        ))}
      </div>

      <Modal open={modal.open} onClose={() => setModal({ open: false })} title={modal.editing ? t("edit_budget", { defaultValue: "Edit Budget" }) : t("new_budget", { defaultValue: "New Budget" })}>
        <BudgetForm initial={modal.editing} tags={tags ?? []} pending={create.isPending || update.isPending} error={formError} onCancel={() => setModal({ open: false })} onSubmit={submit} />
      </Modal>
    </div>
  );
}
