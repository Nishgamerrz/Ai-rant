"use client";
export const MODELS = [
  { id: "fast", label: "Fast — qwen3:4b · quick drafts", hint: "cheapest, ~8 GiB" },
  { id: "medium", label: "Medium — qwen3:8b · balanced", hint: "default for shorts" },
  { id: "hard", label: "Hard — qwen3:8b · stronger reasoning", hint: "best for agent + web + code" },
  { id: "smart_11b", label: "Smart 11B — qwen3:14b · deeper", hint: "20 GiB runner" },
  { id: "animation_best", label: "Animation Best — deepseek-r1:8b", hint: "cinematic, slower" },
] as const;
export type ModelId = typeof MODELS[number]["id"];

export function ModelSelector({ value, onChange, compact }: { value: string; onChange: (v: string) => void; compact?: boolean }) {
  return (
    <div className="space-y-2">
      <label className="text-xs uppercase tracking-wide text-zinc-400">Model — same choices as the workflow</label>
      <div className={`grid gap-2 ${compact ? "grid-cols-1" : "grid-cols-1"}`}>
        {MODELS.map((m) => (
          <button
            key={m.id}
            onClick={() => onChange(m.id)}
            className={`text-left rounded-xl border px-3 py-2.5 transition ${value === m.id ? "bg-zinc-800 border-violet-500/50 ring-1 ring-violet-500/30" : "bg-zinc-900 border-zinc-800 hover:bg-zinc-800"}`}
          >
            <div className={`text-sm ${value === m.id ? "text-white" : "text-zinc-200"}`}>{m.label}</div>
            <div className="text-xs text-zinc-500">{m.hint}</div>
          </button>
        ))}
      </div>
    </div>
  );
}
