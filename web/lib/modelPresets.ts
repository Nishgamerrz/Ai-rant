import manifest from "./model_presets.json";

/** One source of truth for the website and the GitHub Actions model resolver. */
export const MODEL_PRESETS = manifest.presets;
export type ModelId = keyof typeof MODEL_PRESETS;
export type ModelPreset = (typeof MODEL_PRESETS)[ModelId];

export const MODEL_IDS = Object.keys(MODEL_PRESETS) as ModelId[];

export function normalizeModelId(value: unknown): ModelId | null {
  if (typeof value !== "string") return null;
  const normalized = value.trim().toLowerCase();
  return Object.prototype.hasOwnProperty.call(MODEL_PRESETS, normalized)
    ? (normalized as ModelId)
    : null;
}
