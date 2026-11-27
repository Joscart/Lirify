export type Language = "es" | "en";

export const LANGUAGE_COOKIE = "upspotify-language";

export function resolveLanguage(url: URL, saved?: string): Language {
  const requested = url.searchParams.get("lang");
  if (requested === "en" || requested === "es") return requested;
  return saved === "en" ? "en" : "es";
}

export function translator(language: Language) {
  return (es: string, en: string) => language === "en" ? en : es;
}

export const language: Language =
  typeof document !== "undefined" && document.documentElement.lang === "en" ? "en" : "es";

export const text = translator(language);

export function inLanguage(url: string, locale: Language): string {
  const target = new URL(url, location.origin);
  target.searchParams.set("lang", locale);
  return target.href;
}
