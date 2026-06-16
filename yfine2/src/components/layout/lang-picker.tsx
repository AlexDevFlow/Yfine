import { Languages } from "lucide-react";
import { useTranslation } from "react-i18next";
import { SUPPORTED_LANGS } from "@/i18n";

export function LangPicker() {
  const { i18n } = useTranslation();
  const current = SUPPORTED_LANGS.some((l) => l.code === i18n.resolvedLanguage)
    ? i18n.resolvedLanguage
    : "en";
  return (
    <label className="relative inline-flex items-center">
      <Languages className="pointer-events-none absolute left-2.5 h-[18px] w-[18px] text-muted" />
      <select
        aria-label="Language"
        value={current}
        onChange={(e) => void i18n.changeLanguage(e.target.value)}
        className="h-9 cursor-pointer appearance-none rounded-[var(--radius-control)] bg-transparent pl-9 pr-7 text-sm font-medium text-muted outline-none transition-colors hover:bg-surface-2 hover:text-foreground"
      >
        {SUPPORTED_LANGS.map((l) => (
          <option key={l.code} value={l.code} className="bg-surface text-foreground">
            {l.label}
          </option>
        ))}
      </select>
    </label>
  );
}
