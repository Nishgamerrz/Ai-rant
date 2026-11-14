"use client";
import { MODEL_IDS, MODEL_PRESETS, type ModelId } from "@/lib/modelPresets";

export { type ModelId };
export const MODELS = MODEL_IDS.map((id) => {
  const preset = MODEL_PRESETS[id];
  return {
    id,
    label: preset.label,
    desc: `${preset.model} · ${preset.summary}`,
    meta: preset.meta,
  };
});

export function ModelSelector({ value, onChange }: { value: ModelId; onChange: (v: ModelId) => void }) {
  return (
    <div className="space-y-2.5">
      <div className="text-[11px] font-semibold tracking-widest text-zinc-500 uppercase">Model</div>
      <div className="grid gap-1.5">
        {MODELS.map((m) => {
          const active = value === m.id;
          return (
            <button
              key={m.id}
              onClick={() => onChange(m.id)}
              className={`group relative flex items-center gap-3 w-full text-left rounded-xl border px-3.5 py-3 transition-all ${
                active
                  ? "bg-white text-zinc-900 border-white shadow-soft"
                  : "bg-zinc-900/50 border-zinc-800 hover:bg-zinc-900 hover:border-zinc-700 text-zinc-300"
              }`}
            >
              <div className={`h-8 w-8 rounded-lg grid place-items-center text-xs font-semibold shrink-0 ${active ? "bg-zinc-900 text-white" : "bg-zinc-800 text-zinc-400 group-hover:bg-zinc-700"}`}>
                {m.label[0]}
              </div>
              <div className="min-w-0 flex-1">
                <div className={`text-sm font-medium leading-tight ${active ? "text-zinc-900" : "text-zinc-200"}`}>{m.label}</div>
                <div className={`text-xs leading-tight ${active ? "text-zinc-600" : "text-zinc-500"}`}>{m.desc}</div>
              </div>
              <span className={`text-[10px] font-semibold tracking-wide px-2 py-1 rounded-full shrink-0 ${active ? "bg-zinc-900 text-white" : "bg-zinc-800 text-zinc-500 border border-zinc-700"}`}>
                {m.meta}
              </span>
              {active && <span className="absolute right-3 top-3 h-1.5 w-1.5 rounded-full bg-emerald-500 shadow-[0_0_6px_rgba(16,185,129,0.6)]" />}
            </button>
          );
        })}
      </div>
    </div>
  );
}
