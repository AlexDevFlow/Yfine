/**
 * Savings deposits. A "saving" is the IN leg of a transfer into the currency's
 * savings fund (refactor-analysis/sources-savings.md §B). Conservation: net
 * worth in that currency is unchanged — money leaves the from-source and enters
 * the fund. The exposed "saving id" is the IN-leg movement id.
 */
import type { SqlExecutor } from "../types";
import { DomainError } from "../errors";
import { ensureFundForCurrency, getSource } from "./sources";
import { createTransferPair, deleteMovementCascade } from "./transfers";

export interface NewSaving {
  fromSourceId: number;
  amount: number;
  date: string;
  note?: string | null;
  tagIds?: number[];
  /** Optional explicit currency; must match the from-source's currency. */
  currency?: string;
}

/** Create a savings deposit. Returns the IN-leg movement id (the "saving id"). */
export async function createSaving(
  db: SqlExecutor,
  input: NewSaving,
  fundLabel = "Savings Fund",
): Promise<number> {
  if (!(input.amount > 0)) throw new DomainError("invalid_amount");
  const from = await getSource(db, input.fromSourceId);
  if (!from) throw new DomainError("not_found");
  if (from.is_savings_fund === 1) throw new DomainError("fund_save_rejected");

  let currency = from.currency;
  if (input.currency) {
    const requested = input.currency.trim().toUpperCase();
    if (requested !== from.currency) throw new DomainError("currency_mismatch");
    currency = requested;
  }

  const fund = await ensureFundForCurrency(db, currency, fundLabel);
  const { inId } = await createTransferPair(db, {
    fromSourceId: from.id,
    toSourceId: fund.id,
    amount: input.amount,
    date: input.date,
    note: input.note ?? null,
    tagIds: input.tagIds ?? [],
    isSavingsContribution: true,
  });
  return inId;
}

/** Delete a saving — reverses BOTH legs (refund to the from-source + fund debit). */
export async function deleteSaving(db: SqlExecutor, savingInLegId: number): Promise<void> {
  await deleteMovementCascade(db, savingInLegId);
}

export interface EnrichedSaving {
  /** The IN-leg movement id (the "saving id"). */
  id: number;
  amount: number;
  /** Currency of the savings fund the money landed in. */
  currency: string;
  date: string;
  note: string | null;
  /** Where the money came from (the OUT-leg's source). */
  from_source_id: number | null;
  from_source_name: string | null;
  fund_source_id: number | null;
  tags: { id: number; name: string; color: string | null }[];
}

/**
 * List savings deposits — the IN-legs flagged `is_savings_contribution`, newest
 * first. Mirrors the legacy `list_savings` contract (currency comes from the
 * fund; "from" comes from the partner OUT-leg's source).
 */
export async function listSavings(
  db: SqlExecutor,
  opts: { limit?: number; offset?: number } = {},
): Promise<EnrichedSaving[]> {
  const limit = opts.limit ?? 200;
  const offset = opts.offset ?? 0;
  const rows = await db.select<{
    id: number;
    amount: number;
    date: string;
    note: string | null;
    fund_source_id: number | null;
    currency: string | null;
    from_source_id: number | null;
    from_source_name: string | null;
  }>(
    `SELECT m.id, m.amount, m.date, m.note,
       m.source_id AS fund_source_id, f.currency AS currency,
       (SELECT pm.source_id FROM movements pm WHERE pm.id = m.transfer_pair_id) AS from_source_id,
       (SELECT ps.name FROM movements pm LEFT JOIN sources ps ON pm.source_id = ps.id WHERE pm.id = m.transfer_pair_id) AS from_source_name
     FROM movements m LEFT JOIN sources f ON m.source_id = f.id
     WHERE m.is_savings_contribution = 1
     ORDER BY m.date DESC, m.id DESC
     LIMIT ? OFFSET ?`,
    [limit, offset],
  );

  const out: EnrichedSaving[] = rows.map((r) => ({
    id: r.id,
    amount: r.amount,
    currency: r.currency ?? "",
    date: r.date,
    note: r.note,
    from_source_id: r.from_source_id,
    from_source_name: r.from_source_name,
    fund_source_id: r.fund_source_id,
    tags: [],
  }));

  if (rows.length) {
    const byId = new Map(out.map((s) => [s.id, s]));
    const ids = rows.map((r) => r.id);
    const ph = ids.map(() => "?").join(",");
    const tagRows = await db.select<{ movement_id: number; id: number; name: string; color: string | null }>(
      `SELECT mt.movement_id, t.id, t.name, t.color
       FROM movement_tag mt JOIN tags t ON t.id = mt.tag_id
       WHERE mt.movement_id IN (${ph}) ORDER BY t.name COLLATE NOCASE`,
      ids,
    );
    for (const tr of tagRows) byId.get(tr.movement_id)?.tags.push({ id: tr.id, name: tr.name, color: tr.color });
  }

  return out;
}
