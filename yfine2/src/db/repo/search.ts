/**
 * Global search across entities (refactor-analysis/dashboard-search.md §3.27-32).
 * Case-insensitive substring (LIKE %q% with wildcards escaped); movements also
 * match an exact amount when q parses as a positive number. Includes GOALS,
 * closing the legacy gap (BUG-3). Each group capped at `limit`.
 */
import type { SqlExecutor } from "../types";

export type SearchType = "movement" | "source" | "tag" | "whim" | "recurring" | "goal";

export interface SearchItem {
  type: SearchType;
  id: number;
  label: string;
  sublabel?: string;
}

function likeParam(q: string): string {
  return "%" + q.replace(/([\\%_])/g, "\\$1") + "%";
}

export async function searchAll(
  db: SqlExecutor,
  query: string,
  limit = 8,
): Promise<SearchItem[]> {
  const q = query.trim();
  if (q.length < 2 || q.length > 100) return [];
  const like = likeParam(q);
  const out: SearchItem[] = [];

  const sources = await db.select<{ id: number; name: string; currency: string }>(
    `SELECT id,name,currency FROM sources WHERE name LIKE ? ESCAPE '\\' ORDER BY name COLLATE NOCASE LIMIT ?`,
    [like, limit],
  );
  for (const s of sources) out.push({ type: "source", id: s.id, label: s.name, sublabel: s.currency });

  const numeric = Number(q.replace(",", "."));
  const amountMatch = Number.isFinite(numeric) && numeric > 0;
  const movs = await db.select<{
    id: number;
    note: string | null;
    amount: number;
    direction: string;
    date: string;
    source_name: string | null;
  }>(
    `SELECT m.id, m.note, m.amount, m.direction, m.date, s.name AS source_name
     FROM movements m LEFT JOIN sources s ON m.source_id = s.id
     WHERE m.note LIKE ? ESCAPE '\\'${amountMatch ? " OR m.amount = ?" : ""}
     ORDER BY m.date DESC, m.id DESC LIMIT ?`,
    amountMatch ? [like, numeric, limit] : [like, limit],
  );
  for (const m of movs) {
    out.push({
      type: "movement",
      id: m.id,
      label: m.note || `${m.direction === "in" ? "+" : "−"}${m.amount}`,
      sublabel: `${m.source_name ?? "External"} · ${m.date}`,
    });
  }

  const tags = await db.select<{ id: number; name: string }>(
    `SELECT id,name FROM tags WHERE name LIKE ? ESCAPE '\\' ORDER BY name COLLATE NOCASE LIMIT ?`,
    [like, limit],
  );
  for (const t of tags) out.push({ type: "tag", id: t.id, label: t.name });

  const whims = await db.select<{ id: number; name: string }>(
    `SELECT id,name FROM whims WHERE name LIKE ? ESCAPE '\\' OR note LIKE ? ESCAPE '\\' ORDER BY name COLLATE NOCASE LIMIT ?`,
    [like, like, limit],
  );
  for (const w of whims) out.push({ type: "whim", id: w.id, label: w.name });

  const rec = await db.select<{ id: number; name: string }>(
    `SELECT id,name FROM recurring_items WHERE name LIKE ? ESCAPE '\\' ORDER BY name COLLATE NOCASE LIMIT ?`,
    [like, limit],
  );
  for (const r of rec) out.push({ type: "recurring", id: r.id, label: r.name });

  const goals = await db.select<{ id: number; name: string }>(
    `SELECT id,name FROM goals WHERE name LIKE ? ESCAPE '\\' ORDER BY name COLLATE NOCASE LIMIT ?`,
    [like, limit],
  );
  for (const g of goals) out.push({ type: "goal", id: g.id, label: g.name });

  return out;
}

export const SEARCH_ROUTES: Record<SearchType, string> = {
  movement: "/movements",
  source: "/sources",
  tag: "/tags",
  whim: "/whims",
  recurring: "/recurring",
  goal: "/goals",
};
