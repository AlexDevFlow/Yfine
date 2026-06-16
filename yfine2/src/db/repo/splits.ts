/**
 * NEW FEATURE — split transactions. Schema-compatible: a split is N movements
 * (one per category line, each tagged) sharing the same source/date/note/direction.
 * Each line is a real categorized movement, so budgets/stats get the correct
 * per-tag amounts automatically. No schema change.
 */
import type { SqlExecutor } from "../types";
import { DomainError } from "../errors";
import { round2 } from "@/domain/money";
import { createMovement } from "./movements";
import { getSource } from "./sources";

export interface SplitLine {
  amount: number;
  tagId?: number | null;
  note?: string | null;
}

export interface NewSplit {
  source_id?: number | null;
  direction: "in" | "out";
  date: string;
  note?: string | null;
  lines: SplitLine[];
  exclude_from_stats?: boolean;
}

export function splitTotal(lines: readonly SplitLine[]): number {
  return round2(lines.reduce((s, l) => s + (Number(l.amount) || 0), 0));
}

export async function createSplit(db: SqlExecutor, input: NewSplit): Promise<number[]> {
  if (!input.lines.length) throw new DomainError("invalid_amount");
  if (input.lines.some((l) => !(l.amount > 0))) throw new DomainError("invalid_amount");
  if (input.source_id != null && !(await getSource(db, input.source_id))) throw new DomainError("not_found");

  const ids: number[] = [];
  for (const line of input.lines) {
    const id = await createMovement(db, {
      source_id: input.source_id ?? null,
      amount: line.amount,
      direction: input.direction,
      date: input.date,
      // line note falls back to the shared note so the parts read together
      note: line.note?.trim() || input.note || null,
      tagIds: line.tagId != null ? [line.tagId] : [],
      exclude_from_stats: input.exclude_from_stats,
    });
    ids.push(id);
  }
  return ids;
}
