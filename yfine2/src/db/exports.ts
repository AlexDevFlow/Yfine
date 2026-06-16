/**
 * Spreadsheet / PDF exports with selectable sections (parity with the original
 * app's Excel + PDF export). Pure client-side via SheetJS and jsPDF.
 */
import * as XLSX from "xlsx";
import { jsPDF } from "jspdf";
import autoTable from "jspdf-autotable";
import type { SqlExecutor } from "./types";
import * as sources from "./repo/sources";
import * as movements from "./repo/movements";
import * as tags from "./repo/tags";
import * as recurring from "./repo/recurring";
import * as savings from "./repo/savings";
import * as whims from "./repo/whims";
import { todayISO } from "@/lib/date";

export type SectionKey = "sources" | "movements" | "tags" | "recurring" | "savings" | "whims";

export const EXPORT_SECTIONS: { key: SectionKey; label: string }[] = [
  { key: "sources", label: "Sources" },
  { key: "movements", label: "Movements" },
  { key: "tags", label: "Tags" },
  { key: "recurring", label: "Recurring" },
  { key: "savings", label: "Savings" },
  { key: "whims", label: "Whims" },
];

interface Section {
  title: string;
  columns: string[];
  rows: (string | number)[][];
}

async function buildSection(db: SqlExecutor, key: SectionKey): Promise<Section> {
  switch (key) {
    case "sources": {
      const [list, balances] = await Promise.all([
        sources.listSources(db, { includeHidden: true }),
        sources.getBalancesBatch(db),
      ]);
      return {
        title: "Sources",
        columns: ["Name", "Currency", "Balance", "Starting", "Yield %", "Fund"],
        rows: list.map((s) => [s.name, s.currency, balances.get(s.id) ?? s.starting_balance, s.starting_balance, s.yield_rate, s.is_savings_fund ? "yes" : ""]),
      };
    }
    case "movements": {
      const items = await movements.listMovements(db, {}, { limit: 100000 });
      return {
        title: "Movements",
        columns: ["Date", "Direction", "Amount", "Currency", "Account", "Note", "Tags"],
        rows: items.map((m) => [m.date, m.direction, m.amount, m.source_currency ?? "", m.source_name ?? "", m.note ?? "", m.tags.map((t) => t.name).join(", ")]),
      };
    }
    case "tags": {
      const list = await tags.listTagsWithUsage(db);
      return {
        title: "Tags",
        columns: ["Name", "Color", "Movements", "Budgets"],
        rows: list.map((t) => [t.name, t.color ?? "", t.movement_count, t.budget_count]),
      };
    }
    case "recurring": {
      const list = await recurring.listRecurring(db, todayISO());
      return {
        title: "Recurring",
        columns: ["Name", "Direction", "Amount", "Currency", "Frequency", "Next due"],
        rows: list.map((r) => [r.name, r.direction, r.amount, r.currency, r.frequency, r.next_due_date]),
      };
    }
    case "savings": {
      const list = await savings.listSavings(db, { limit: 100000 });
      return {
        title: "Savings",
        columns: ["Date", "Amount", "Currency", "From", "Note", "Tags"],
        rows: list.map((s) => [s.date, s.amount, s.currency, s.from_source_name ?? "", s.note ?? "", s.tags.map((t) => t.name).join(", ")]),
      };
    }
    case "whims": {
      const list = await whims.listWhims(db);
      return {
        title: "Whims",
        columns: ["Name", "Amount", "Currency", "Priority", "Status"],
        rows: list.map((w) => [w.name, w.amount, w.currency, w.priority, w.status]),
      };
    }
  }
}

async function collect(db: SqlExecutor, selected: SectionKey[]): Promise<Section[]> {
  const out: Section[] = [];
  for (const k of selected) out.push(await buildSection(db, k));
  return out;
}

export async function exportExcel(db: SqlExecutor, selected: SectionKey[]): Promise<Uint8Array> {
  const sections = await collect(db, selected);
  const wb = XLSX.utils.book_new();
  for (const s of sections) {
    const ws = XLSX.utils.aoa_to_sheet([s.columns, ...s.rows]);
    XLSX.utils.book_append_sheet(wb, ws, s.title.slice(0, 31));
  }
  if (!wb.SheetNames.length) XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet([["No data"]]), "Empty");
  return new Uint8Array(XLSX.write(wb, { type: "array", bookType: "xlsx" }) as ArrayBuffer);
}

export async function exportPdf(db: SqlExecutor, selected: SectionKey[], title = "Yfine export"): Promise<Uint8Array> {
  const sections = await collect(db, selected);
  const doc = new jsPDF({ orientation: "landscape" });
  doc.setFontSize(14);
  doc.text(title, 14, 16);
  let y = 22;
  for (const s of sections) {
    doc.setFontSize(11);
    doc.text(s.title, 14, y);
    autoTable(doc, {
      head: [s.columns],
      body: s.rows.map((r) => r.map((c) => String(c))),
      startY: y + 2,
      styles: { fontSize: 8 },
      headStyles: { fillColor: [99, 102, 241] },
      margin: { left: 14, right: 14 },
    });
    // @ts-expect-error lastAutoTable is augmented on the doc at runtime by the plugin
    y = (doc.lastAutoTable?.finalY ?? y + 20) + 10;
    if (y > 190) { doc.addPage(); y = 16; }
  }
  return new Uint8Array(doc.output("arraybuffer"));
}
