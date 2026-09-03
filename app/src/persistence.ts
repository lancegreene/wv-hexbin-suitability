import { defaultConfig } from './registry';
import { validateSteps } from './steps';
import type { NormalizationOverride, Registry, ScoringConfig } from './types';

const CURRENT_KEY = 'hexbin.current.v1';
const PRESETS_KEY = 'hexbin.presets.v1';

type Store = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;
const browserStore = (): Store => window.localStorage;

/** Overlay a raw (untrusted) config onto registry defaults, dropping anything invalid. */
export function reconcile(raw: unknown, reg: Registry): ScoringConfig {
  const out = defaultConfig(reg);
  if (typeof raw !== 'object' || raw === null) return out;
  const r = raw as Partial<ScoringConfig> & Record<string, unknown>;
  const known = new Set(reg.criteria.map((c) => c.key));

  if (r.weights && typeof r.weights === 'object') {
    for (const [k, v] of Object.entries(r.weights)) {
      if (known.has(k) && typeof v === 'number' && Number.isFinite(v) && v >= 0) out.weights[k] = v;
      else if (!known.has(k)) console.warn(`preset: dropping unknown criterion weight '${k}'`);
    }
  }
  if (r.masksEnabled && typeof r.masksEnabled === 'object') {
    for (const m of reg.masks) {
      const v = (r.masksEnabled as Record<string, unknown>)[m.key];
      if (typeof v === 'boolean') out.masksEnabled[m.key] = v;
    }
  }
  if (typeof r.slopeThreshold === 'number' && Number.isFinite(r.slopeThreshold)) out.slopeThreshold = r.slopeThreshold;
  if (typeof r.minAcres === 'number' && Number.isFinite(r.minAcres) && r.minAcres >= 0) out.minAcres = r.minAcres;
  if (typeof r.scoreOpacity === 'number' && r.scoreOpacity > 0 && r.scoreOpacity <= 1) out.scoreOpacity = r.scoreOpacity;
  if (r.aggregation === 'wlc' || r.aggregation === 'geometric') out.aggregation = r.aggregation;
  if (r.resolution === 8 || r.resolution === 9 || r.resolution === 10) out.resolution = r.resolution;
  if (r.displayMode === 'hex' || r.displayMode === 'parcel') out.displayMode = r.displayMode;
  if (r.basemap === 'none' || r.basemap === 'streets' || r.basemap === 'imagery') out.basemap = r.basemap;

  if (r.normalization && typeof r.normalization === 'object') {
    for (const [k, ov] of Object.entries(r.normalization as Record<string, NormalizationOverride>)) {
      if (!known.has(k)) { console.warn(`preset: dropping normalization for unknown '${k}'`); continue; }
      if (ov?.mode === 'curve') {
        const crit = reg.criteria.find((c) => c.key === k);
        if (crit?.membership.fn === 'steps') {
          // A steps-default criterion has no curve: scoring would use the
          // default steps while labels/drawer saw "curve" — silent divergence
          console.warn(`preset: '${k}' has no curve to fall back to — dropping curve override`);
          continue;
        }
        out.normalization[k] = ov;
      }
      else if (ov?.mode === 'steps' && Array.isArray(ov.steps) && validateSteps(ov.steps).length === 0) {
        out.normalization[k] = ov;
      } else console.warn(`preset: dropping invalid classes for '${k}'`);
    }
  }
  return out;
}

export function saveCurrent(cfg: ScoringConfig, store: Store = browserStore()): void {
  store.setItem(CURRENT_KEY, JSON.stringify(cfg));
}

export function loadCurrent(reg: Registry, store: Store = browserStore()): ScoringConfig {
  const raw = store.getItem(CURRENT_KEY);
  if (raw === null) return defaultConfig(reg);
  try {
    return reconcile(JSON.parse(raw), reg);
  } catch {
    console.warn('persistence: stored config unreadable, using defaults');
    return defaultConfig(reg);
  }
}

interface PresetEntry { name: string; savedAt: string; config: ScoringConfig }

function readPresets(store: Store): PresetEntry[] {
  try {
    const raw = store.getItem(PRESETS_KEY);
    return raw ? (JSON.parse(raw) as PresetEntry[]) : [];
  } catch {
    console.warn('persistence: preset store unreadable, starting empty');
    return [];
  }
}

export function listPresets(store: Store = browserStore()): { name: string; savedAt: string }[] {
  return readPresets(store).map(({ name, savedAt }) => ({ name, savedAt }));
}

export function savePreset(name: string, cfg: ScoringConfig, store: Store = browserStore()): void {
  const presets = readPresets(store).filter((p) => p.name !== name);
  presets.push({ name, savedAt: new Date().toISOString(), config: cfg });
  store.setItem(PRESETS_KEY, JSON.stringify(presets));
}

export function loadPreset(name: string, reg: Registry, store: Store = browserStore()): ScoringConfig | null {
  const hit = readPresets(store).find((p) => p.name === name);
  return hit ? reconcile(hit.config, reg) : null;
}

export function deletePreset(name: string, store: Store = browserStore()): void {
  store.setItem(PRESETS_KEY, JSON.stringify(readPresets(store).filter((p) => p.name !== name)));
}

export function serializePreset(name: string, cfg: ScoringConfig): string {
  return JSON.stringify(
    { format: 'hexbin-preset-v1', name, savedAt: new Date().toISOString(), config: cfg },
    null, 2);
}

export function parsePreset(text: string, reg: Registry): { name: string; config: ScoringConfig } {
  let obj: unknown;
  try {
    obj = JSON.parse(text);
  } catch {
    throw new Error('not valid JSON');
  }
  const p = obj as { format?: string; name?: string; config?: unknown };
  if (p.format !== 'hexbin-preset-v1') {
    throw new Error(`unrecognized file — expected format "hexbin-preset-v1", got "${p.format}"`);
  }
  if (!p.name || typeof p.name !== 'string') throw new Error('preset has no name');
  return { name: p.name, config: reconcile(p.config, reg) };
}
