import type { Language, Translator } from "../i18n";

export type PageProps = {
  language: Language;
  t: Translator;
};

export type JsonObject = Record<string, unknown>;

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
