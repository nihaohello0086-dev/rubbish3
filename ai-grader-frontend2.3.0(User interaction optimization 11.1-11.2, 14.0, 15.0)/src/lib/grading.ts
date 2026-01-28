// src/lib/grading.ts
import type { JsonValue, Loose } from "../types/grading";

// Pretty-print any value as JSON string
export const pretty = (v: unknown): string => {
  try {
    return JSON.stringify(v, null, 2);
  } catch {
    return String(v);
  }
};

// Try parse JSON array from text, mainly for rubric
export function tryParseJsonArray(text: string): JsonValue[] | null {
  try {
    const data = JSON.parse(text);
    return Array.isArray(data) ? (data as JsonValue[]) : null;
  } catch {
    return null;
  }
}

// Download JSON as a file
export function downloadJson(filename: string, data: unknown) {
  const blob = new Blob([JSON.stringify(data, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

// Safe helpers
export const pick = (o: Loose, keys: string[]): unknown => {
  for (const k of keys) if (k in o) return o[k];
  return undefined;
};

export const toNum = (v: unknown, def = 0): number => {
  const n = Number(v);
  return Number.isFinite(n) ? n : def;
};

export const toStr = (v: unknown): string | undefined => {
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  return undefined;
};

/**
 * 从用户输入的 rubric 文本中提取维度名称列表
 * - 支持 JSON 数组形式：["Completeness","Method",...]
 * - 支持对象数组形式：[{ criterion: "Completeness", ... }, ...]
 * - 其它情况返回 []
 */
export const getRubricNamesFromUser = (text: string): string[] => {
  const trimmed = text?.trim();
  if (!trimmed) return [];
  try {
    const data = JSON.parse(trimmed);
    if (Array.isArray(data)) {
      return data
        .map((it) => {
          if (typeof it === "string") return it;
          if (it && typeof it === "object") {
            const o = it as Loose;
            return (
              toStr(
                pick(o, [
                  "criterion",
                  "item",
                  "name",
                  "title",
                  "dimension",
                  "aspect",
                  "label",
                ])
              ) ?? ""
            );
          }
          return "";
        })
        .filter(Boolean);
    }
  } catch {
    // not JSON
  }
  return [];
};

/**
 * 构造发送给后端的 rubric 字段：
 * - 若用户输入合法 JSON 数组 -> 提取名称后 join(", ")
 * - 否则直接使用原始文本（建议逗号分隔）
 */
export const buildRubricField = (rawText: string): string | undefined => {
  const trimmed = rawText.trim();
  if (!trimmed) return undefined;

  const fromJsonNames = getRubricNamesFromUser(trimmed);
  if (fromJsonNames.length > 0) {
    return fromJsonNames.join(", ");
  }
  return trimmed;
};
