/**
 * CSV bank-statement import. Faithful port of services/importers/csv_parser.py +
 * presets + dedupe + preview/commit (refactor-analysis/imports.md §2). Fixes:
 *  - B1: dedupe is re-run against the FINAL target source at commit (preview-time
 *        flags can't silently let duplicates through).
 *  - B2: a currency-mismatch between the file and the target source is surfaced.
 * (OFX/QFX/XLSX parsers are deferred — CSV is the common path.)
 */
import type { SqlExecutor } from "../types";
import { round2 } from "@/domain/money";
import { createMovement } from "../repo/movements";
import { createSource, getSource } from "../repo/sources";

import ynab from "./presets/ynab.json";
import paypal from "./presets/paypal.json";
import revolut from "./presets/revolut.json";
import n26 from "./presets/n26.json";
import firefly from "./presets/firefly_iii.json";

export interface Preset {
  id: string;
  display_name: string;
  format: string;
  currency_hint?: string | null;
  source_hint?: string | null;
  detect?: { headers?: string[]; contains?: string[] };
  options?: CsvOptions;
}
export const PRESETS = [ynab, paypal, revolut, n26, firefly] as unknown as Preset[];

export interface CsvOptions {
  encoding?: string;
  delimiter?: string;
  date_format?: string;
  decimal_separator?: string;
  column_map?: Record<string, string>;
  skip_rows?: number;
  sign_convention?: string;
}

export interface ParsedMovement {
  date: string; // ISO YYYY-MM-DD
  amount: number; // positive
  direction: "in" | "out";
  note: string | null;
  currency: string | null;
}

export interface ParseResult {
  movements: ParsedMovement[];
  detectedCurrency: string | null;
  warnings: string[];
  headers: string[];
  needsMapping: boolean;
}

const SYNONYMS: Record<string, string[]> = {
  date: ["date", "data", "datum", "fecha", "transaction date", "posted date", "started date", "completed date", "data valuta", "data operazione", "data contabile", "booking date", "value date", "дата"],
  amount: ["amount", "importo", "betrag", "valor", "monto", "total", "montant"],
  amount_in: ["credit", "credito", "entrata", "entrate", "income", "in", "eingang", "haber", "accrediti", "inflow", "deposit"],
  amount_out: ["debit", "debito", "uscita", "uscite", "expense", "out", "ausgang", "soll", "addebiti", "outflow", "withdrawal"],
  note: ["note", "description", "descrizione", "memo", "detail", "details", "payee", "merchant", "name", "narration", "reference", "concepto", "causale", "descripcion"],
  currency: ["currency", "valuta", "ccy", "moneda", "waehrung", "wahrung", "devise"],
  direction: ["direction", "type", "tipo", "dir"],
};

function normalizeHeader(h: string): string {
  return (h || "").trim().toLowerCase().replace(/_/g, " ").replace(/-/g, " ");
}

export function guessColumnMap(headers: string[]): Record<string, string> | null {
  const normalized = new Map<string, string>();
  for (const h of headers) if (h) normalized.set(normalizeHeader(h), h);
  const result: Record<string, string> = {};
  for (const [field, syns] of Object.entries(SYNONYMS)) {
    for (const syn of syns) {
      if (normalized.has(syn)) {
        result[field] = normalized.get(syn)!;
        break;
      }
    }
  }
  const hasAmount = "amount" in result || ("amount_in" in result && "amount_out" in result);
  return "date" in result && hasAmount ? result : null;
}

export function parseAmount(input: string, decimalSep = "."): number | null {
  if (input == null) return null;
  let s = String(input).trim();
  if (!s) return null;
  s = s.replace(/ /g, "").replace(/ /g, "");
  for (const sym of ["€", "$", "£", "¥", "CHF", "USD", "EUR", "GBP"]) s = s.split(sym).join("");
  if (decimalSep === ",") {
    s = s.replace(/\./g, "").replace(/,/g, ".");
  } else {
    const hasComma = s.includes(",");
    const hasDot = s.includes(".");
    if (hasComma && hasDot) s = s.replace(/,/g, "");
    else if (hasComma && !hasDot) s = s.replace(/,/g, ".");
  }
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}

/** Minimal Python-strptime subset for the codes used by presets (%Y %m %d %H %M %S). */
function strptime(s: string, fmt: string): string | null {
  const tokens: string[] = [];
  let regex = "";
  for (let i = 0; i < fmt.length; i++) {
    if (fmt[i] === "%" && i + 1 < fmt.length) {
      const code = fmt[++i];
      if (code === "Y") { regex += "(\\d{4})"; tokens.push("Y"); }
      else if ("mdHMS".includes(code)) { regex += "(\\d{1,2})"; tokens.push(code); }
      else regex += code.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    } else {
      regex += fmt[i].replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    }
  }
  const m = new RegExp("^" + regex + "$").exec(s.trim());
  if (!m) return null;
  const part: Record<string, number> = {};
  tokens.forEach((tk, idx) => (part[tk] = Number(m[idx + 1])));
  const y = part.Y, mo = part.m, d = part.d;
  if (!y || !mo || !d || mo < 1 || mo > 12 || d < 1 || d > 31) return null;
  return `${y}-${String(mo).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
}

const FALLBACK_FORMATS = ["%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%m/%d/%Y", "%m-%d-%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"];

export function tryParseDate(input: string, dateFormat?: string): string | null {
  const s = (input || "").trim();
  if (!s) return null;
  if (dateFormat) {
    const r = strptime(s, dateFormat);
    if (r) return r;
  }
  for (const fmt of FALLBACK_FORMATS) {
    const r = strptime(s, fmt);
    if (r) return r;
  }
  // day-first loose fallback: d?/m?/y or with - .
  const parts = s.split(/[/.\-]/).map((p) => p.trim());
  if (parts.length >= 3) {
    let [a, b, c] = parts;
    if (c.length === 4) {
      const day = Number(a), mon = Number(b), yr = Number(c);
      if (day >= 1 && day <= 31 && mon >= 1 && mon <= 12) return `${yr}-${String(mon).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
    }
    void c;
  }
  return null;
}

function detectDelimiter(line: string): string {
  const cands = [",", ";", "\t", "|"];
  let best = ",";
  let bestN = -1;
  for (const c of cands) {
    const n = line.split(c).length - 1;
    if (n > bestN) { bestN = n; best = c; }
  }
  return best;
}

/** RFC-4180-ish CSV row reader with quotes. */
function parseRows(text: string, delimiter: string): string[][] {
  const rows: string[][] = [];
  let field = "";
  let row: string[] = [];
  let inQuotes = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (inQuotes) {
      if (ch === '"') {
        if (text[i + 1] === '"') { field += '"'; i++; }
        else inQuotes = false;
      } else field += ch;
    } else if (ch === '"') inQuotes = true;
    else if (ch === delimiter) { row.push(field); field = ""; }
    else if (ch === "\n") { row.push(field); rows.push(row); row = []; field = ""; }
    else if (ch === "\r") { /* skip */ }
    else field += ch;
  }
  if (field.length > 0 || row.length > 0) { row.push(field); rows.push(row); }
  return rows;
}

function prep(text: string, options: CsvOptions): { headers: string[]; dataRows: string[][]; delimiter: string } {
  let t = text;
  if (t.startsWith("﻿")) t = t.slice(1);
  let lines = t.split(/\r?\n/);
  const skip = Number(options.skip_rows ?? 0) || 0;
  if (skip) lines = lines.slice(skip);
  t = lines.join("\n");
  const firstLine = lines[0] ?? "";
  const delimiter = options.delimiter || detectDelimiter(firstLine);
  const rows = parseRows(t, delimiter);
  const headers = rows[0] ?? [];
  return { headers, dataRows: rows.slice(1), delimiter };
}

/** Headers for preset detection — respects skip_rows + delimiter (B5 fix). */
export function extractHeaders(text: string, options: CsvOptions = {}): string[] {
  return prep(text, options).headers;
}

export function parseCsv(text: string, options: CsvOptions = {}): ParseResult {
  const { headers, dataRows } = prep(text, options);
  if (headers.length === 0) return { movements: [], detectedCurrency: null, warnings: ["empty_file"], headers: [], needsMapping: false };

  const decimalSep = options.decimal_separator ?? ".";
  let columnMap = options.column_map ?? guessColumnMap(headers) ?? undefined;
  if (!columnMap) {
    return { movements: [], detectedCurrency: null, warnings: [`needs_mapping:${headers.join(",")}`], headers, needsMapping: true };
  }

  const headerIndex: Record<string, number> = {};
  for (const [field, name] of Object.entries(columnMap)) {
    const idx = headers.indexOf(name);
    if (idx === -1) return { movements: [], detectedCurrency: null, warnings: [`column_not_found:${name}`], headers, needsMapping: false };
    headerIndex[field] = idx;
  }

  const movements: ParsedMovement[] = [];
  const warnings: string[] = [];
  let detectedCurrency: string | null = null;

  dataRows.forEach((row, i) => {
    const rowNum = i + 2;
    if (!row.length || row.every((c) => (c || "").trim() === "")) return;

    const dRaw = headerIndex.date != null && headerIndex.date < row.length ? row[headerIndex.date] : "";
    const date = tryParseDate(dRaw, options.date_format);
    if (!date) { warnings.push(`row_${rowNum}_bad_date`); return; }

    let amount: number | null = null;
    let direction: "in" | "out" | null = null;

    if (headerIndex.amount_in != null && headerIndex.amount_out != null) {
      const inVal = parseAmount(row[headerIndex.amount_in] ?? "", decimalSep);
      const outVal = parseAmount(row[headerIndex.amount_out] ?? "", decimalSep);
      if (inVal && inVal > 0) { amount = inVal; direction = "in"; }
      else if (outVal && outVal > 0) { amount = outVal; direction = "out"; }
    } else {
      const a = parseAmount(headerIndex.amount != null ? row[headerIndex.amount] ?? "" : "", decimalSep);
      if (a == null) { warnings.push(`row_${rowNum}_bad_amount`); return; }
      if (options.sign_convention === "positive_with_type" && headerIndex.direction != null) {
        const dir = (row[headerIndex.direction] || "").trim().toLowerCase();
        if (["in", "credit", "income", "entrata", "credito"].includes(dir)) direction = "in";
        else if (["out", "debit", "expense", "uscita", "debito"].includes(dir)) direction = "out";
        else direction = a >= 0 ? "in" : "out";
        amount = Math.abs(a);
      } else {
        direction = a >= 0 ? "in" : "out";
        amount = Math.abs(a);
      }
    }

    // round FIRST so sub-cent rows (|amount| < 0.005) that round to 0 are skipped,
    // not emitted as amount:0 (which would later be rejected mid-commit).
    const rounded = amount == null ? null : round2(amount);
    if (rounded == null || rounded === 0 || (direction !== "in" && direction !== "out")) {
      warnings.push(`row_${rowNum}_zero_or_invalid`);
      return;
    }

    let note: string | null = null;
    if (headerIndex.note != null && headerIndex.note < row.length) note = (row[headerIndex.note] || "").trim() || null;

    let currency: string | null = null;
    if (headerIndex.currency != null && headerIndex.currency < row.length) {
      currency = (row[headerIndex.currency] || "").trim().toUpperCase() || null;
      if (currency && !detectedCurrency) detectedCurrency = currency;
    }

    movements.push({ date, amount: rounded, direction, note, currency });
  });

  return { movements, detectedCurrency, warnings, headers, needsMapping: false };
}

export function detectPreset(text: string, headers: string[]): Preset | null {
  const lowerHeaders = headers.map((h) => h.trim().toLowerCase());
  const head = text.slice(0, 4096).toLowerCase();
  for (const p of PRESETS) {
    if (p.format !== "csv") continue;
    const reqHeaders = p.detect?.headers ?? [];
    const reqContains = p.detect?.contains ?? [];
    const headersOk = reqHeaders.every((h) => lowerHeaders.includes(h.toLowerCase()));
    const containsOk = reqContains.every((c) => head.includes(c.toLowerCase()));
    if (headersOk && containsOk && (reqHeaders.length || reqContains.length)) return p;
  }
  return null;
}

// ---- dedupe ----
function rowKey(sourceId: number, m: ParsedMovement): string {
  const note = (m.note || "").trim().toLowerCase();
  return `${sourceId}|${m.date}|${m.amount.toFixed(2)}|${m.direction}|${note}`;
}

export async function markDuplicates(db: SqlExecutor, sourceId: number | null, movements: ParsedMovement[]): Promise<boolean[]> {
  if (sourceId == null || movements.length === 0) return movements.map(() => false);
  const dates = movements.map((m) => m.date).sort();
  const existing = await db.select<{ date: string; amount: number; direction: "in" | "out"; note: string | null }>(
    `SELECT date, amount, direction, note FROM movements WHERE source_id = ? AND date >= ? AND date <= ?`,
    [sourceId, dates[0], dates[dates.length - 1]],
  );
  const seen = new Set(existing.map((e) => rowKey(sourceId, { date: e.date, amount: e.amount, direction: e.direction, note: e.note, currency: null })));
  return movements.map((m) => {
    const k = rowKey(sourceId, m);
    if (seen.has(k)) return true;
    seen.add(k); // intra-batch dedupe
    return false;
  });
}

// ---- preview + commit ----
export interface PreviewResult {
  preset: Preset | null;
  headers: string[];
  needsMapping: boolean;
  detectedCurrency: string | null;
  warnings: string[];
  rows: (ParsedMovement & { index: number; isDuplicate: boolean })[];
  totalIn: number;
  totalOut: number;
  duplicateCount: number;
}

export async function previewCsv(
  db: SqlExecutor,
  text: string,
  opts: { presetId?: string; options?: CsvOptions; sourceId?: number | null } = {},
): Promise<PreviewResult> {
  const userOptions = opts.options ?? {};
  const headersForDetect = extractHeaders(text, userOptions);
  const preset = opts.presetId ? PRESETS.find((p) => p.id === opts.presetId) ?? null : detectPreset(text, headersForDetect);
  const effective: CsvOptions = { ...(preset?.options ?? {}), ...userOptions };
  const result = parseCsv(text, effective);
  const dupFlags = await markDuplicates(db, opts.sourceId ?? null, result.movements);
  let totalIn = 0;
  let totalOut = 0;
  const rows = result.movements.map((m, i) => {
    if (m.direction === "in") totalIn = round2(totalIn + m.amount);
    else totalOut = round2(totalOut + m.amount);
    return { ...m, index: i, isDuplicate: dupFlags[i] };
  });
  return {
    preset,
    headers: result.headers,
    needsMapping: result.needsMapping && result.movements.length === 0,
    detectedCurrency: result.detectedCurrency ?? preset?.currency_hint ?? null,
    warnings: result.warnings.filter((w) => !w.startsWith("needs_mapping:")),
    rows,
    totalIn,
    totalOut,
    duplicateCount: dupFlags.filter(Boolean).length,
  };
}

export interface CommitResult {
  imported: number;
  skipped: number;
  sourceId: number;
  currencyWarning?: string;
}

export async function commitCsv(
  db: SqlExecutor,
  input: {
    movements: ParsedMovement[];
    sourceId?: number;
    newSource?: { name: string; currency: string; starting_balance?: number };
    tagIds?: number[];
    excludeFromStats?: boolean;
  },
): Promise<CommitResult> {
  let sourceId = input.sourceId;
  if (input.newSource) {
    const s = await createSource(db, { name: input.newSource.name, currency: input.newSource.currency, starting_balance: input.newSource.starting_balance ?? 0 });
    sourceId = s.id;
  }
  if (sourceId == null) throw new Error("no target source");
  const source = await getSource(db, sourceId);
  if (!source) throw new Error("source not found");

  // B2: warn when file currency differs from the target source currency.
  let currencyWarning: string | undefined;
  const fileCcy = input.movements.find((m) => m.currency)?.currency;
  if (fileCcy && fileCcy.toUpperCase() !== source.currency.toUpperCase()) {
    currencyWarning = `File currency ${fileCcy} differs from account currency ${source.currency}; amounts imported as-is (no conversion).`;
  }

  // B1: re-dedupe against the FINAL target source at commit time.
  const dupFlags = await markDuplicates(db, sourceId, input.movements);
  let imported = 0;
  let skipped = 0;
  for (let i = 0; i < input.movements.length; i++) {
    if (dupFlags[i]) { skipped += 1; continue; }
    const m = input.movements[i];
    try {
      await createMovement(db, {
        source_id: sourceId,
        amount: m.amount,
        direction: m.direction,
        date: m.date,
        note: m.note,
        tagIds: input.tagIds,
        exclude_from_stats: input.excludeFromStats,
      });
      imported += 1;
    } catch {
      // a single bad row must not abort the batch and lose the rows after it
      skipped += 1;
    }
  }
  return { imported, skipped, sourceId, currencyWarning };
}
