import en from "./en.json";

export type Language = "en";

const dictionary: Record<string, unknown> = en;

export function getTranslation(keyPath: string, params?: Record<string, string | number>): string {
  const parts = keyPath.split(".");
  let current: unknown = dictionary;

  for (const part of parts) {
    if (current && typeof current === "object" && part in (current as Record<string, unknown>)) {
      current = (current as Record<string, unknown>)[part];
    } else {
      current = undefined;
      break;
    }
  }

  if (typeof current !== "string") {
    return keyPath;
  }

  if (params) {
    let result = current;
    for (const [k, v] of Object.entries(params)) {
      result = result.replace(new RegExp(`{{\\s*${k}\\s*}}`, "g"), String(v));
    }
    return result;
  }

  return current;
}
