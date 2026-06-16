import { Plus, TrendingUp, Trash2, Pencil, AlertTriangle, LineChart as LineChartIcon } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Field, Input, Select } from "@/components/ui/input";
import { Modal } from "@/components/ui/modal";
import { RangeChart } from "@/components/ui/range-chart";
import { isPreviewDb } from "@/db/connection";
import {
  useCreateHolding,
  useCreatePortfolio,
  useDeleteHolding,
  useDeletePortfolio,
  usePortfolioHistory,
  usePortfolios,
  useSources,
  useUpdateHolding,
  type SourceWithBalance,
} from "@/db/queries";
import type { EnrichedHolding, NewHolding, NewPortfolio, PortfolioSummary } from "@/db/repo/portfolios";
import { cn } from "@/lib/cn";
import { dayLabel } from "@/lib/date";
import { formatMoney, formatSigned } from "@/lib/format";
import { useErrorText } from "@/lib/use-error-text";

/** Lazily-loaded portfolio value-over-time chart (rendered when expanded). */
function PortfolioHistory({ id, currency, locale }: { id: number; currency: string; locale?: string }) {
  const { t } = useTranslation();
  const { data, isLoading } = usePortfolioHistory(id);
  if (isLoading) return <p className="pb-2 text-xs text-muted">{t("loading", { defaultValue: "Loading…" })}</p>;
  if (!data || data.length < 2) return <p className="pb-2 text-xs text-muted">{t("not_enough_history", { defaultValue: "Not enough history to chart yet." })}</p>;
  return (
    <div className="pb-1">
      <RangeChart points={data} height={140} format={(n) => formatMoney(n, currency, locale)} formatDate={(d) => dayLabel(d, locale)} />
    </div>
  );
}

const CURRENCIES = ["EUR", "USD", "GBP", "CHF", "JPY", "CAD", "AUD", "CNY", "BTC", "ETH"];

function PortfolioForm({ sources, onCancel, onSubmit, pending, error }: {
  sources: SourceWithBalance[]; onCancel: () => void; onSubmit: (v: NewPortfolio) => void; pending: boolean; error?: string;
}) {
  const { t } = useTranslation();
  const [name, setName] = useState("");
  const [kind, setKind] = useState<"crypto" | "stocks" | "mixed">("mixed");
  const [base, setBase] = useState("EUR");
  const [sourceId, setSourceId] = useState(String(sources[0]?.id ?? ""));
  const submit = (e: FormEvent) => { e.preventDefault(); onSubmit({ name: name.trim(), kind, base_currency: base, source_id: Number(sourceId) }); };
  return (
    <form onSubmit={submit} className="space-y-4">
      <Field label={t("name", { defaultValue: "Name" })} htmlFor="pf-name"><Input id="pf-name" value={name} onChange={(e) => setName(e.target.value)} required autoFocus /></Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label={t("kind", { defaultValue: "Kind" })} htmlFor="pf-kind">
          <Select id="pf-kind" value={kind} onChange={(e) => setKind(e.target.value as "crypto" | "stocks" | "mixed")}>
            <option value="mixed">{t("kind_mixed", { defaultValue: "Mixed" })}</option>
            <option value="crypto">{t("kind_crypto", { defaultValue: "Crypto" })}</option>
            <option value="stocks">{t("kind_stocks", { defaultValue: "Stocks" })}</option>
          </Select>
        </Field>
        <Field label={t("base_currency", { defaultValue: "Base currency" })} htmlFor="pf-base">
          <Select id="pf-base" value={base} onChange={(e) => setBase(e.target.value)}>{CURRENCIES.map((c) => <option key={c}>{c}</option>)}</Select>
        </Field>
      </div>
      <Field label={t("linked_source", { defaultValue: "Linked account" })} htmlFor="pf-src">
        <Select id="pf-src" value={sourceId} onChange={(e) => setSourceId(e.target.value)} required>{sources.map((s) => <option key={s.id} value={s.id}>{s.name} · {s.currency}</option>)}</Select>
      </Field>
      {error ? <p className="text-sm text-negative">{error}</p> : null}
      <div className="flex justify-end gap-2 pt-1">
        <Button type="button" variant="ghost" onClick={onCancel}>{t("cancel", { defaultValue: "Cancel" })}</Button>
        <Button type="submit" disabled={pending || !name.trim() || !sourceId}>{t("save", { defaultValue: "Save" })}</Button>
      </div>
    </form>
  );
}

function HoldingForm({ portfolioId, kind, base, initial, onCancel, onSubmit, pending, error }: {
  portfolioId: number; kind: string; base: string; initial?: EnrichedHolding;
  onCancel: () => void; onSubmit: (v: NewHolding) => void; pending: boolean; error?: string;
}) {
  const { t } = useTranslation();
  const [assetClass, setAssetClass] = useState<"crypto" | "stock">(initial?.asset_class ?? (kind === "crypto" ? "crypto" : "stock"));
  const [symbol, setSymbol] = useState(initial?.symbol ?? "");
  const [quantity, setQuantity] = useState(initial ? String(initial.quantity) : "");
  const [avgCost, setAvgCost] = useState(initial ? String(initial.avg_cost) : "");
  const [currency, setCurrency] = useState(initial?.currency ?? base);
  const [manual, setManual] = useState((initial?.manual_price ?? 0) === 1);
  const [price, setPrice] = useState(initial?.last_price != null ? String(initial.last_price) : "");
  const submit = (e: FormEvent) => {
    e.preventDefault();
    onSubmit({
      portfolio_id: portfolioId, asset_class: assetClass, symbol: symbol.trim().toUpperCase(),
      quantity: Number(quantity) || 0, avg_cost: Number(avgCost) || 0, currency,
      manual_price: manual, last_price: manual && price ? Number(price) : null,
    });
  };
  return (
    <form onSubmit={submit} className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        {kind === "mixed" && (
          <Field label={t("asset_class", { defaultValue: "Type" })} htmlFor="h-class">
            <Select id="h-class" value={assetClass} onChange={(e) => setAssetClass(e.target.value as "crypto" | "stock")}>
              <option value="stock">{t("stock", { defaultValue: "Stock" })}</option>
              <option value="crypto">{t("crypto", { defaultValue: "Crypto" })}</option>
            </Select>
          </Field>
        )}
        <Field label={t("symbol", { defaultValue: "Symbol" })} htmlFor="h-sym"><Input id="h-sym" value={symbol} onChange={(e) => setSymbol(e.target.value.toUpperCase())} required maxLength={32} autoFocus /></Field>
      </div>
      <div className="grid grid-cols-3 gap-3">
        <Field label={t("quantity", { defaultValue: "Quantity" })} htmlFor="h-qty"><Input id="h-qty" type="number" step="any" value={quantity} onChange={(e) => setQuantity(e.target.value)} className="num" /></Field>
        <Field label={t("avg_cost", { defaultValue: "Avg cost" })} htmlFor="h-cost"><Input id="h-cost" type="number" step="any" value={avgCost} onChange={(e) => setAvgCost(e.target.value)} className="num" /></Field>
        <Field label={t("currency", { defaultValue: "Currency" })} htmlFor="h-ccy"><Select id="h-ccy" value={currency} onChange={(e) => setCurrency(e.target.value)}>{CURRENCIES.map((c) => <option key={c}>{c}</option>)}</Select></Field>
      </div>
      <label className="flex items-center gap-2 text-sm text-foreground">
        <input type="checkbox" checked={manual} onChange={(e) => setManual(e.target.checked)} /> {t("manual_price", { defaultValue: "Set price manually" })}
      </label>
      {manual && <Field label={t("price", { defaultValue: "Price" })} htmlFor="h-price"><Input id="h-price" type="number" step="any" value={price} onChange={(e) => setPrice(e.target.value)} className="num" /></Field>}
      {error ? <p className="text-sm text-negative">{error}</p> : null}
      <div className="flex justify-end gap-2 pt-1">
        <Button type="button" variant="ghost" onClick={onCancel}>{t("cancel", { defaultValue: "Cancel" })}</Button>
        <Button type="submit" disabled={pending || !symbol.trim()}>{t("save", { defaultValue: "Save" })}</Button>
      </div>
    </form>
  );
}

export function PortfoliosPage() {
  const { t, i18n } = useTranslation();
  const locale = i18n.resolvedLanguage;
  const errText = useErrorText();
  const { data: list, isLoading } = usePortfolios();
  const { data: sources } = useSources();
  const createP = useCreatePortfolio();
  const delP = useDeletePortfolio();
  const createH = useCreateHolding();
  const updateH = useUpdateHolding();
  const delH = useDeleteHolding();

  const [pForm, setPForm] = useState(false);
  const [hForm, setHForm] = useState<{ portfolio: PortfolioSummary; editing?: EnrichedHolding }>();
  const [err, setErr] = useState<string>();
  const [chartOpen, setChartOpen] = useState<Set<number>>(new Set());
  const toggleChart = (id: number) =>
    setChartOpen((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });

  return (
    <div className="space-y-4">
      {isPreviewDb && <div className="rounded-[var(--radius-control)] border border-border bg-warning-soft px-3 py-2 text-xs text-warning">{t("preview_db_note", { defaultValue: "Browser preview with seeded sample data." })}</div>}
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted">{t("portfolios_subtitle", { defaultValue: "Investments — manual prices now; live quotes are opt-in." })}</p>
        <Button onClick={() => { setErr(undefined); setPForm(true); }} disabled={(sources?.length ?? 0) === 0}><Plus className="h-4 w-4" /> {t("new_portfolio", { defaultValue: "New Portfolio" })}</Button>
      </div>
      {isLoading && <Card className="p-8 text-center text-sm text-muted">{t("loading", { defaultValue: "Loading…" })}</Card>}
      {list && list.length === 0 && <Card className="p-10 text-center text-sm text-muted">{t("no_portfolios", { defaultValue: "No portfolios yet." })}</Card>}

      {(list ?? []).map((p) => (
        <Card key={p.portfolio.id}>
          <CardHeader
            title={<span className="flex items-center gap-2"><TrendingUp className="h-4 w-4 text-primary" />{p.portfolio.name}</span>}
            subtitle={`${p.source_name ?? "—"} · ${p.portfolio.base_currency}`}
            action={
              <div className="flex items-center gap-2">
                <div className="text-right">
                  <p className="num text-base font-semibold text-foreground">{formatMoney(p.total_value, p.portfolio.base_currency, locale)}</p>
                  {p.total_pnl != null && <p className={cn("num text-xs", p.total_pnl >= 0 ? "text-positive" : "text-negative")}>{formatSigned(p.total_pnl, p.portfolio.base_currency, locale)} ({p.total_pnl_pct}%)</p>}
                </div>
                <button onClick={() => toggleChart(p.portfolio.id)} aria-label={t("history", { defaultValue: "History" })} aria-expanded={chartOpen.has(p.portfolio.id)} className={cn("rounded-md p-1.5 hover:bg-surface-2 hover:text-foreground", chartOpen.has(p.portfolio.id) ? "text-primary" : "text-muted")}><LineChartIcon className="h-4 w-4" /></button>
                <button onClick={() => delP.mutate(p.portfolio.id)} className="rounded-md p-1.5 text-muted hover:bg-negative-soft hover:text-negative"><Trash2 className="h-4 w-4" /></button>
              </div>
            }
          />
          <CardContent className="pt-3">
            {chartOpen.has(p.portfolio.id) && (
              <div className="mb-3 border-b border-border pb-2">
                <PortfolioHistory id={p.portfolio.id} currency={p.portfolio.base_currency} locale={locale} />
              </div>
            )}
            {p.has_unconverted && (
              <p className="mb-2 flex items-center gap-1.5 text-xs text-warning"><AlertTriangle className="h-3.5 w-3.5" />{t("missing_fx", { defaultValue: "Some holdings use a currency with no exchange rate — totals may be approximate." })}</p>
            )}
            {p.holdings.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead><tr className="text-left text-xs text-muted">
                    <th className="py-1 font-medium">{t("symbol", { defaultValue: "Symbol" })}</th>
                    <th className="py-1 text-right font-medium">{t("quantity", { defaultValue: "Qty" })}</th>
                    <th className="py-1 text-right font-medium">{t("price", { defaultValue: "Price" })}</th>
                    <th className="py-1 text-right font-medium">{t("value", { defaultValue: "Value" })}</th>
                    <th className="py-1 text-right font-medium">{t("pnl", { defaultValue: "P/L" })}</th>
                    <th />
                  </tr></thead>
                  <tbody>
                    {p.holdings.map((h) => (
                      <tr key={h.id} className="border-t border-border">
                        <td className="py-2"><span className="font-medium text-foreground">{h.symbol}</span> <span className="text-xs text-muted">{h.currency}</span></td>
                        <td className="num py-2 text-right text-muted">{h.quantity}</td>
                        <td className="num py-2 text-right text-muted">{h.last_price != null ? formatMoney(h.last_price, h.currency, locale) : "—"}</td>
                        <td className="num py-2 text-right text-foreground">{h.market_value != null ? formatMoney(h.market_value, h.currency, locale) : "—"}</td>
                        <td className={cn("num py-2 text-right", h.unrealized_pnl == null ? "text-muted" : h.unrealized_pnl >= 0 ? "text-positive" : "text-negative")}>{h.unrealized_pnl != null ? `${h.unrealized_pnl_pct}%` : "—"}</td>
                        <td className="py-2 text-right">
                          <button onClick={() => { setErr(undefined); setHForm({ portfolio: p, editing: h }); }} className="rounded p-1 text-muted hover:text-foreground"><Pencil className="h-3.5 w-3.5" /></button>
                          <button onClick={() => delH.mutate(h.id)} className="rounded p-1 text-muted hover:text-negative"><Trash2 className="h-3.5 w-3.5" /></button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <p className="text-sm text-muted">{t("no_holdings", { defaultValue: "No holdings yet." })}</p>}
            <div className="mt-3">
              <Button size="sm" variant="outline" onClick={() => { setErr(undefined); setHForm({ portfolio: p }); }}><Plus className="h-4 w-4" /> {t("add_holding", { defaultValue: "Add holding" })}</Button>
            </div>
          </CardContent>
        </Card>
      ))}

      <Modal open={pForm} onClose={() => setPForm(false)} title={t("new_portfolio", { defaultValue: "New Portfolio" })}>
        <PortfolioForm sources={sources ?? []} pending={createP.isPending} error={err} onCancel={() => setPForm(false)} onSubmit={(v) => createP.mutate(v, { onSuccess: () => setPForm(false), onError: (e) => setErr(errText(e)) })} />
      </Modal>

      {hForm && (
        <Modal open onClose={() => setHForm(undefined)} title={hForm.editing ? t("edit_holding", { defaultValue: "Edit Holding" }) : t("add_holding", { defaultValue: "Add Holding" })}>
          <HoldingForm
            portfolioId={hForm.portfolio.portfolio.id} kind={hForm.portfolio.portfolio.kind} base={hForm.portfolio.portfolio.base_currency} initial={hForm.editing}
            pending={createH.isPending || updateH.isPending} error={err}
            onCancel={() => setHForm(undefined)}
            onSubmit={(v) => {
              const onDone = { onSuccess: () => setHForm(undefined), onError: (e: unknown) => setErr(errText(e)) };
              if (hForm.editing) updateH.mutate({ id: hForm.editing.id, patch: { symbol: v.symbol, quantity: v.quantity, avg_cost: v.avg_cost, currency: v.currency, manual_price: v.manual_price, last_price: v.last_price } }, onDone);
              else createH.mutate(v, onDone);
            }}
          />
        </Modal>
      )}
    </div>
  );
}
