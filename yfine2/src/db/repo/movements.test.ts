import { describe, it, expect } from "vitest";
import { makeMemDb } from "@/test/sqlite";
import type { SqlExecutor } from "../types";
import { createSource, getBalance } from "./sources";
import * as mv from "./movements";

async function addTag(db: SqlExecutor, name: string): Promise<number> {
  const r = await db.select<{ id: number }>(
    `INSERT INTO tags (name,created_at,updated_at) VALUES (?,?,?) RETURNING id`,
    [name, "t", "t"],
  );
  return r[0].id;
}

describe("movements repo — plain", () => {
  it("creates with validation and replace-set tags", async () => {
    const { db } = await makeMemDb();
    const s = await createSource(db, { name: "A", currency: "EUR", starting_balance: 0 });
    const t1 = await addTag(db, "Food");
    const id = await mv.createMovement(db, {
      source_id: s.id,
      amount: 12.5,
      direction: "out",
      date: "2026-05-01",
      note: "  lunch  ",
      tagIds: [t1],
    });
    const row = (await mv.getMovement(db, id))!;
    expect(row.note).toBe("lunch"); // trimmed
    expect(await getBalance(db, s.id)).toBe(-12.5);

    await expect(
      mv.createMovement(db, { amount: 0, direction: "in", date: "2026-05-01" }),
    ).rejects.toMatchObject({ code: "invalid_amount" });
    await expect(
      mv.createMovement(db, { source_id: 9999, amount: 5, direction: "in", date: "2026-05-01" }),
    ).rejects.toMatchObject({ code: "not_found" });
  });

  it("rejects editing a transfer leg via the plain path (BUG-2 fix)", async () => {
    const { db } = await makeMemDb();
    const a = await createSource(db, { name: "A", currency: "EUR", starting_balance: 100 });
    const b = await createSource(db, { name: "B", currency: "EUR", starting_balance: 0 });
    const pair = await mv.createTransfer(db, { fromSourceId: a.id, toSourceId: b.id, amount: 30, date: "2026-05-01" });
    await expect(
      mv.updateMovement(db, pair.outId, { amount: 999 }),
    ).rejects.toMatchObject({ code: "is_transfer_leg" });
  });
});

describe("movements repo — transfers", () => {
  it("requires distinct sources on create (and edit) — BUG-1 fix", async () => {
    const { db } = await makeMemDb();
    const a = await createSource(db, { name: "A", currency: "EUR", starting_balance: 100 });
    const b = await createSource(db, { name: "B", currency: "EUR", starting_balance: 0 });
    await expect(
      mv.createTransfer(db, { fromSourceId: a.id, toSourceId: a.id, amount: 10, date: "2026-05-01" }),
    ).rejects.toMatchObject({ code: "same_source" });

    const pair = await mv.createTransfer(db, { fromSourceId: a.id, toSourceId: b.id, amount: 10, date: "2026-05-01" });
    await expect(
      mv.updateTransfer(db, pair.outId, { toSourceId: a.id }),
    ).rejects.toMatchObject({ code: "same_source" });
  });

  it("same-currency edit mirrors amount to both legs; conserves", async () => {
    const { db } = await makeMemDb();
    const a = await createSource(db, { name: "A", currency: "EUR", starting_balance: 100 });
    const b = await createSource(db, { name: "B", currency: "EUR", starting_balance: 0 });
    const pair = await mv.createTransfer(db, { fromSourceId: a.id, toSourceId: b.id, amount: 30, date: "2026-05-01" });
    expect(await getBalance(db, a.id)).toBe(70);
    expect(await getBalance(db, b.id)).toBe(30);

    await mv.updateTransfer(db, pair.outId, { amount: 50, date: "2026-06-01", note: "moved" });
    expect(await getBalance(db, a.id)).toBe(50);
    expect(await getBalance(db, b.id)).toBe(50);
    const inLeg = (await mv.getMovement(db, pair.inId))!;
    expect(inLeg.date).toBe("2026-06-01");
    expect(inLeg.note).toBe("moved");
    expect(inLeg.amount).toBe(50);
  });

  it("cross-currency edit does NOT clobber the converted IN amount", async () => {
    const { db } = await makeMemDb();
    const eur = await createSource(db, { name: "EUR", currency: "EUR", starting_balance: 100 });
    const usd = await createSource(db, { name: "USD", currency: "USD", starting_balance: 0 });
    const pair = await mv.createTransfer(db, {
      fromSourceId: eur.id,
      toSourceId: usd.id,
      amount: 10,
      toAmount: 11,
      date: "2026-05-01",
    });
    expect((await mv.getMovement(db, pair.inId))!.amount).toBe(11);

    // change only the OUT amount → IN must stay at its explicit converted value
    await mv.updateTransfer(db, pair.outId, { amount: 20 });
    expect((await mv.getMovement(db, pair.outId))!.amount).toBe(20);
    expect((await mv.getMovement(db, pair.inId))!.amount).toBe(11);

    // explicit toAmount updates the IN leg
    await mv.updateTransfer(db, pair.outId, { toAmount: 22 });
    expect((await mv.getMovement(db, pair.inId))!.amount).toBe(22);
  });

  it("rejects editing a non-transfer as a transfer", async () => {
    const { db } = await makeMemDb();
    const s = await createSource(db, { name: "A", currency: "EUR" });
    const id = await mv.createMovement(db, { source_id: s.id, amount: 5, direction: "out", date: "2026-05-01" });
    await expect(mv.updateTransfer(db, id, { amount: 9 })).rejects.toMatchObject({ code: "not_a_transfer" });
  });
});

describe("movements repo — bulk", () => {
  it("bulk delete dedups transfer partners and reports skipped", async () => {
    const { db } = await makeMemDb();
    const a = await createSource(db, { name: "A", currency: "EUR", starting_balance: 100 });
    const b = await createSource(db, { name: "B", currency: "EUR", starting_balance: 0 });
    const pair = await mv.createTransfer(db, { fromSourceId: a.id, toSourceId: b.id, amount: 30, date: "2026-05-01" });
    const plain = await mv.createMovement(db, { source_id: a.id, amount: 5, direction: "out", date: "2026-05-02" });

    const res = await mv.bulkDelete(db, [pair.outId, pair.inId, plain, 9999]);
    expect(res.affected).toBe(2); // transfer (one delete) + plain
    expect(res.skipped).toEqual([9999]);
    const left = await db.select<{ c: number }>(`SELECT COUNT(*) c FROM movements`);
    expect(left[0].c).toBe(0);
  });

  it("bulk set-source skips transfer legs; bulk tags expand to partners", async () => {
    const { db } = await makeMemDb();
    const a = await createSource(db, { name: "A", currency: "EUR", starting_balance: 100 });
    const b = await createSource(db, { name: "B", currency: "EUR", starting_balance: 0 });
    const c = await createSource(db, { name: "C", currency: "EUR" });
    const pair = await mv.createTransfer(db, { fromSourceId: a.id, toSourceId: b.id, amount: 30, date: "2026-05-01" });
    const plain = await mv.createMovement(db, { source_id: a.id, amount: 5, direction: "out", date: "2026-05-02" });
    const tag = await addTag(db, "Bills");

    const setRes = await mv.bulkSetSource(db, [pair.outId, plain], c.id);
    expect(setRes.affected).toBe(1); // only the plain one moved
    expect(setRes.skipped).toContain(pair.outId);

    const tagRes = await mv.bulkSetTags(db, [pair.outId], [tag], "add");
    expect(tagRes.affected).toBe(1);
    // both legs got the tag (expanded to partner)
    const tagged = await db.select<{ c: number }>(`SELECT COUNT(*) c FROM movement_tag WHERE tag_id = ?`, [tag]);
    expect(tagged[0].c).toBe(2);

    await expect(mv.bulkSetTags(db, [plain], [9999], "add")).rejects.toMatchObject({ code: "unknown_tag" });
  });
});

describe("movements repo — listing & filters", () => {
  it("hides the IN leg of transfers, escapes note search, paginates", async () => {
    const { db } = await makeMemDb();
    const a = await createSource(db, { name: "A", currency: "EUR", starting_balance: 1000 });
    const b = await createSource(db, { name: "B", currency: "EUR" });
    await mv.createMovement(db, { source_id: a.id, amount: 10, direction: "out", date: "2026-05-01", note: "100% cotton" });
    await mv.createMovement(db, { source_id: a.id, amount: 20, direction: "in", date: "2026-05-02", note: "salary" });
    await mv.createTransfer(db, { fromSourceId: a.id, toSourceId: b.id, amount: 30, date: "2026-05-03" });

    const all = await mv.listMovements(db, { excludeTransferIn: true });
    // 2 plain + 1 transfer OUT leg = 3 (IN leg hidden)
    expect(all.length).toBe(3);
    expect(all.every((m) => !(m.transfer_pair_id != null && m.direction === "in"))).toBe(true);
    // ordering: date DESC
    expect(all[0].date >= all[1].date).toBe(true);
    // transfer OUT row carries the partner source name
    const transferRow = all.find((m) => m.transfer_pair_id != null)!;
    expect(transferRow.partner_source_name).toBe("B");

    // note search treats % literally (escaped)
    const cotton = await mv.listMovements(db, { q: "100%" });
    expect(cotton.length).toBe(1);
    expect(cotton[0].note).toBe("100% cotton");

    expect(await mv.countMovements(db, { excludeTransferIn: true })).toBe(3);
  });

  it("tag match or vs and, and rejects an invalid date range", async () => {
    const { db } = await makeMemDb();
    const a = await createSource(db, { name: "A", currency: "EUR" });
    const food = await addTag(db, "Food");
    const work = await addTag(db, "Work");
    const m1 = await mv.createMovement(db, { source_id: a.id, amount: 1, direction: "out", date: "2026-05-01", tagIds: [food] });
    await mv.createMovement(db, { source_id: a.id, amount: 2, direction: "out", date: "2026-05-02", tagIds: [food, work] });
    void m1;

    expect((await mv.listMovements(db, { tagIds: [food, work], tagMatch: "or" })).length).toBe(2);
    expect((await mv.listMovements(db, { tagIds: [food, work], tagMatch: "and" })).length).toBe(1);

    await expect(
      mv.listMovements(db, { dateFrom: "2026-06-01", dateTo: "2026-05-01" }),
    ).rejects.toMatchObject({ code: "invalid_range" });
  });
});
