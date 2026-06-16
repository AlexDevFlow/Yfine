/** Sample data for the browser preview (sql.js). Never runs in the packaged app. */
import type { SqlExecutor } from "./types";
import { createSource } from "./repo/sources";
import { createSaving } from "./repo/savings";
import { addMonthsISO, monthStart, todayISO } from "@/lib/date";

export async function seedPreview(db: SqlExecutor): Promise<void> {
  const today = todayISO();
  const ms = monthStart(today);
  const ts = today + "T00:00:00";

  await db.execute(
    `INSERT INTO tags (name,color,created_at,updated_at) VALUES
      ('Food','#f59e0b',?,?),('Salary','#10b981',?,?),
      ('Subscriptions','#6366f1',?,?),('Shopping','#ec4899',?,?)`,
    [ts, ts, ts, ts, ts, ts, ts, ts],
  );

  const checking = await createSource(db, { name: "Checking", currency: "EUR", starting_balance: 1800 });
  const cash = await createSource(db, { name: "Cash wallet", currency: "EUR", starting_balance: 120 });
  await createSource(db, { name: "USD account", currency: "USD", starting_balance: 540 });
  await createSource(db, {
    name: "Term deposit",
    currency: "EUR",
    starting_balance: 5000,
    yield_rate: 1.5,
    yield_period_months: 12,
  });

  const mv = async (
    sourceId: number | null,
    dir: "in" | "out",
    amount: number,
    date: string,
    note: string,
    tagId?: number,
  ) => {
    const rows = await db.select<{ id: number }>(
      `INSERT INTO movements (source_id,amount,direction,date,note,transfer_pair_id,exclude_from_stats,is_savings_contribution,created_at,updated_at)
       VALUES (?,?,?,?,?,NULL,0,0,?,?) RETURNING id`,
      [sourceId, amount, dir, date, note, ts, ts],
    );
    if (tagId) {
      await db.execute(`INSERT INTO movement_tag (movement_id,tag_id) VALUES (?,?)`, [rows[0].id, tagId]);
    }
  };

  // current month
  await mv(checking.id, "in", 2000, ms, "Salary", 2);
  await mv(checking.id, "out", 42.1, today, "Groceries", 1);
  await mv(checking.id, "out", 12.99, today, "Netflix", 3);
  await mv(cash.id, "out", 8.5, today, "Coffee", 1);
  await mv(checking.id, "out", 89.99, today, "New shoes", 4);
  await createSaving(db, { fromSourceId: checking.id, amount: 300, date: ms, note: "monthly save" });

  // a few prior months so the comparison chart has bars
  for (let i = 1; i <= 4; i++) {
    const m = addMonthsISO(ms, -i);
    await mv(checking.id, "in", 2000, m, "Salary", 2);
    await mv(checking.id, "out", 1300 + i * 30, m, "Living costs");
  }
}
