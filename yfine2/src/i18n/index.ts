import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import LanguageDetector from "i18next-browser-languagedetector";

import en from "./locales/en.json";
import it from "./locales/it.json";
import es from "./locales/es.json";
import uk from "./locales/uk.json";

export const SUPPORTED_LANGS = [
  { code: "en", label: "English" },
  { code: "it", label: "Italiano" },
  { code: "es", label: "Español" },
  { code: "uk", label: "Українська" },
] as const;

export type LangCode = (typeof SUPPORTED_LANGS)[number]["code"];

// Locales are reused verbatim from the legacy app (flat key -> string maps),
// fully translated in all four languages. New keys are added to en first and
// fall back to en until translated.
void i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: {
      en: { translation: en },
      it: { translation: it },
      es: { translation: es },
      uk: { translation: uk },
    },
    fallbackLng: "en",
    supportedLngs: SUPPORTED_LANGS.map((l) => l.code),
    interpolation: { escapeValue: false },
    react: { useSuspense: false },
    detection: {
      order: ["localStorage", "navigator"],
      lookupLocalStorage: "yfine.lang",
      caches: ["localStorage"],
    },
  });

export default i18n;
