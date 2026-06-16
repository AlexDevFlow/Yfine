/**
 * Boot/periodic reconciliation: apply due recurring items and accrue source
 * yields. Mirrors the legacy startup-sync + hourly scheduler run, made idempotent
 * by last_fired_date (recurring) and yield_last_date (yield). Each unit is
 * isolated so one failure can't abort the rest.
 */
import type { SqlExecutor } from "../types";
import type { SourceRow } from "../schema-types";
import { accrueSource } from "@/domain/yield";
import { getBalance } from "./sources";
import { createNotification } from "./notifications";
import { processDueRecurring } from "./recurring";

const now = () => new Date().toISOString();

export async function processSourceYields(db: SqlExecutor, today: string): Promise<number> {
  const sources = await db.select<SourceRow>(
    `SELECT * FROM sources WHERE yield_rate > 0 AND yield_next_date IS NOT NULL`,
  );
  let credited = 0;
  for (const s of sources) {
    try {
      const res = await accrueSource(
        s,
        {
          getBalance: (id) => getBalance(db, id),
          postInterest: async (id, amount, date, note) => {
            const ts = now();
            await db.execute(
              `INSERT INTO movements (source_id,amount,direction,date,note,transfer_pair_id,exclude_from_stats,is_savings_contribution,created_at,updated_at)
               VALUES (?,?,?,?,?,NULL,0,0,?,?)`,
              [id, amount, "in", date, note, ts, ts],
            );
            await createNotification(db, {
              type: "info",
              title: `Interest: ${s.name}`,
              body: `+${amount} ${s.currency}`,
              related_entity: `source:${id}`,
            });
          },
        },
        today,
        (rate, period) => `Interest ${rate}% · ${period}m`,
      );
      credited += res.created;
      await db.execute(
        `UPDATE sources SET yield_last_date = ?, yield_next_date = ?, updated_at = ? WHERE id = ?`,
        [res.yield_last_date, res.yield_next_date, now(), s.id],
      );
    } catch {
      /* isolate per-source failures */
    }
  }
  return credited;
}

export async function runScheduler(
  db: SqlExecutor,
  today: string,
): Promise<{ applied: number; errors: number; credited: number }> {
  const rec = await processDueRecurring(db, today);
  const credited = await processSourceYields(db, today);
  return { ...rec, credited };
}
