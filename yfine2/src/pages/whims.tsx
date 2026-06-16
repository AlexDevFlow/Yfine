import { Check, PiggyBank, Plus, RotateCcw, ShoppingBag, Trash2, X } from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field, Input, Select } from "@/components/ui/input";
import { Modal } from "@/components/ui/modal";
import { isPreviewDb } from "@/db/connection";
import {
  useCreateWhim,
  useDeleteWhim,
  useDismissWhim,
  usePurchaseWhim,
  useRestoreWhim,
  useSources,
  useStartSaving,
  useUpdateWhim,
  useWhims,
  type SourceWithBalance,
} from "@/db/queries";
import type { EnrichedWhim, NewWhim } from "@/db/repo/whims";
import { formatMoney } from "@/lib/format";
import { useErrorText } from "@/lib/use-error-text";

const PRIORITIES = ["high", "medium", "low"] as const;
const PRIORITY_TONE = { high: "negative", medium: "warning", low: "neutral" } as const;

function WhimForm({ initial, onCancel, onSubmit, pending, error }: {
  initial?: EnrichedWhim; onCancel: () => void; onSubmit: (v: NewWhim) => void; pending: boolean; error?: string;
}) {
  const { t } = useTranslation();
  const [name, setName] = useState(initial?.name ?? "");
  const [amount, setAmount] = useState(initial ? String(initial.amount) : "");
  const [currency, setCurrency] = useState(initial?.currency ?? "EUR");
  const [priority, setPriority] = useState<"low" | "medium" | "high">(initial?.priority ?? "medium");
  const [url, setUrl] = useState(initial?.url ?? "");
  const [note, setNote] = useState(initial?.note ?? "");
  const submit = (e: FormEvent) => {
    e.preventDefault();
    onSubmit({ name: name.trim(), amount: Number(amount) || 0, currency: currency.trim().toUpperCase(), priority, url: url || null, note: note || null });
  };
  return (
    <form onSubmit={submit} className="space-y-4">
      <Field label={t("name", { defaultValue: "Name" })} htmlFor="w-name"><Input id="w-name" value={name} onChange={(e) => setName(e.target.value)} required autoFocus /></Field>
      <div className="grid grid-cols-3 gap-3">
        <Field label={t("amount", { defaultValue: "Amount" })} htmlFor="w-amt"><Input id="w-amt" type="number" step="0.01" min="0.01" value={amount} onChange={(e) => setAmount(e.target.value)} required className="num" /></Field>
        <Field label={t("currency", { defaultValue: "Currency" })} htmlFor="w-ccy"><Input id="w-ccy" value={currency} onChange={(e) => setCurrency(e.target.value.toUpperCase())} maxLength={5} /></Field>
        <Field label={t("whim_priority", { defaultValue: "Priority" })} htmlFor="w-pri">
          <Select id="w-pri" value={priority} onChange={(e) => setPriority(e.target.value as "low" | "medium" | "high")}>
            {PRIORITIES.map((p) => <option key={p} value={p}>{t(`priority_${p}`, { defaultValue: p })}</option>)}
          </Select>
        </Field>
      </div>
      <Field label={t("url", { defaultValue: "Link (optional)" })} htmlFor="w-url"><Input id="w-url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://" /></Field>
      <Field label={t("note", { defaultValue: "Note" })} htmlFor="w-note"><Input id="w-note" value={note} onChange={(e) => setNote(e.target.value)} /></Field>
      {error ? <p className="text-sm text-negative">{error}</p> : null}
      <div className="flex justify-end gap-2 pt-1">
        <Button type="button" variant="ghost" onClick={onCancel}>{t("cancel", { defaultValue: "Cancel" })}</Button>
        <Button type="submit" disabled={pending || !name.trim() || !amount}>{t("save", { defaultValue: "Save" })}</Button>
      </div>
    </form>
  );
}

function PurchaseDialog({ whim, sources, onClose, onConfirm, pending, error }: {
  whim: EnrichedWhim; sources: SourceWithBalance[]; onClose: () => void; onConfirm: (sourceId: number, note: string, amount: number) => void; pending: boolean; error?: string;
}) {
  const { t } = useTranslation();
  const opts = sources.filter((s) => s.currency === whim.currency);
  const [sourceId, setSourceId] = useState(String(whim.source_id ?? opts[0]?.id ?? ""));
  const [note, setNote] = useState("");
  // Price defaults to the wishlisted amount but is editable — the real price may have changed.
  const [amount, setAmount] = useState(String(whim.amount));
  return (
    <Modal open onClose={onClose} title={`${t("buy", { defaultValue: "Buy" })}: ${whim.name}`}
      footer={<>
        <Button variant="ghost" onClick={onClose}>{t("cancel", { defaultValue: "Cancel" })}</Button>
        <Button disabled={pending || !sourceId || !(Number(amount) > 0)} onClick={() => onConfirm(Number(sourceId), note, Number(amount))}>{t("buy", { defaultValue: "Buy" })}</Button>
      </>}>
      <div className="space-y-4">
        {whim.linked_goal_allocated != null && whim.linked_goal_allocated > 0 && (
          <p className="rounded-[var(--radius-control)] bg-accent-soft px-3 py-2 text-xs text-primary">
            {t("whim_drain_hint", { defaultValue: "Your saved {{amt}} will be moved into the chosen account first.", amt: formatMoney(whim.linked_goal_allocated, whim.currency) })}
          </p>
        )}
        <div className="grid grid-cols-2 gap-3">
          <Field label={`${t("price", { defaultValue: "Price" })} (${whim.currency})`} htmlFor="p-amt">
            <Input id="p-amt" type="number" step="0.01" min="0.01" value={amount} onChange={(e) => setAmount(e.target.value)} className="num" />
          </Field>
          <Field label={t("pay_from", { defaultValue: "Pay from" })} htmlFor="p-src">
            <Select id="p-src" value={sourceId} onChange={(e) => setSourceId(e.target.value)}>
              {opts.map((s) => <option key={s.id} value={s.id}>{s.name} · {formatMoney(s.balance, s.currency)}</option>)}
            </Select>
          </Field>
        </div>
        {Number(amount) > 0 && Number(amount) !== whim.amount && (
          <p className="text-xs text-muted">{t("price_changed_hint", { defaultValue: "Was {{old}} — buying at {{now}}.", old: formatMoney(whim.amount, whim.currency), now: formatMoney(Number(amount), whim.currency) })}</p>
        )}
        <Field label={t("note", { defaultValue: "Note" })} htmlFor="p-note"><Input id="p-note" value={note} onChange={(e) => setNote(e.target.value)} /></Field>
        {opts.length === 0 && <p className="text-xs text-warning">{t("no_compatible_sources", { defaultValue: "No compatible accounts (same currency)." })}</p>}
        {error ? <p className="text-sm text-negative">{error}</p> : null}
      </div>
    </Modal>
  );
}

export function WhimsPage() {
  const { t, i18n } = useTranslation();
  const locale = i18n.resolvedLanguage;
  const errText = useErrorText();
  const { data: whimList, isLoading } = useWhims();
  const { data: sources } = useSources();
  const create = useCreateWhim();
  const update = useUpdateWhim();
  const purchase = usePurchaseWhim();
  const dismiss = useDismissWhim();
  const restore = useRestoreWhim();
  const del = useDeleteWhim();
  const startSaving = useStartSaving();

  const [form, setForm] = useState<{ open: boolean; editing?: EnrichedWhim }>({ open: false });
  const [buying, setBuying] = useState<EnrichedWhim>();
  const [formError, setFormError] = useState<string>();
  const [buyError, setBuyError] = useState<string>();

  const groups = useMemo(() => {
    const list = whimList ?? [];
    return {
      pending: list.filter((w) => w.status === "pending"),
      purchased: list.filter((w) => w.status === "purchased"),
      dismissed: list.filter((w) => w.status === "dismissed"),
    };
  }, [whimList]);

  const submit = (v: NewWhim) => {
    setFormError(undefined);
    const onErr = (e: unknown) => setFormError(errText(e));
    if (form.editing) update.mutate({ id: form.editing.id, patch: v }, { onSuccess: () => setForm({ open: false }), onError: onErr });
    else create.mutate(v, { onSuccess: () => setForm({ open: false }), onError: onErr });
  };

  const card = (w: EnrichedWhim) => {
    const saving = w.linked_goal_allocated != null && w.linked_goal_status === "active";
    const pct = saving && w.linked_goal_target ? Math.min(100, Math.round((w.linked_goal_allocated! / w.linked_goal_target) * 100)) : 0;
    return (
      <Card key={w.id} className="p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="truncate font-medium text-foreground">{w.name}</p>
            <div className="mt-0.5 flex items-center gap-1.5">
              <span className="num text-sm text-muted">{formatMoney(w.amount, w.currency, locale)}</span>
              {w.status === "pending" && <Badge tone={PRIORITY_TONE[w.priority]}>{t(`priority_${w.priority}`, { defaultValue: w.priority })}</Badge>}
              {w.status === "purchased" && <Badge tone="positive">{t("whim_purchased", { defaultValue: "Purchased" })}</Badge>}
            </div>
          </div>
          <button onClick={() => del.mutate(w.id)} className="rounded-md p-1.5 text-muted hover:bg-negative-soft hover:text-negative"><Trash2 className="h-4 w-4" /></button>
        </div>
        {saving && (
          <div className="mt-3">
            <div className="h-2 overflow-hidden rounded-full bg-surface-2"><div className="h-full rounded-full bg-primary" style={{ width: `${pct}%` }} /></div>
            <p className="num mt-1 text-xs text-muted">{formatMoney(w.linked_goal_allocated!, w.currency, locale)} / {formatMoney(w.linked_goal_target!, w.currency, locale)} {t("saved", { defaultValue: "saved" })}</p>
          </div>
        )}
        {w.status === "pending" && (
          <div className="mt-3 flex flex-wrap gap-2">
            <Button size="sm" onClick={() => { setBuyError(undefined); setBuying(w); }}><ShoppingBag className="h-4 w-4" /> {t("buy", { defaultValue: "Buy" })}</Button>
            {!saving && <Button size="sm" variant="outline" onClick={() => startSaving.mutate(w.id)}><PiggyBank className="h-4 w-4" /> {t("save_for_this", { defaultValue: "Save for this" })}</Button>}
            <Button size="sm" variant="ghost" onClick={() => { setFormError(undefined); setForm({ open: true, editing: w }); }}>{t("edit", { defaultValue: "Edit" })}</Button>
            <Button size="sm" variant="ghost" onClick={() => dismiss.mutate(w.id)}><X className="h-4 w-4" /> {t("dismiss", { defaultValue: "Dismiss" })}</Button>
          </div>
        )}
        {w.status === "dismissed" && (
          <div className="mt-3"><Button size="sm" variant="outline" onClick={() => restore.mutate(w.id)}><RotateCcw className="h-4 w-4" /> {t("restore", { defaultValue: "Restore" })}</Button></div>
        )}
      </Card>
    );
  };

  return (
    <div className="space-y-5">
      {isPreviewDb && <div className="rounded-[var(--radius-control)] border border-border bg-warning-soft px-3 py-2 text-xs text-warning">{t("preview_db_note", { defaultValue: "Browser preview with seeded sample data." })}</div>}
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted">{t("whims_subtitle", { defaultValue: "A prioritised wishlist — save up or buy outright." })}</p>
        <Button onClick={() => { setFormError(undefined); setForm({ open: true }); }}><Plus className="h-4 w-4" /> {t("new_whim", { defaultValue: "New Whim" })}</Button>
      </div>

      {isLoading && <Card className="p-8 text-center text-sm text-muted">{t("loading", { defaultValue: "Loading…" })}</Card>}
      {whimList && whimList.length === 0 && <Card className="p-10 text-center text-sm text-muted">{t("no_whims", { defaultValue: "No whims yet." })}</Card>}

      {groups.pending.length > 0 && <div className="grid grid-cols-1 gap-3 md:grid-cols-2">{groups.pending.map(card)}</div>}
      {groups.purchased.length > 0 && (
        <div className="space-y-3">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-foreground"><Check className="h-4 w-4 text-positive" /> {t("whim_purchased", { defaultValue: "Purchased" })}</h2>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">{groups.purchased.map(card)}</div>
        </div>
      )}
      {groups.dismissed.length > 0 && (
        <div className="space-y-3">
          <h2 className="text-sm font-semibold text-muted">{t("whim_dismissed", { defaultValue: "Dismissed" })}</h2>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">{groups.dismissed.map(card)}</div>
        </div>
      )}

      <Modal open={form.open} onClose={() => setForm({ open: false })} title={form.editing ? t("edit_whim", { defaultValue: "Edit Whim" }) : t("new_whim", { defaultValue: "New Whim" })}>
        <WhimForm initial={form.editing} pending={create.isPending || update.isPending} error={formError} onCancel={() => setForm({ open: false })} onSubmit={submit} />
      </Modal>

      {buying && (
        <PurchaseDialog whim={buying} sources={sources ?? []} pending={purchase.isPending} error={buyError}
          onClose={() => setBuying(undefined)}
          onConfirm={(sourceId, note, amount) => purchase.mutate({ id: buying.id, sourceId, note, amount }, { onSuccess: () => setBuying(undefined), onError: (e) => setBuyError(errText(e)) })} />
      )}
    </div>
  );
}
