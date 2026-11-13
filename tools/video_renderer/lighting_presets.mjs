// Time-of-day looks shared by the MP4 renderer. The matching Roblox ClockTime
// mapping lives in tools/time_of_day.py so the downloadable Studio place agrees.
export const LIGHTING_PRESETS = Object.freeze({
  dawn: Object.freeze({
    sky: 0x7885a7, hemisphereSky: 0xffd3b5, hemisphereGround: 0x48536d,
    hemisphereIntensity: 0.76, ambientIntensity: 0.24,
    sunColor: 0xffb178, sunIntensity: 1.05, fillColor: 0x91a6e2,
    fillIntensity: 0.34, rimColor: 0xffd7b5, rimIntensity: 0.22, sunHeight: 130,
  }),
  day: Object.freeze({
    sky: 0x9fd0f4, hemisphereSky: 0xf2f9ff, hemisphereGround: 0x9aa88f,
    hemisphereIntensity: 0.85, ambientIntensity: 0.28,
    sunColor: 0xfff4dc, sunIntensity: 1.35, fillColor: 0xcfe4ff,
    fillIntensity: 0.30, rimColor: 0xffffff, rimIntensity: 0.20, sunHeight: 260,
  }),
  sunset: Object.freeze({
    sky: 0xe59a73, hemisphereSky: 0xffcba2, hemisphereGround: 0x65545a,
    hemisphereIntensity: 0.68, ambientIntensity: 0.24,
    sunColor: 0xff9c61, sunIntensity: 1.05, fillColor: 0x899bd6,
    fillIntensity: 0.32, rimColor: 0xffc38a, rimIntensity: 0.22, sunHeight: 75,
  }),
  night: Object.freeze({
    sky: 0x101a36, hemisphereSky: 0x8294bf, hemisphereGround: 0x303b53,
    hemisphereIntensity: 0.58, ambientIntensity: 0.23,
    sunColor: 0xa7c2ff, sunIntensity: 0.78, fillColor: 0x778fd0,
    fillIntensity: 0.38, rimColor: 0xffcf9c, rimIntensity: 0.20, sunHeight: 150,
  }),
});

export const SCENE_TIME_CHOICES = Object.freeze(Object.keys(LIGHTING_PRESETS));

const ALIASES = Object.freeze({
  morning: 'dawn', sunrise: 'dawn', daybreak: 'dawn', 'early morning': 'dawn',
  dusk: 'sunset', evening: 'sunset', 'golden hour': 'sunset',
  midday: 'day', afternoon: 'day',
  midnight: 'night', nocturnal: 'night', moonlit: 'night', moonlight: 'night', 'after dark': 'night',
});
const TIME_PATTERN = /\b(early morning|golden hour|after dark|daybreak|sunrise|morning|dawn|midday|afternoon|day|sunset|dusk|evening|midnight|nocturnal|moonlit|moonlight|night)\b/i;

function canonicalTimeOfDay(value) {
  const name = String(value || '').trim().toLowerCase().replace(/[-_]/g, ' ');
  const normalized = ALIASES[name] || name;
  return Object.hasOwn(LIGHTING_PRESETS, normalized) ? normalized : null;
}

export function resolveTimeOfDay(requested = 'auto', context = '') {
  const choice = String(requested || 'auto').trim().toLowerCase();
  if (choice === 'auto') {
    const match = String(context || '').toLowerCase().match(TIME_PATTERN);
    return match ? (canonicalTimeOfDay(match[0]) || 'day') : 'day';
  }
  const normalized = canonicalTimeOfDay(choice);
  if (normalized) return normalized;
  throw new Error(`Unknown time of day "${requested}".`);
}

function effectiveShotHour(shots, index, fallback, context) {
  let selected = fallback;
  for (let i = 0; i <= index; i += 1) {
    const value = shots[i]?.time_of_day;
    if (value && value !== 'auto') selected = resolveTimeOfDay(value, context);
  }
  return selected;
}

/** Return the two named looks and their eased blend for a timeline position. */
export function resolveLightingAtTime(plan = {}, seconds = 0) {
  const fallback = resolveTimeOfDay(plan.time_of_day || 'auto', plan.theme || '');
  const shots = Array.isArray(plan.camera_shots)
    ? plan.camera_shots.filter((shot) => shot && Number.isFinite(Number(shot.time)))
    : [];
  if (!shots.length) return { from: fallback, to: fallback, blend: 0 };

  let index = 0;
  for (let i = 0; i < shots.length; i += 1) {
    if (seconds >= Number(shots[i].time)) index = i;
    else break;
  }
  const a = shots[index];
  const b = shots[Math.min(index + 1, shots.length - 1)];
  const from = effectiveShotHour(shots, index, fallback, plan.theme || '');
  const to = effectiveShotHour(shots, Math.min(index + 1, shots.length - 1), fallback, plan.theme || '');
  let blend = 0;
  if (b !== a && from !== to && b.transition !== 'snap') {
    const duration = Math.max(0.01, Number(b.time) - Number(a.time));
    const progress = Math.max(0, Math.min(1, (seconds - Number(a.time)) / duration));
    blend = progress * progress * (3 - 2 * progress);
  }
  return { from, to, blend };
}
