import { useTranslation } from "react-i18next";
import { DomainError, type DomainErrorCode } from "@/db/errors";

const MESSAGES: Record<DomainErrorCode, string> = {
  cross_currency: "Both sources must share the same currency.",
  fund_not_mergeable: "Savings funds can't be merged.",
  fund_save_rejected: "You can't save from a savings fund.",
  not_a_fund: "That source isn't a savings fund.",
  active_goal_blocks_delete: "An active goal still uses this source.",
  has_portfolios: "This source has portfolios — move or delete them first.",
  currency_mismatch: "Currency doesn't match the source.",
  not_found: "Not found.",
  invalid_amount: "Amount must be greater than zero.",
  note_too_long: "Note is too long (max 1000 characters).",
  invalid_range: "The selected range is invalid.",
  is_transfer_leg: "This is part of a transfer — edit it from the transfer form.",
  not_a_transfer: "This movement isn't a transfer.",
  same_source: "Pick two different accounts.",
  unknown_tag: "One of the tags no longer exists.",
  not_yet_due: "This item isn't due yet.",
  recurring_ended: "This recurring item has ended.",
  duplicate_budget: "An active budget for this tag and currency already exists.",
  goal_not_active: "This goal isn't active.",
  alloc_from_own_source: "You can't allocate from the goal's own fund.",
  goal_cancelled: "This goal was cancelled.",
  use_close_or_delete: "Use Close (refund) or Delete to wind a goal down.",
  whim_already_purchased: "This item was already purchased.",
  not_pending: "Only pending items can do that.",
  not_dismissed: "Only dismissed items can be restored.",
  tag_name_required: "Give the tag a name.",
  duplicate_tag: "A tag with that name already exists.",
  invalid_color: "Color must be a hex code like #6366f1.",
};

/** Maps a thrown DomainError (or any error) to a localized, human message. */
export function useErrorText() {
  const { t } = useTranslation();
  return (err: unknown): string => {
    if (err instanceof DomainError) {
      return t(`err_${err.code}`, { defaultValue: MESSAGES[err.code] });
    }
    // tauri-plugin-sql rejects with a plain string, not an Error — so reading
    // `.message` alone would drop the real SQLite message and show the fallback.
    if (typeof err === "string" && err.trim()) return err;
    const msg = (err as { message?: unknown } | null)?.message;
    if (typeof msg === "string" && msg.trim()) return msg;
    return "Something went wrong.";
  };
}
