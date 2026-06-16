/**
 * Domain-level rejections (the rules the legacy app enforced as HTTP 409/422).
 * The UI maps `code` to a localized message; throwing keeps repos pure of i18n.
 */
export type DomainErrorCode =
  | "cross_currency"
  | "fund_not_mergeable"
  | "fund_save_rejected"
  | "not_a_fund"
  | "active_goal_blocks_delete"
  | "has_portfolios"
  | "currency_mismatch"
  | "not_found"
  | "invalid_amount"
  | "note_too_long"
  | "invalid_range"
  | "is_transfer_leg"
  | "not_a_transfer"
  | "same_source"
  | "unknown_tag"
  | "not_yet_due"
  | "recurring_ended"
  | "duplicate_budget"
  | "goal_not_active"
  | "alloc_from_own_source"
  | "goal_cancelled"
  | "use_close_or_delete"
  | "whim_already_purchased"
  | "not_pending"
  | "not_dismissed"
  | "tag_name_required"
  | "duplicate_tag"
  | "invalid_color";

export class DomainError extends Error {
  code: DomainErrorCode;
  constructor(code: DomainErrorCode, message?: string) {
    super(message ?? code);
    this.name = "DomainError";
    this.code = code;
  }
}
