import { useMemo, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Field, Input, Select } from "@/components/ui/input";
import { cn } from "@/lib/cn";
import { todayISO } from "@/lib/date";
import type { SourceWithBalance } from "@/db/queries";
import type { TagRow } from "@/db/schema-types";
import type { EnrichedMovement } from "@/db/repo/movements";

function TagChips({
  tags,
  selected,
  onChange,
}: {
  tags: TagRow[];
  selected: number[];
  onChange: (ids: number[]) => void;
}) {
  if (tags.length === 0) return null;
  const toggle = (id: number) =>
    onChange(selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id]);
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
            <span
              className="mr-1 inline-block h-2 w-2 rounded-full align-middle"
              style={{ background: t.color ?? "var(--muted-2)" }}
            />
            {t.name}
          </button>
        );
      })}
    </div>
  );
}

// ---- plain movement -----------------------------------------------------

export interface MovementFormValues {
  source_id: number | null;
  amount: number;
  direction: "in" | "out";
  date: string;
  note: string;
  tagIds: number[];
}

export function MovementForm({
  initial,
  sources,
  tags,
  onSubmit,
  onCancel,
  pending,
  error,
}: {
  initial?: EnrichedMovement;
  sources: SourceWithBalance[];
  tags: TagRow[];
  onSubmit: (v: MovementFormValues) => void;
  onCancel: () => void;
  pending: boolean;
  error?: string;
}) {
  const { t } = useTranslation();
  const [direction, setDirection] = useState<"in" | "out">(initial?.direction ?? "out");
  const [sourceId, setSourceId] = useState<string>(initial?.source_id != null ? String(initial.source_id) : "");
  const [amount, setAmount] = useState(initial ? String(initial.amount) : "");
  const [date, setDate] = useState(initial?.date ?? todayISO());
  const [note, setNote] = useState(initial?.note ?? "");
  const [tagIds, setTagIds] = useState<number[]>(initial?.tags.map((x) => x.id) ?? []);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    onSubmit({
      source_id: sourceId === "" ? null : Number(sourceId),
      amount: Number(amount) || 0,
      direction,
      date,
      note,
      tagIds,
    });
  };

  return (
    <form onSubmit={submit} className="space-y-4">
      <div className="grid grid-cols-2 gap-2">
        {(["out", "in"] as const).map((d) => (
          <button
            type="button"
            key={d}
            onClick={() => setDirection(d)}
            className={cn(
              "h-10 rounded-[var(--radius-control)] border text-sm font-medium transition-colors",
              direction === d
                ? d === "in"
                  ? "border-positive bg-positive-soft text-positive"
                  : "border-negative bg-negative-soft text-negative"
                : "border-border text-muted hover:text-foreground",
            )}
          >
            {d === "in" ? t("income", { defaultValue: "Income" }) : t("expense", { defaultValue: "Expense" })}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-2 gap-3">
        <Field label={t("amount", { defaultValue: "Amount" })} htmlFor="mv-amt">
          <Input id="mv-amt" type="number" step="0.01" min="0.01" value={amount} onChange={(e) => setAmount(e.target.value)} required autoFocus className="num" />
        </Field>
        <Field label={t("date", { defaultValue: "Date" })} htmlFor="mv-date">
          <Input id="mv-date" type="date" value={date} onChange={(e) => setDate(e.target.value)} required />
        </Field>
      </div>

      <Field label={t("source", { defaultValue: "Source" })} htmlFor="mv-src">
        <Select id="mv-src" value={sourceId} onChange={(e) => setSourceId(e.target.value)}>
          <option value="">{t("external", { defaultValue: "External (no account)" })}</option>
          {sources.map((s) => (
            <option key={s.id} value={s.id}>{s.name} · {s.currency}</option>
          ))}
        </Select>
      </Field>

      <Field label={t("note", { defaultValue: "Note" })} htmlFor="mv-note">
        <Input id="mv-note" value={note} onChange={(e) => setNote(e.target.value)} maxLength={1000} />
      </Field>

      {tags.length > 0 && (
        <Field label={t("tags", { defaultValue: "Tags" })}>
          <TagChips tags={tags} selected={tagIds} onChange={setTagIds} />
        </Field>
      )}

      {error ? <p className="text-sm text-negative">{error}</p> : null}
      <div className="flex justify-end gap-2 pt-1">
        <Button type="button" variant="ghost" onClick={onCancel}>{t("cancel", { defaultValue: "Cancel" })}</Button>
        <Button type="submit" disabled={pending || !amount}>{t("save", { defaultValue: "Save" })}</Button>
      </div>
    </form>
  );
}

// ---- transfer -----------------------------------------------------------

export interface TransferFormValues {
  fromSourceId: number;
  toSourceId: number;
  amount: number;
  toAmount: number | null;
  date: string;
  note: string;
  tagIds: number[];
}

export function TransferForm({
  initial,
  sources,
  tags,
  onSubmit,
  onCancel,
  pending,
  error,
}: {
  initial?: EnrichedMovement; // the OUT leg
  sources: SourceWithBalance[];
  tags: TagRow[];
  onSubmit: (v: TransferFormValues) => void;
  onCancel: () => void;
  pending: boolean;
  error?: string;
}) {
  const { t } = useTranslation();
  const real = sources;
  const [fromId, setFromId] = useState<string>(
    initial?.source_id != null ? String(initial.source_id) : String(real[0]?.id ?? ""),
  );
  const [toId, setToId] = useState<string>(
    initial?.partner_source_id != null ? String(initial.partner_source_id) : String(real[1]?.id ?? real[0]?.id ?? ""),
  );
  const [amount, setAmount] = useState(initial ? String(initial.amount) : "");
  const [toAmount, setToAmount] = useState(initial?.partner_amount != null ? String(initial.partner_amount) : "");
  const [date, setDate] = useState(initial?.date ?? todayISO());
  const [note, setNote] = useState(initial?.note ?? "");
  const [tagIds, setTagIds] = useState<number[]>(initial?.tags.map((x) => x.id) ?? []);

  const fromCcy = useMemo(() => real.find((s) => s.id === Number(fromId))?.currency, [real, fromId]);
  const toCcy = useMemo(() => real.find((s) => s.id === Number(toId))?.currency, [real, toId]);
  const crossCurrency = !!fromCcy && !!toCcy && fromCcy !== toCcy;
  const sameSource = fromId !== "" && fromId === toId;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    onSubmit({
      fromSourceId: Number(fromId),
      toSourceId: Number(toId),
      amount: Number(amount) || 0,
      toAmount: crossCurrency ? Number(toAmount) || 0 : null,
      date,
      note,
      tagIds,
    });
  };

  return (
    <form onSubmit={submit} className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        <Field label={t("from", { defaultValue: "From" })} htmlFor="tr-from">
          <Select id="tr-from" value={fromId} onChange={(e) => setFromId(e.target.value)} required>
            {real.map((s) => (
              <option key={s.id} value={s.id}>{s.name} · {s.currency}</option>
            ))}
          </Select>
        </Field>
        <Field label={t("to", { defaultValue: "To" })} htmlFor="tr-to">
          <Select id="tr-to" value={toId} onChange={(e) => setToId(e.target.value)} required>
            {real.map((s) => (
              <option key={s.id} value={s.id}>{s.name} · {s.currency}</option>
            ))}
          </Select>
        </Field>
      </div>
      {sameSource && (
        <p className="text-xs text-negative">{t("err_same_source", { defaultValue: "Pick two different accounts." })}</p>
      )}

      <div className="grid grid-cols-2 gap-3">
        <Field label={crossCurrency ? `${t("amount", { defaultValue: "Amount" })} (${fromCcy})` : t("amount", { defaultValue: "Amount" })} htmlFor="tr-amt">
          <Input id="tr-amt" type="number" step="0.01" min="0.01" value={amount} onChange={(e) => setAmount(e.target.value)} required className="num" />
        </Field>
        {crossCurrency && (
          <Field label={`${t("converted", { defaultValue: "Converted" })} (${toCcy})`} htmlFor="tr-to-amt">
            <Input id="tr-to-amt" type="number" step="0.01" min="0.01" value={toAmount} onChange={(e) => setToAmount(e.target.value)} required className="num" />
          </Field>
        )}
        <Field label={t("date", { defaultValue: "Date" })} htmlFor="tr-date">
          <Input id="tr-date" type="date" value={date} onChange={(e) => setDate(e.target.value)} required />
        </Field>
      </div>

      <Field label={t("note", { defaultValue: "Note" })} htmlFor="tr-note">
        <Input id="tr-note" value={note} onChange={(e) => setNote(e.target.value)} maxLength={1000} />
      </Field>

      {tags.length > 0 && (
        <Field label={t("tags", { defaultValue: "Tags" })}>
          <TagChips tags={tags} selected={tagIds} onChange={setTagIds} />
        </Field>
      )}

      {error ? <p className="text-sm text-negative">{error}</p> : null}
      <div className="flex justify-end gap-2 pt-1">
        <Button type="button" variant="ghost" onClick={onCancel}>{t("cancel", { defaultValue: "Cancel" })}</Button>
        <Button type="submit" disabled={pending || !amount || sameSource || real.length < 2}>
          {t("save", { defaultValue: "Save" })}
        </Button>
      </div>
    </form>
  );
}
