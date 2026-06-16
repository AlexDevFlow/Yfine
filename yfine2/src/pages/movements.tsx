import { ArrowDownLeft, ArrowLeftRight, ArrowUpRight, CalendarDays, ChevronDown, ChevronRight, Layers, ListChecks, Pencil, Plus, Repeat, Search, SlidersHorizontal, Tag as TagIcon, Trash2, X } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input, Select } from "@/components/ui/input";
import { Modal } from "@/components/ui/modal";
import { SplitForm } from "@/components/split-form";
import { MovementsCalendar } from "./movements-calendar";
import { isPreviewDb } from "@/db/connection";
import {
  useBulkDelete,
  useBulkSetSource,
  useBulkSetTags,
  useCreateMovement,
  useCreateRecurring,
  useCreateSplit,
  useCreateTransfer,
  useDeleteMovement,
  useMovements,
  useSources,
  useTags,
  useUpdateMovement,
  useUpdateTransfer,
} from "@/db/queries";
import type { EnrichedMovement, MovementFilters } from "@/db/repo/movements";
import type { NewSplit } from "@/db/repo/splits";
import { groupMovementsHierarchically } from "@/domain/grouping";
import { cn } from "@/lib/cn";
import { dayLabel, monthLabel } from "@/lib/date";
import { formatMoney, formatSigned } from "@/lib/format";
import { useErrorText } from "@/lib/use-error-text";
import {
  MovementForm,
  TransferForm,
  type MovementFormValues,
  type TransferFormValues,
} from "./movements-forms";

function isTransfer(m: EnrichedMovement) {
  return m.transfer_pair_id != null;
}

function MovementRow({
  m,
  locale,
  onEdit,
  onDelete,
  onMakeRecurring,
  selected,
  onToggleSelect,
}: {
  m: EnrichedMovement;
  locale?: string;
  onEdit: () => void;
  onDelete: () => void;
  onMakeRecurring?: () => void;
  selected?: boolean;
  onToggleSelect?: () => void;
}) {
  const { t } = useTranslation();
  const transfer = isTransfer(m);
  const sourceLabel = m.source_name ?? (m.source_id == null ? t("external", { defaultValue: "External" }) : t("deleted", { defaultValue: "Deleted" }));
  const ccy = m.source_currency;
  const amountText = ccy
    ? transfer
      ? formatMoney(m.amount, ccy, locale)
      : formatSigned(m.direction === "in" ? m.amount : -m.amount, ccy, locale)
    : m.amount.toFixed(2);

  return (
    <li className="group flex items-center justify-between gap-3 py-2.5">
      <div className="flex min-w-0 items-center gap-3">
        {onToggleSelect && (
          <input type="checkbox" checked={!!selected} onChange={onToggleSelect} className="h-4 w-4 shrink-0" aria-label={t("select", { defaultValue: "Select" })} />
        )}
        <span
          className={cn(
            "grid h-9 w-9 shrink-0 place-items-center rounded-full",
            transfer ? "bg-surface-2 text-muted" : m.direction === "in" ? "bg-positive-soft text-positive" : "bg-negative-soft text-negative",
          )}
        >
          {transfer ? <ArrowLeftRight className="h-4 w-4" /> : m.direction === "in" ? <ArrowUpRight className="h-4 w-4" /> : <ArrowDownLeft className="h-4 w-4" />}
        </span>
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-foreground">
            {m.note || (transfer ? t("transfer", { defaultValue: "Transfer" }) : sourceLabel)}
          </p>
          <p className="truncate text-xs text-muted">
            {transfer ? `${sourceLabel} → ${m.partner_source_name ?? "?"}` : sourceLabel}
            {m.tags.length > 0 && (
              <span className="ml-1">
                {m.tags.map((tag) => (
                  <span key={tag.id} className="ml-1 inline-flex items-center">
                    <span className="mr-0.5 inline-block h-1.5 w-1.5 rounded-full align-middle" style={{ background: tag.color ?? "var(--muted-2)" }} />
                    {tag.name}
                  </span>
                ))}
              </span>
            )}
          </p>
        </div>
      </div>
      <div className="flex items-center gap-1">
        <span className={cn("num mr-1 text-sm font-semibold", transfer ? "text-muted" : m.direction === "in" ? "text-positive" : "text-foreground")}>
          {amountText}
        </span>
        {onMakeRecurring && !transfer && (
          <button onClick={onMakeRecurring} aria-label={t("make_recurring", { defaultValue: "Make recurring" })} className="rounded-md p-1.5 text-muted opacity-0 transition-opacity hover:bg-surface-2 hover:text-foreground group-hover:opacity-100">
            <Repeat className="h-4 w-4" />
          </button>
        )}
        <button onClick={onEdit} aria-label={t("edit", { defaultValue: "Edit" })} className="rounded-md p-1.5 text-muted opacity-0 transition-opacity hover:bg-surface-2 hover:text-foreground group-hover:opacity-100">
          <Pencil className="h-4 w-4" />
        </button>
        <button onClick={onDelete} aria-label={t("delete", { defaultValue: "Delete" })} className="rounded-md p-1.5 text-muted opacity-0 transition-opacity hover:bg-negative-soft hover:text-negative group-hover:opacity-100">
          <Trash2 className="h-4 w-4" />
        </button>
      </div>
    </li>
  );
}

export function MovementsPage() {
  const { t, i18n } = useTranslation();
  const locale = i18n.resolvedLanguage;
  const errText = useErrorText();

  const [q, setQ] = useState("");
  const [filterSource, setFilterSource] = useState("");
  const [filterDir, setFilterDir] = useState("");
  const [showFilters, setShowFilters] = useState(false);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [amtMin, setAmtMin] = useState("");
  const [amtMax, setAmtMax] = useState("");
  const [filterTagIds, setFilterTagIds] = useState<number[]>([]);
  const [tagMatch, setTagMatch] = useState<"or" | "and">("or");

  const advancedCount =
    (dateFrom ? 1 : 0) + (dateTo ? 1 : 0) + (amtMin ? 1 : 0) + (amtMax ? 1 : 0) + (filterTagIds.length ? 1 : 0);
  const clearAdvanced = () => {
    setDateFrom(""); setDateTo(""); setAmtMin(""); setAmtMax(""); setFilterTagIds([]); setTagMatch("or");
  };

  const filters = useMemo<MovementFilters>(
    () => ({
      excludeTransferIn: true,
      q: q.trim() || undefined,
      sourceId: filterSource === "" ? undefined : Number(filterSource),
      direction: (filterDir || undefined) as "in" | "out" | undefined,
      dateFrom: dateFrom || undefined,
      dateTo: dateTo || undefined,
      amountMin: amtMin ? Number(amtMin) : undefined,
      amountMax: amtMax ? Number(amtMax) : undefined,
      tagIds: filterTagIds.length ? filterTagIds : undefined,
      tagMatch,
    }),
    [q, filterSource, filterDir, dateFrom, dateTo, amtMin, amtMax, filterTagIds, tagMatch],
  );

  const { data, isLoading, error } = useMovements(filters);
  const { data: sources } = useSources();
  const { data: tags } = useTags();
  const realSources = useMemo(() => (sources ?? []).filter((s) => s.is_savings_fund === 0 || true), [sources]);

  const createMovement = useCreateMovement();
  const createRecurring = useCreateRecurring();
  const updateMovement = useUpdateMovement();
  const createTransfer = useCreateTransfer();
  const updateTransfer = useUpdateTransfer();
  const del = useDeleteMovement();

  const [mvModal, setMvModal] = useState<{ open: boolean; editing?: EnrichedMovement }>({ open: false });
  const [trModal, setTrModal] = useState<{ open: boolean; editing?: EnrichedMovement }>({ open: false });
  const [deleting, setDeleting] = useState<EnrichedMovement>();
  const [recurringFrom, setRecurringFrom] = useState<EnrichedMovement>();
  const [recFreq, setRecFreq] = useState("monthly");
  const [formError, setFormError] = useState<string>();
  const [splitOpen, setSplitOpen] = useState(false);
  const [calendarOpen, setCalendarOpen] = useState(false);
  const [selectMode, setSelectMode] = useState(false);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [bulkMoveTo, setBulkMoveTo] = useState("");
  const createSplit = useCreateSplit();
  const bulkDelete = useBulkDelete();
  const bulkMove = useBulkSetSource();
  const bulkSetTags = useBulkSetTags();
  const [bulkTagOpen, setBulkTagOpen] = useState(false);
  const [bulkTagIds, setBulkTagIds] = useState<number[]>([]);
  const [bulkTagMode, setBulkTagMode] = useState<"add" | "remove" | "replace">("add");
  const toggleBulkTag = (id: number) =>
    setBulkTagIds((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));
  const toggleSel = (id: number) =>
    setSelected((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  const clearSel = () => setSelected(new Set());
  const submitSplit = (v: NewSplit) => {
    setFormError(undefined);
    createSplit.mutate(v, { onSuccess: () => setSplitOpen(false), onError: (e) => setFormError(errText(e)) });
  };

  const groups = useMemo(() => groupMovementsHierarchically(data?.items ?? []), [data]);

  // Collapsible month/day groups (like the original). Keys are collapsed; default open.
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const toggleCollapse = (key: string) =>
    setCollapsed((s) => {
      const n = new Set(s);
      if (n.has(key)) n.delete(key);
      else n.add(key);
      return n;
    });

  const openEdit = (m: EnrichedMovement) => {
    setFormError(undefined);
    if (isTransfer(m)) setTrModal({ open: true, editing: m });
    else setMvModal({ open: true, editing: m });
  };

  const submitMovement = (v: MovementFormValues) => {
    setFormError(undefined);
    const onErr = (e: unknown) => setFormError(errText(e));
    if (mvModal.editing) {
      updateMovement.mutate(
        { id: mvModal.editing.id, patch: { source_id: v.source_id, amount: v.amount, direction: v.direction, date: v.date, note: v.note, tagIds: v.tagIds } },
        { onSuccess: () => setMvModal({ open: false }), onError: onErr },
      );
    } else {
      createMovement.mutate(
        { source_id: v.source_id, amount: v.amount, direction: v.direction, date: v.date, note: v.note, tagIds: v.tagIds },
        { onSuccess: () => setMvModal({ open: false }), onError: onErr },
      );
    }
  };

  const submitTransfer = (v: TransferFormValues) => {
    setFormError(undefined);
    const onErr = (e: unknown) => setFormError(errText(e));
    const patch = {
      fromSourceId: v.fromSourceId,
      toSourceId: v.toSourceId,
      amount: v.amount,
      toAmount: v.toAmount,
      date: v.date,
      note: v.note,
      tagIds: v.tagIds,
    };
    if (trModal.editing) {
      updateTransfer.mutate(
        { outLegId: trModal.editing.id, patch },
        { onSuccess: () => setTrModal({ open: false }), onError: onErr },
      );
    } else {
      createTransfer.mutate(patch, { onSuccess: () => setTrModal({ open: false }), onError: onErr });
    }
  };

  return (
    <div className="space-y-4">
      {isPreviewDb && (
        <div className="rounded-[var(--radius-control)] border border-border bg-warning-soft px-3 py-2 text-xs text-warning">
          {t("preview_db_note", { defaultValue: "Browser preview with seeded sample data (in-memory). The packaged app uses your real database." })}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-[180px] flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("search", { defaultValue: "Search" }) + "…"} className="pl-9" />
        </div>
        <Select value={filterSource} onChange={(e) => setFilterSource(e.target.value)} className="w-auto">
          <option value="">{t("all_sources", { defaultValue: "All sources" })}</option>
          {(sources ?? []).map((s) => (
            <option key={s.id} value={s.id}>{s.name}</option>
          ))}
        </Select>
        <Select value={filterDir} onChange={(e) => setFilterDir(e.target.value)} className="w-auto">
          <option value="">{t("all", { defaultValue: "All" })}</option>
          <option value="in">{t("income", { defaultValue: "Income" })}</option>
          <option value="out">{t("expense", { defaultValue: "Expense" })}</option>
        </Select>
        <Button variant={showFilters || advancedCount > 0 ? "secondary" : "outline"} onClick={() => setShowFilters((s) => !s)}>
          <SlidersHorizontal className="h-4 w-4" /> {t("filters", { defaultValue: "Filters" })}
          {advancedCount > 0 && <span className="ml-1 grid h-4 min-w-4 place-items-center rounded-full bg-primary px-1 text-[10px] text-primary-foreground">{advancedCount}</span>}
        </Button>
        <Button variant="outline" onClick={() => { setFormError(undefined); setTrModal({ open: true }); }} disabled={(realSources?.length ?? 0) < 2}>
          <ArrowLeftRight className="h-4 w-4" /> {t("transfer", { defaultValue: "Transfer" })}
        </Button>
        <Button variant="outline" onClick={() => { setFormError(undefined); setSplitOpen(true); }}>
          <Layers className="h-4 w-4" /> {t("split", { defaultValue: "Split" })}
        </Button>
        <Button variant="outline" onClick={() => setCalendarOpen(true)}>
          <CalendarDays className="h-4 w-4" /> {t("calendar", { defaultValue: "Calendar" })}
        </Button>
        <Button variant={selectMode ? "secondary" : "ghost"} onClick={() => { setSelectMode((s) => !s); clearSel(); }}>
          <ListChecks className="h-4 w-4" /> {t("select", { defaultValue: "Select" })}
        </Button>
        <Button onClick={() => { setFormError(undefined); setMvModal({ open: true }); }}>
          <Plus className="h-4 w-4" /> {t("new_movement", { defaultValue: "New Movement" })}
        </Button>
      </div>

      {showFilters && (
        <Card className="space-y-3 p-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <div>
              <p className="mb-1 text-xs font-medium text-muted">{t("date_from", { defaultValue: "From date" })}</p>
              <Input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
            </div>
            <div>
              <p className="mb-1 text-xs font-medium text-muted">{t("date_to", { defaultValue: "To date" })}</p>
              <Input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
            </div>
            <div>
              <p className="mb-1 text-xs font-medium text-muted">{t("amount_min", { defaultValue: "Min amount" })}</p>
              <Input type="number" step="0.01" min="0" value={amtMin} onChange={(e) => setAmtMin(e.target.value)} className="num" />
            </div>
            <div>
              <p className="mb-1 text-xs font-medium text-muted">{t("amount_max", { defaultValue: "Max amount" })}</p>
              <Input type="number" step="0.01" min="0" value={amtMax} onChange={(e) => setAmtMax(e.target.value)} className="num" />
            </div>
          </div>
          {(tags?.length ?? 0) > 0 && (
            <div>
              <div className="mb-1.5 flex items-center justify-between">
                <p className="text-xs font-medium text-muted">{t("tags", { defaultValue: "Tags" })}</p>
                {filterTagIds.length > 1 && (
                  <div className="flex items-center gap-1 text-xs">
                    {(["or", "and"] as const).map((m) => (
                      <button key={m} onClick={() => setTagMatch(m)} className={cn("rounded-full px-2 py-0.5 font-medium", tagMatch === m ? "bg-accent-soft text-primary" : "text-muted hover:text-foreground")}>
                        {m === "or" ? t("match_any", { defaultValue: "Any" }) : t("match_all", { defaultValue: "All" })}
                      </button>
                    ))}
                  </div>
                )}
              </div>
              <div className="flex flex-wrap gap-1.5">
                {(tags ?? []).map((tg) => {
                  const on = filterTagIds.includes(tg.id);
                  return (
                    <button key={tg.id} onClick={() => setFilterTagIds((s) => (on ? s.filter((x) => x !== tg.id) : [...s, tg.id]))} className={cn("rounded-full border px-2.5 py-1 text-xs font-medium transition-colors", on ? "border-primary bg-accent-soft text-primary" : "border-border text-muted hover:text-foreground")}>
                      <span className="mr-1 inline-block h-2 w-2 rounded-full align-middle" style={{ background: tg.color ?? "var(--muted-2)" }} />
                      {tg.name}
                    </button>
                  );
                })}
              </div>
            </div>
          )}
          {advancedCount > 0 && (
            <div className="flex justify-end">
              <Button size="sm" variant="ghost" onClick={clearAdvanced}><X className="h-4 w-4" /> {t("clear_filters", { defaultValue: "Clear filters" })}</Button>
            </div>
          )}
        </Card>
      )}

      {selectMode && selected.size > 0 && (
        <div className="sticky top-16 z-20 flex flex-wrap items-center gap-2 rounded-[var(--radius-control)] border border-border bg-surface p-2 shadow-[var(--shadow-card)]">
          <span className="px-1 text-sm font-medium text-foreground">{t("n_selected", { defaultValue: "{{n}} selected", n: selected.size })}</span>
          <Select value={bulkMoveTo} onChange={(e) => setBulkMoveTo(e.target.value)} className="w-auto">
            <option value="">{t("move_to", { defaultValue: "Move to…" })}</option>
            {(sources ?? []).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </Select>
          <Button size="sm" variant="outline" disabled={!bulkMoveTo || bulkMove.isPending} onClick={() => bulkMove.mutate({ ids: [...selected], sourceId: Number(bulkMoveTo) }, { onSuccess: () => { clearSel(); setBulkMoveTo(""); } })}>
            {t("move", { defaultValue: "Move" })}
          </Button>
          <Button size="sm" variant="outline" disabled={(tags?.length ?? 0) === 0} onClick={() => { setBulkTagIds([]); setBulkTagMode("add"); setBulkTagOpen(true); }}>
            <TagIcon className="h-4 w-4" /> {t("tags", { defaultValue: "Tags" })}
          </Button>
          <Button size="sm" variant="danger" disabled={bulkDelete.isPending} onClick={() => bulkDelete.mutate([...selected], { onSuccess: clearSel })}>
            <Trash2 className="h-4 w-4" /> {t("delete", { defaultValue: "Delete" })}
          </Button>
          <Button size="sm" variant="ghost" onClick={clearSel} aria-label={t("clear", { defaultValue: "Clear" })}><X className="h-4 w-4" /></Button>
        </div>
      )}

      {isLoading && <Card className="p-8 text-center text-sm text-muted">{t("loading", { defaultValue: "Loading…" })}</Card>}
      {error && <Card className="p-8 text-center text-sm text-negative">{errText(error)}</Card>}

      {data && groups.length === 0 && (
        <Card className="p-10 text-center text-sm text-muted">{t("no_movements", { defaultValue: "No movements yet." })}</Card>
      )}

      {groups.map((year) => (
        <div key={year.year} className="space-y-3">
          {year.months.map((month) => {
            const monthKey = `month:${month.month}`;
            const monthCollapsed = collapsed.has(monthKey);
            return (
              <Card key={month.month} className="overflow-hidden">
                <button
                  type="button"
                  onClick={() => toggleCollapse(monthKey)}
                  className="flex w-full items-center justify-between border-b border-border bg-surface-2/40 px-5 py-2.5 text-left transition-colors hover:bg-surface-2/70"
                  aria-expanded={!monthCollapsed}
                >
                  <h3 className="flex items-center gap-1.5 text-sm font-semibold text-foreground">
                    {monthCollapsed ? <ChevronRight className="h-4 w-4 text-muted" /> : <ChevronDown className="h-4 w-4 text-muted" />}
                    {monthLabel(month.month, locale)}
                  </h3>
                  <div className="flex items-center gap-3 text-xs">
                    {month.totalIn > 0 && <span className="num text-positive">+{month.totalIn.toFixed(2)}</span>}
                    {month.totalOut > 0 && <span className="num text-muted">−{month.totalOut.toFixed(2)}</span>}
                  </div>
                </button>
                {!monthCollapsed && (
                  <div className="px-5">
                    {month.days.map((day) => {
                      const dayKey = `day:${day.date}`;
                      const dayCollapsed = collapsed.has(dayKey);
                      return (
                        <div key={day.date} className="border-b border-border last:border-0">
                          <button
                            type="button"
                            onClick={() => toggleCollapse(dayKey)}
                            className="flex w-full items-center gap-1 pt-3 pb-1 text-left text-xs font-medium uppercase tracking-wide text-muted-2 hover:text-foreground"
                            aria-expanded={!dayCollapsed}
                          >
                            {dayCollapsed ? <ChevronRight className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
                            {dayLabel(day.date, locale)}
                            {dayCollapsed && <span className="ml-1 normal-case text-muted-2">· {t("n_items", { defaultValue: "{{n}} items", n: day.items.length })}</span>}
                          </button>
                          {!dayCollapsed && (
                            <ul className="divide-y divide-border">
                              {day.items.map((m) => (
                                <MovementRow
                                  key={m.id}
                                  m={m}
                                  locale={locale}
                                  onEdit={() => openEdit(m)}
                                  onDelete={() => setDeleting(m)}
                                  onMakeRecurring={() => { setRecFreq("monthly"); setRecurringFrom(m); }}
                                  selected={selectMode ? selected.has(m.id) : undefined}
                                  onToggleSelect={selectMode ? () => toggleSel(m.id) : undefined}
                                />
                              ))}
                            </ul>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </Card>
            );
          })}
        </div>
      ))}

      <Modal open={mvModal.open} onClose={() => setMvModal({ open: false })} title={mvModal.editing ? t("edit_movement", { defaultValue: "Edit Movement" }) : t("new_movement", { defaultValue: "New Movement" })}>
        <MovementForm
          initial={mvModal.editing}
          sources={sources ?? []}
          tags={tags ?? []}
          pending={createMovement.isPending || updateMovement.isPending}
          error={formError}
          onCancel={() => setMvModal({ open: false })}
          onSubmit={submitMovement}
        />
      </Modal>

      <Modal open={trModal.open} onClose={() => setTrModal({ open: false })} title={trModal.editing ? t("edit_transfer", { defaultValue: "Edit Transfer" }) : t("new_transfer", { defaultValue: "New Transfer" })}>
        <TransferForm
          initial={trModal.editing}
          sources={realSources ?? []}
          tags={tags ?? []}
          pending={createTransfer.isPending || updateTransfer.isPending}
          error={formError}
          onCancel={() => setTrModal({ open: false })}
          onSubmit={submitTransfer}
        />
      </Modal>

      <Modal
        open={bulkTagOpen}
        onClose={() => setBulkTagOpen(false)}
        title={t("bulk_tag_title", { defaultValue: "Tag {{n}} movements", n: selected.size })}
        footer={
          <>
            <Button variant="ghost" onClick={() => setBulkTagOpen(false)}>{t("cancel", { defaultValue: "Cancel" })}</Button>
            <Button
              disabled={bulkSetTags.isPending || bulkTagIds.length === 0}
              onClick={() => bulkSetTags.mutate({ ids: [...selected], tagIds: bulkTagIds, mode: bulkTagMode }, { onSuccess: () => { setBulkTagOpen(false); clearSel(); } })}
            >
              {t("apply", { defaultValue: "Apply" })}
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <div className="grid grid-cols-3 gap-2">
            {(["add", "remove", "replace"] as const).map((m) => (
              <button key={m} type="button" onClick={() => setBulkTagMode(m)} className={cn("h-9 rounded-[var(--radius-control)] border text-sm font-medium", bulkTagMode === m ? "border-primary bg-accent-soft text-primary" : "border-border text-muted")}>
                {t(`tag_mode_${m}`, { defaultValue: m })}
              </button>
            ))}
          </div>
          <div className="flex flex-wrap gap-1.5">
            {(tags ?? []).map((tg) => {
              const on = bulkTagIds.includes(tg.id);
              return (
                <button key={tg.id} type="button" onClick={() => toggleBulkTag(tg.id)} className={cn("rounded-full border px-2.5 py-1 text-xs font-medium transition-colors", on ? "border-primary bg-accent-soft text-primary" : "border-border text-muted hover:text-foreground")}>
                  <span className="mr-1 inline-block h-2 w-2 rounded-full align-middle" style={{ background: tg.color ?? "var(--muted-2)" }} />
                  {tg.name}
                </button>
              );
            })}
          </div>
          <p className="text-xs text-muted">{t("bulk_tag_hint", { defaultValue: "Add appends, Remove strips, Replace sets exactly these tags." })}</p>
        </div>
      </Modal>

      <Modal open={splitOpen} onClose={() => setSplitOpen(false)} title={t("split_transaction", { defaultValue: "Split transaction" })}>
        <SplitForm
          sources={sources ?? []}
          tags={tags ?? []}
          pending={createSplit.isPending}
          error={formError}
          onCancel={() => setSplitOpen(false)}
          onSubmit={submitSplit}
        />
      </Modal>

      {deleting && (
        <Modal
          open
          onClose={() => setDeleting(undefined)}
          title={t("delete", { defaultValue: "Delete" })}
          footer={
            <>
              <Button variant="ghost" onClick={() => setDeleting(undefined)}>{t("cancel", { defaultValue: "Cancel" })}</Button>
              <Button variant="danger" disabled={del.isPending} onClick={() => del.mutate(deleting.id, { onSuccess: () => setDeleting(undefined) })}>
                {t("delete", { defaultValue: "Delete" })}
              </Button>
            </>
          }
        >
          <p className="text-sm text-muted">
            {isTransfer(deleting)
              ? t("confirm_delete_transfer", { defaultValue: "This will remove both legs of the transfer." })
              : t("confirm_delete_movement", { defaultValue: "This movement will be permanently deleted." })}
          </p>
        </Modal>
      )}

      {calendarOpen && <MovementsCalendar onClose={() => setCalendarOpen(false)} locale={locale} />}

      {recurringFrom && (
        <Modal
          open
          onClose={() => setRecurringFrom(undefined)}
          title={t("make_recurring", { defaultValue: "Make recurring" })}
          footer={
            <>
              <Button variant="ghost" onClick={() => setRecurringFrom(undefined)}>{t("cancel", { defaultValue: "Cancel" })}</Button>
              <Button
                disabled={createRecurring.isPending}
                onClick={() => {
                  const m = recurringFrom;
                  createRecurring.mutate(
                    {
                      name: m.note || m.source_name || t("recurring", { defaultValue: "Recurring" }),
                      amount: m.amount,
                      direction: m.direction,
                      currency: m.source_currency ?? "EUR",
                      frequency: recFreq,
                      start_date: m.date,
                      end_date: null,
                      source_id: m.source_id,
                      apply_mode: "confirm",
                      alert_days_before: 7,
                      alert_if_insufficient: m.direction === "out",
                    },
                    { onSuccess: () => setRecurringFrom(undefined), onError: (e) => setFormError(errText(e)) },
                  );
                }}
              >
                {t("create", { defaultValue: "Create" })}
              </Button>
            </>
          }
        >
          <div className="space-y-4">
            <p className="text-sm text-muted">
              {t("make_recurring_hint", { defaultValue: "Create a recurring rule from \"{{name}}\" ({{amt}}).", name: recurringFrom.note || recurringFrom.source_name || "—", amt: recurringFrom.source_currency ? formatSigned(recurringFrom.direction === "in" ? recurringFrom.amount : -recurringFrom.amount, recurringFrom.source_currency, locale) : String(recurringFrom.amount) })}
            </p>
            <div>
              <p className="mb-1 text-sm font-medium text-foreground">{t("frequency", { defaultValue: "Frequency" })}</p>
              <Select value={recFreq} onChange={(e) => setRecFreq(e.target.value)}>
                {(["daily", "weekly", "monthly", "yearly"] as const).map((f) => (
                  <option key={f} value={f}>{t(`freq_${f}`, { defaultValue: f })}</option>
                ))}
              </Select>
            </div>
            {formError ? <p className="text-sm text-negative">{formError}</p> : null}
          </div>
        </Modal>
      )}
    </div>
  );
}
