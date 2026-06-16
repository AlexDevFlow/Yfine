/**
 * Row shapes for the core tables, matching the on-disk SQLite columns exactly
 * (snake_case). Booleans are stored as 0/1 integers; dates/datetimes as text.
 */

export interface SourceRow {
  id: number;
  name: string;
  currency: string;
  starting_balance: number;
  exclude_from_stats: number; // 0|1
  is_savings_fund: number; // 0|1
  hidden_from_sources: number; // 0|1
  yield_rate: number;
  yield_period_months: number;
  yield_next_date: string | null;
  yield_last_date: string | null;
  created_at: string;
  updated_at: string;
}

export interface MovementRow {
  id: number;
  source_id: number | null;
  amount: number;
  direction: "in" | "out";
  date: string;
  note: string | null;
  transfer_pair_id: number | null;
  exclude_from_stats: number;
  is_savings_contribution: number;
  created_at: string;
  updated_at: string;
}

export interface TagRow {
  id: number;
  name: string;
  color: string | null;
  created_at: string;
  updated_at: string;
}

export interface SavingRow {
  id: number;
  amount: number;
  currency: string;
  date: string;
  description: string | null;
  note: string | null;
  created_at: string;
  updated_at: string;
}
