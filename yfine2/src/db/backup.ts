/**
 * Backup / restore. Reproduces the legacy formats so existing backups stay
 * importable (refactor-analysis/exports-data.md §3):
 *  - JSON: { "<table>": [rows...], "_export_mode": "all", "_plugin_tables": {...} }
 *  - .yfine: a ZIP with manifest.json (format marker) + data.json (+ attachments later)
 * Import is all-or-nothing inside one transaction with PRAGMA defer_foreign_keys=ON
 * (needed for the self-referential movements.transfer_pair_id cycle).
 */
import { unzipSync, zipSync, strToU8, strFromU8 } from "fflate";
import type { SqlExecutor } from "./types";

// Parents-first insert order; delete is the reverse (children-first).
const CORE_TABLES = [
  "sources", "tags", "exchange_rates", "movements", "movement_tag",
  "movement_attachments", "recurring_items", "notifications", "settings",
  "whims", "budgets", "portfolios", "holdings", "holding_price_snapshots",
  "goals", "goal_allocations", "savings", "saving_tag",
];

type Row = Record<string, unknown>;
export interface BackupData {
  _export_mode: "all";
  _plugin_tables?: Record<string, Row[]>;
  [table: string]: unknown;
}

async function tableColumns(db: SqlExecutor, table: string): Promise<Set<string>> {
  const info = await db.select<{ name: string }>(`PRAGMA table_info(${table})`);
  return new Set(info.map((r) => r.name));
}

async function allTableNames(db: SqlExecutor): Promise<string[]> {
  const rows = await db.select<{ name: string }>(
    `SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'`,
  );
  return rows.map((r) => r.name);
}

export async function exportAll(db: SqlExecutor): Promise<BackupData> {
  const out: BackupData = { _export_mode: "all" };
  for (const t of CORE_TABLES) {
    out[t] = await db.select<Row>(`SELECT * FROM ${t}`);
  }
  // plugin / unknown tables (everything not core, not alembic_version)
  const known = new Set([...CORE_TABLES, "alembic_version"]);
  const extra = (await allTableNames(db)).filter((t) => !known.has(t));
  if (extra.length) {
    const plugins: Record<string, Row[]> = {};
    for (const t of extra) plugins[t] = await db.select<Row>(`SELECT * FROM ${t}`);
    out._plugin_tables = plugins;
  }
  return out;
}

function normalizeVal(v: unknown): unknown {
  if (typeof v === "boolean") return v ? 1 : 0;
  if (v === undefined) return null;
  return v;
}

async function clearAndInsert(db: SqlExecutor, table: string, rows: Row[]): Promise<void> {
  await db.execute(`DELETE FROM ${table}`);
  if (!rows.length) return;
  const cols = await tableColumns(db, table);
  for (const row of rows) {
    const keys = Object.keys(row).filter((k) => cols.has(k));
    if (!keys.length) continue;
    const ph = keys.map(() => "?").join(",");
    await db.execute(
      `INSERT INTO ${table} (${keys.join(",")}) VALUES (${ph})`,
      keys.map((k) => normalizeVal(row[k])),
    );
  }
}

/**
 * Insert movements with transfer_pair_id deferred to a second pass, so the
 * self-referential transfer cycle never trips an FK error during insert — no
 * reliance on `defer_foreign_keys` (which is per-connection and unreliable on a
 * pooled backend). Both legs exist before any transfer_pair_id is set.
 */
async function insertMovementsDeferred(db: SqlExecutor, rows: Row[]): Promise<void> {
  if (!rows.length) return;
  const cols = await tableColumns(db, "movements");
  const links: { id: unknown; pair: unknown }[] = [];
  for (const row of rows) {
    const keys = Object.keys(row).filter((k) => cols.has(k));
    if (!keys.length) continue;
    const ph = keys.map(() => "?").join(",");
    const vals = keys.map((k) => (k === "transfer_pair_id" ? null : normalizeVal(row[k])));
    await db.execute(`INSERT INTO movements (${keys.join(",")}) VALUES (${ph})`, vals);
    if (row.transfer_pair_id != null && row.id != null) links.push({ id: row.id, pair: row.transfer_pair_id });
  }
  for (const l of links) {
    await db.execute(`UPDATE movements SET transfer_pair_id = ? WHERE id = ?`, [l.pair, l.id]);
  }
}

async function applyImport(db: SqlExecutor, data: BackupData): Promise<void> {
  for (const t of [...CORE_TABLES].reverse()) await db.execute(`DELETE FROM ${t}`); // children-first
  for (const t of CORE_TABLES) {
    const rows = (data[t] as Row[] | undefined) ?? [];
    if (t === "movements") await insertMovementsDeferred(db, rows);
    else await clearAndInsert(db, t, rows);
  }
  if (data._plugin_tables) {
    const existing = new Set(await allTableNames(db));
    for (const [t, rows] of Object.entries(data._plugin_tables)) {
      if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(t) || !existing.has(t)) continue;
      await clearAndInsert(db, t, rows);
    }
  }
}

/**
 * All-or-nothing restore. Wraps the wipe+reload in a transaction AND keeps a
 * pre-import snapshot: if anything fails, the snapshot is reloaded so a failed
 * restore can't leave the database half-wiped (defends against backends where a
 * transaction may not roll back cleanly, e.g. a pooled connection).
 */
export async function importAll(db: SqlExecutor, data: BackupData): Promise<void> {
  const snapshot = await exportAll(db);
  await db.execute("BEGIN");
  try {
    await applyImport(db, data);
    await db.execute("COMMIT");
  } catch (e) {
    try {
      await db.execute("ROLLBACK");
    } catch {
      /* ignore */
    }
    // Best-effort recovery to the pre-import state.
    try {
      await db.execute("BEGIN");
      await applyImport(db, snapshot);
      await db.execute("COMMIT");
    } catch {
      try {
        await db.execute("ROLLBACK");
      } catch {
        /* ignore */
      }
    }
    throw e;
  }
}

// ---- .yfine archive ----

export interface ArchiveManifest {
  format: "yfine-archive";
  version: number;
  created_at: string;
  plugins: { id: string; name: string; version: string }[];
}

export async function exportArchive(db: SqlExecutor, createdAt: string): Promise<Uint8Array> {
  const manifest: ArchiveManifest = { format: "yfine-archive", version: 1, created_at: createdAt, plugins: [] };
  const data = await exportAll(db);
  return zipSync({
    "manifest.json": strToU8(JSON.stringify(manifest, null, 2)),
    "data.json": strToU8(JSON.stringify(data, null, 2)),
  });
}

export async function exportJson(db: SqlExecutor): Promise<string> {
  return JSON.stringify(await exportAll(db), null, 2);
}

function isZip(bytes: Uint8Array): boolean {
  return bytes.length >= 4 && bytes[0] === 0x50 && bytes[1] === 0x4b && bytes[2] === 0x03 && bytes[3] === 0x04;
}

/** Import either a .yfine ZIP or a legacy JSON backup (detected by content). */
export async function importFile(db: SqlExecutor, bytes: Uint8Array): Promise<void> {
  if (isZip(bytes)) {
    const files = unzipSync(bytes);
    const manifestRaw = files["manifest.json"];
    if (!manifestRaw) throw new Error("not a yfine archive (no manifest.json)");
    const manifest = JSON.parse(strFromU8(manifestRaw)) as Partial<ArchiveManifest>;
    if (manifest.format !== "yfine-archive") throw new Error("not a yfine archive (bad format marker)");
    const dataRaw = files["data.json"];
    if (!dataRaw) throw new Error("archive missing data.json");
    await importAll(db, JSON.parse(strFromU8(dataRaw)) as BackupData);
    return;
  }
  // legacy JSON
  const data = JSON.parse(strFromU8(bytes)) as BackupData;
  await importAll(db, data);
}

/** Plain-CSV export of movements (lowest-common-denominator, a gap the old app lacked). */
export async function exportMovementsCsv(db: SqlExecutor): Promise<string> {
  const rows = await db.select<{ date: string; amount: number; direction: string; note: string | null; source_name: string | null; currency: string | null }>(
    `SELECT m.date, m.amount, m.direction, m.note, s.name AS source_name, s.currency
     FROM movements m LEFT JOIN sources s ON m.source_id = s.id
     WHERE m.transfer_pair_id IS NULL ORDER BY m.date DESC, m.id DESC`,
  );
  const esc = (v: unknown) => {
    const s = v == null ? "" : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const header = "date,amount,direction,note,account,currency";
  const lines = rows.map((r) => [r.date, r.amount, r.direction, r.note, r.source_name, r.currency].map(esc).join(","));
  return [header, ...lines].join("\n");
}
