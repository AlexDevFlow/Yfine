import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getDb } from "./connection";
import * as sources from "./repo/sources";
import * as movements from "./repo/movements";
import * as dashboard from "./repo/dashboard";
import * as recurring from "./repo/recurring";
import * as notifications from "./repo/notifications";
import * as budgets from "./repo/budgets";
import * as goals from "./repo/goals";
import * as whims from "./repo/whims";
import * as portfolios from "./repo/portfolios";
import { importFile } from "./backup";
import { commitCsv } from "./importers/csv";
import * as settingsRepo from "./repo/settings";
import { createSplit, type NewSplit } from "./repo/splits";
import { forecastCashflow } from "./repo/forecast";
import { consolidatedNetWorth } from "./repo/consolidate";
import { searchAll, type SearchItem } from "./repo/search";
import * as tags from "./repo/tags";
import * as savings from "./repo/savings";
import * as history from "./repo/history";
import { round2 } from "@/domain/money";
import { monthEnd, monthStart, todayISO } from "@/lib/date";
import type { SourceRow, TagRow } from "./schema-types";
import { withTx } from "./tx";

// Every money-derived view; mutations that move money invalidate the lot
// (cheap against the local DB, and avoids stale budgets/forecast/consolidated).
const MONEY_KEYS = ["movements", "sources", "dashboard", "budgets", "goals", "whims", "recurring", "forecast", "consolidated", "portfolios", "notifications", "savings", "history", "movementCounts"];
function invalidateMoney(qc: ReturnType<typeof useQueryClient>) {
  for (const k of MONEY_KEYS) void qc.invalidateQueries({ queryKey: [k] });
}

export interface SourceWithBalance extends SourceRow {
  balance: number;
}

export function useSources() {
  return useQuery({
    queryKey: ["sources"],
    queryFn: async (): Promise<SourceWithBalance[]> => {
      const db = await getDb();
      const [list, balances] = await Promise.all([
        sources.listSources(db, { includeHidden: true }),
        sources.getBalancesBatch(db),
      ]);
      return list.map((s) => ({
        ...s,
        balance: balances.get(s.id) ?? round2(s.starting_balance),
      }));
    },
  });
}

export function useCreateSource() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (data: sources.NewSource) => {
      const db = await getDb();
      return sources.createSource(db, data);
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["sources"] });
      void qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}

export function useUpdateSource() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (v: { id: number; patch: sources.SourcePatch }) => {
      const db = await getDb();
      return sources.updateSource(db, v.id, v.patch);
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["sources"] });
      void qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}

export function useDeleteSource() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (v: { id: number; action: sources.DeleteAction }) => {
      const db = await getDb();
      return sources.deleteSource(db, v.id, v.action);
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["sources"] });
      void qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}

export function useSetFundVisibility() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (v: { id: number; hidden: boolean }) => {
      const db = await getDb();
      return sources.setFundVisibility(db, v.id, v.hidden);
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["sources"] });
      void qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}

// ---- tags ----
export function useTags() {
  return useQuery({
    queryKey: ["tags"],
    queryFn: async (): Promise<TagRow[]> => tags.listTags(await getDb()),
  });
}

export function useTagsWithUsage() {
  return useQuery({
    queryKey: ["tags", "usage"],
    queryFn: async () => tags.listTagsWithUsage(await getDb()),
  });
}

function useTagMutation<TArgs, TResult>(fn: (db: import("./types").SqlExecutor, a: TArgs) => Promise<TResult>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (a: TArgs) => {
      const db = await getDb();
      return withTx(db, () => fn(db, a));
    },
    // Tag edits ripple into every tagged movement, budget rules, and the dashboard.
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["tags"] });
      invalidateMoney(qc);
    },
  });
}

export const useCreateTag = () => useTagMutation((db, data: tags.NewTag) => tags.createTag(db, data));
export const useUpdateTag = () => useTagMutation((db, v: { id: number; patch: tags.TagPatch }) => tags.updateTag(db, v.id, v.patch));
export const useDeleteTag = () => useTagMutation((db, id: number) => tags.deleteTag(db, id));

// ---- savings ----
export function useSavings() {
  return useQuery({
    queryKey: ["savings"],
    queryFn: async () => savings.listSavings(await getDb()),
  });
}
export const useCreateSaving = () => useBroadMutation((db, data: savings.NewSaving) => savings.createSaving(db, data));
export const useDeleteSaving = () => useBroadMutation((db, id: number) => savings.deleteSaving(db, id));

// ---- history (charts / sparklines) ----
export function useNetWorthHistory(currency: string | null) {
  return useQuery({
    queryKey: ["history", "networth", currency],
    enabled: currency != null,
    queryFn: async () => (currency ? history.netWorthHistory(await getDb(), currency) : []),
  });
}
export function useSourceHistory(sourceId: number) {
  return useQuery({
    queryKey: ["history", "source", sourceId],
    queryFn: async () => history.sourceBalanceHistory(await getDb(), sourceId),
  });
}
export function useMovementCounts() {
  return useQuery({
    queryKey: ["movementCounts"],
    queryFn: async () => Object.fromEntries(await history.movementCounts(await getDb())) as Record<number, number>,
  });
}

// ---- movements ----
export function useMovements(filters: movements.MovementFilters, pageSize = 200) {
  return useQuery({
    queryKey: ["movements", filters],
    queryFn: async () => {
      const db = await getDb();
      const [items, total] = await Promise.all([
        movements.listMovements(db, filters, { limit: pageSize }),
        movements.countMovements(db, filters),
      ]);
      return { items, total };
    },
  });
}

/** Money mutations run atomically (withTx) and refresh every derived view. */
function useMoneyMutation<TArgs, TResult>(fn: (db: import("./types").SqlExecutor, args: TArgs) => Promise<TResult>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (args: TArgs) => {
      const db = await getDb();
      return withTx(db, () => fn(db, args));
    },
    onSuccess: () => invalidateMoney(qc),
  });
}

// ---- dashboard + search ----
export function useDashboard() {
  return useQuery({
    queryKey: ["dashboard"],
    queryFn: async () => {
      const db = await getDb();
      const today = todayISO();
      const ms = monthStart(today);
      const me = monthEnd(today);
      const [nw, flow, savings, recent, upcoming] = await Promise.all([
        dashboard.netWorth(db),
        dashboard.monthlyFlow(db, ms, me),
        dashboard.monthlySavings(db, ms, me),
        movements.listMovements(db, { excludeTransferIn: true }, { limit: 6 }),
        dashboard.upcomingRecurring(db, today, 5),
      ]);
      const primaryCurrency =
        Object.entries(nw).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))[0]?.[0] ?? "EUR";
      const comparison = await dashboard.monthlyComparison(db, primaryCurrency, 6, today);
      return { netWorth: nw, primaryCurrency, flow, savings, recent, upcoming, comparison };
    },
  });
}

export function useSearch(q: string) {
  return useQuery({
    queryKey: ["search", q],
    queryFn: async (): Promise<SearchItem[]> => searchAll(await getDb(), q, 8),
    enabled: q.trim().length >= 2,
    staleTime: 5_000,
  });
}

// ---- recurring ----
export function useRecurring() {
  return useQuery({
    queryKey: ["recurring"],
    queryFn: async () => {
      const db = await getDb();
      const today = todayISO();
      const [items, summary] = await Promise.all([
        recurring.listRecurring(db, today),
        recurring.monthlySummary(db),
      ]);
      return { items, summary, today };
    },
  });
}

function useRecurringMutation<TArgs, TResult>(fn: (db: import("./types").SqlExecutor, a: TArgs) => Promise<TResult>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (a: TArgs) => {
      const db = await getDb();
      return withTx(db, () => fn(db, a));
    },
    onSuccess: () => invalidateMoney(qc),
  });
}
export const useCreateRecurring = () => useRecurringMutation((db, data: recurring.NewRecurring) => recurring.createRecurring(db, data));
export const useUpdateRecurring = () => useRecurringMutation((db, v: { id: number; patch: recurring.RecurringPatch }) => recurring.updateRecurring(db, v.id, v.patch));
export const useDeleteRecurring = () => useRecurringMutation((db, id: number) => recurring.deleteRecurring(db, id));
export const useApplyRecurring = () => useRecurringMutation((db, v: { id: number; amount?: number; note?: string }) => recurring.applyRecurringById(db, v.id, { amount: v.amount, note: v.note }, todayISO()));

// ---- notifications ----
export function useNotifications() {
  return useQuery({
    queryKey: ["notifications", "list"],
    queryFn: async () => notifications.listNotifications(await getDb(), { limit: 100 }),
  });
}
export function useUnreadCount() {
  return useQuery({
    queryKey: ["notifications", "unread"],
    queryFn: async () => notifications.unreadCount(await getDb()),
  });
}
function useNotifMutation<TArgs, TResult>(fn: (db: import("./types").SqlExecutor, a: TArgs) => Promise<TResult>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (a: TArgs) => fn(await getDb(), a),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["notifications"] }),
  });
}
export const useMarkRead = () => useNotifMutation((db, id: number) => notifications.markRead(db, id));
export const useMarkAllRead = () => useNotifMutation((db, _: void) => notifications.markAllRead(db));
export const useDeleteNotification = () => useNotifMutation((db, id: number) => notifications.deleteNotification(db, id));
export const useDeleteAllRead = () => useNotifMutation((db, _: void) => notifications.deleteAllRead(db));

// ---- budgets / goals / whims (money-moving → broad invalidation) ----
function useBroadMutation<TArgs, TResult>(fn: (db: import("./types").SqlExecutor, a: TArgs) => Promise<TResult>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (a: TArgs) => {
      const db = await getDb();
      return withTx(db, () => fn(db, a));
    },
    onSuccess: () => invalidateMoney(qc),
  });
}

export function useBudgets(offset = 0) {
  return useQuery({ queryKey: ["budgets", offset], queryFn: async () => budgets.listBudgetStatuses(await getDb(), offset) });
}
export const useCreateBudget = () => useBroadMutation((db, data: budgets.NewBudget) => budgets.createBudget(db, data));
export const useUpdateBudget = () => useBroadMutation((db, v: { id: number; patch: budgets.BudgetPatch }) => budgets.updateBudget(db, v.id, v.patch));
export const useDeleteBudget = () => useBroadMutation((db, id: number) => budgets.deleteBudget(db, id));

export function useGoals() {
  return useQuery({ queryKey: ["goals"], queryFn: async () => goals.listGoals(await getDb()) });
}
export const useCreateGoal = () => useBroadMutation((db, data: goals.NewGoal) => goals.createGoal(db, data));
export const useUpdateGoal = () => useBroadMutation((db, v: { id: number; patch: goals.GoalPatch }) => goals.updateGoal(db, v.id, v.patch));
export const useAllocate = () => useBroadMutation((db, v: { goalId: number; input: goals.AllocateInput }) => goals.allocate(db, v.goalId, v.input));
export const useCloseGoal = () => useBroadMutation((db, v: { id: number; toSourceId: number; date?: string }) => goals.closeGoal(db, v.id, v.toSourceId, v.date));
export const useDeleteGoal = () => useBroadMutation((db, id: number) => goals.deleteGoal(db, id));

export function useWhims() {
  return useQuery({ queryKey: ["whims"], queryFn: async () => whims.listWhims(await getDb()) });
}
export const useCreateWhim = () => useBroadMutation((db, data: whims.NewWhim) => whims.createWhim(db, data));
export const useUpdateWhim = () => useBroadMutation((db, v: { id: number; patch: whims.WhimPatch }) => whims.updateWhim(db, v.id, v.patch));
export const usePurchaseWhim = () => useBroadMutation((db, v: { id: number; sourceId: number; note?: string; tagIds?: number[]; amount?: number }) => whims.purchaseWhim(db, v.id, { sourceId: v.sourceId, note: v.note, tagIds: v.tagIds, amount: v.amount }));
export const useDismissWhim = () => useBroadMutation((db, id: number) => whims.dismissWhim(db, id));
export const useRestoreWhim = () => useBroadMutation((db, id: number) => whims.restoreWhim(db, id));
export const useDeleteWhim = () => useBroadMutation((db, id: number) => whims.deleteWhim(db, id));
export const useStartSaving = () => useBroadMutation((db, id: number) => whims.startSavingForWhim(db, id));

// ---- portfolios ----
export function usePortfolios() {
  return useQuery({
    queryKey: ["portfolios"],
    queryFn: async () => {
      const db = await getDb();
      const list = await portfolios.listPortfolios(db);
      return Promise.all(list.map((p) => portfolios.summarizePortfolio(db, p.id)));
    },
  });
}
function usePortfolioMutation<TArgs, TResult>(fn: (db: import("./types").SqlExecutor, a: TArgs) => Promise<TResult>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (a: TArgs) => {
      const db = await getDb();
      return withTx(db, () => fn(db, a));
    },
    onSuccess: () => {
      for (const k of ["portfolios", "dashboard", "consolidated"]) void qc.invalidateQueries({ queryKey: [k] });
    },
  });
}
export const useCreatePortfolio = () => usePortfolioMutation((db, data: portfolios.NewPortfolio) => portfolios.createPortfolio(db, data));
export const useDeletePortfolio = () => usePortfolioMutation((db, id: number) => portfolios.deletePortfolio(db, id));
export const useCreateHolding = () => usePortfolioMutation((db, data: portfolios.NewHolding) => portfolios.createHolding(db, data));
export const useUpdateHolding = () => usePortfolioMutation((db, v: { id: number; patch: portfolios.HoldingPatch }) => portfolios.updateHolding(db, v.id, v.patch));
export const useDeleteHolding = () => usePortfolioMutation((db, id: number) => portfolios.deleteHolding(db, id));

// ---- backup / restore / csv import ----
export function useImportBackup() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (bytes: Uint8Array) => importFile(await getDb(), bytes),
    onSuccess: () => void qc.invalidateQueries(), // a restore touches everything
  });
}
export const useCommitCsv = () => useBroadMutation((db, input: Parameters<typeof commitCsv>[1]) => commitCsv(db, input));

// ---- settings / preferences ----
export function usePreferences() {
  return useQuery({ queryKey: ["settings"], queryFn: async () => settingsRepo.getSettings(await getDb()) });
}
export function useUpdatePreferences() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (patch: settingsRepo.SettingsPatch) => settingsRepo.updateSettings(await getDb(), patch),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["settings"] });
      void qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}

export const useCreateMovement = () =>
  useMoneyMutation((db, data: movements.NewMovement) => movements.createMovement(db, data));
export const useUpdateMovement = () =>
  useMoneyMutation((db, v: { id: number; patch: movements.MovementPatch }) =>
    movements.updateMovement(db, v.id, v.patch),
  );
export const useDeleteMovement = () =>
  useMoneyMutation((db, id: number) => movements.deleteMovement(db, id));
export const useCreateTransfer = () =>
  useMoneyMutation((db, t: movements.NewTransfer) => movements.createTransfer(db, t));
export const useUpdateTransfer = () =>
  useMoneyMutation((db, v: { outLegId: number; patch: movements.TransferPatch }) =>
    movements.updateTransfer(db, v.outLegId, v.patch),
  );
export const useBulkDelete = () =>
  useMoneyMutation((db, ids: number[]) => movements.bulkDelete(db, ids));
export const useBulkSetTags = () =>
  useMoneyMutation((db, v: { ids: number[]; tagIds: number[]; mode: movements.TagMode }) =>
    movements.bulkSetTags(db, v.ids, v.tagIds, v.mode),
  );
export const useBulkSetSource = () =>
  useMoneyMutation((db, v: { ids: number[]; sourceId: number | null }) =>
    movements.bulkSetSource(db, v.ids, v.sourceId),
  );

// ---- NEW features: split / forecast / consolidated ----
export const useCreateSplit = () => useMoneyMutation((db, input: NewSplit) => createSplit(db, input));

export function useForecast(horizonDays = 90) {
  return useQuery({
    queryKey: ["forecast", horizonDays],
    queryFn: async () => forecastCashflow(await getDb(), horizonDays, todayISO()),
  });
}

export function useConsolidated(base: string | null) {
  return useQuery({
    queryKey: ["consolidated", base],
    enabled: !!base,
    queryFn: async () => consolidatedNetWorth(await getDb(), base as string),
  });
}
