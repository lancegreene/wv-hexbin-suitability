import { useRef, useState } from 'react';
import Help from './Help';
import { deletePreset, listPresets, loadPreset, parsePreset, savePreset, serializePreset } from '../persistence';
import { degToPct, effectiveSteps, metersToMiles, milesToMeters, pctToDeg, validateSteps } from '../steps';
import type { Criterion, Registry, ScoringConfig, Step } from '../types';

interface Props {
  registry: Registry;
  config: ScoringConfig;
  onChange: (cfg: ScoringConfig) => void;
  onClose: () => void;
}

const EDITABLE_UNITS = new Set(['pct_slope', 'pct', 'meters']);

function toDisplay(unit: string, stored: number): number {
  if (unit === 'pct_slope') return pctToDeg(stored);
  if (unit === 'meters') return metersToMiles(stored);
  return stored;
}
function fromDisplay(unit: string, shown: number): number {
  if (unit === 'pct_slope') return degToPct(shown);
  if (unit === 'meters') return milesToMeters(shown);
  return shown;
}
const unitLabel = (unit: string) =>
  unit === 'pct_slope' ? '°' : unit === 'meters' ? 'mi' : unit === 'minutes' ? 'min' : '%';

function StepsEditor({ c, steps, onSteps }: {
  c: Criterion; steps: Step[]; onSteps: (s: Step[]) => void;
}) {
  const errors = validateSteps(steps);
  const set = (i: number, patch: Partial<Step>) =>
    onSteps(steps.map((s, j) => (j === i ? { ...s, ...patch } : s)));
  return (
    <div className="steps-editor">
      <table>
        <thead><tr><th>≤ bound ({unitLabel(c.unit)})</th><th>score</th><th>label</th><th /></tr></thead>
        <tbody>
          {steps.map((s, i) => (
            <tr key={i}>
              <td>
                {s.max === undefined ? <em>above</em> : (
                  <input type="number" step="any"
                    value={Number(toDisplay(c.unit, s.max).toFixed(3))}
                    onChange={(e) => set(i, { max: fromDisplay(c.unit, Number(e.target.value)) })} />
                )}
              </td>
              <td>
                <input type="number" min={0} max={1} step={0.05} value={s.score}
                  onChange={(e) => set(i, { score: Number(e.target.value) })} />
              </td>
              <td>
                <input type="text" value={s.label}
                  onChange={(e) => set(i, { label: e.target.value })} />
              </td>
              <td>
                {s.max !== undefined && (
                  <button className="secondary" onClick={() => onSteps(steps.filter((_, j) => j !== i))}>×</button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <button className="secondary" onClick={() => {
        const lastBound = steps.filter((s) => s.max !== undefined).pop();
        const newMax = (lastBound?.max ?? 0) * 2 || fromDisplay(c.unit, 1);
        onSteps([...steps.slice(0, -1), { max: newMax, score: 0.5, label: 'new class' }, steps[steps.length - 1]]);
      }}>+ class</button>
      {errors.length > 0 && (
        <div className="steps-errors">{errors.map((e, i) => <div key={i}>{e}</div>)}</div>
      )}
      <div className="muted">stored bounds: {steps.filter((s) => s.max !== undefined)
        .map((s) => `${s.max?.toFixed(1)}`).join(', ')} ({c.unit})</div>
    </div>
  );
}

export default function SettingsDrawer({ registry, config, onChange, onClose }: Props) {
  const [presetName, setPresetName] = useState('');
  const [importError, setImportError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const defaultStepsFor = (c: Criterion): Step[] =>
    c.unit === 'pct_slope'
      ? [{ max: degToPct(5), score: 1.0, label: 'no limitations' },
         { max: degToPct(10), score: 0.5, label: 'some limitations' },
         { score: 0.0, label: 'not advised' }]
      : [{ max: fromDisplay(c.unit, 1), score: 1.0, label: 'good' },
         { max: fromDisplay(c.unit, 3), score: 0.5, label: 'fair' },
         { score: 0.0, label: 'poor' }];

  return (
    <div className="drawer">
      <div className="drawer-head">
        <strong>Scoring settings</strong>
        <button className="secondary" onClick={onClose}>close</button>
      </div>

      {registry.criteria.filter((c) => EDITABLE_UNITS.has(c.unit) || c.membership.fn === 'steps').map((c) => {
        const ov = config.normalization[c.key];
        const isDefaultSteps = c.membership.fn === 'steps'; // no curve fallback to offer
        const hasOverride = ov?.mode === 'steps';
        const stepped = hasOverride || isDefaultSteps;
        const resetToDefault = () => {
          const { [c.key]: _drop, ...rest } = config.normalization;
          onChange({ ...config, normalization: rest });
        };
        return (
          <section className="panel-card" key={c.key}>
            <div className="group-title">{c.label}<Help id="normalization" /></div>
            <div className="controls-row">
              {isDefaultSteps ? (
                <span>
                  {hasOverride ? 'Classes (custom)' : 'Classes (default)'}
                  {hasOverride && (
                    <button className="secondary" onClick={resetToDefault}>reset to default</button>
                  )}
                </span>
              ) : (
                <>
                  <label><input type="radio" checked={!stepped} onChange={resetToDefault} /> Curve</label>
                  <label><input type="radio" checked={stepped}
                    onChange={() => onChange({ ...config, normalization: {
                      ...config.normalization, [c.key]: { mode: 'steps', steps: defaultStepsFor(c) } } })} /> Classes</label>
                </>
              )}
            </div>
            {stepped ? (
              <StepsEditor c={c} steps={effectiveSteps(c, ov) ?? defaultStepsFor(c)}
                onSteps={(steps) => onChange({ ...config, normalization: {
                  ...config.normalization, [c.key]: { mode: 'steps', steps } } })} />
            ) : (
              <div className="muted">
                {c.membership.fn === 'small'
                  ? `curve: 0.5 at ${toDisplay(c.unit, c.membership.midpoint).toFixed(1)}${unitLabel(c.unit)}`
                  : `curve: ${c.membership.fn}`}
              </div>
            )}
          </section>
        );
      })}

      <section className="panel-card">
        <div className="group-title">Presets<Help id="presets" /></div>
        <div className="controls-row">
          <input type="text" placeholder="preset name" value={presetName}
            onChange={(e) => setPresetName(e.target.value)} />
          <button disabled={!presetName.trim()}
            onClick={() => { savePreset(presetName.trim(), config); setPresetName(''); }}>
            Save as
          </button>
        </div>
        {listPresets().map((p) => (
          <div className="controls-row" key={p.name}>
            <span style={{ flex: 1 }}>{p.name}</span>
            <button className="secondary" onClick={() => {
              const cfg = loadPreset(p.name, registry);
              if (cfg) onChange(cfg);
            }}>Load</button>
            <button className="secondary" onClick={() => {
              const a = document.createElement('a');
              a.href = URL.createObjectURL(new Blob([serializePreset(p.name, loadPreset(p.name, registry) ?? config)],
                { type: 'application/json' }));
              a.download = `${p.name}.suitability-preset.json`;
              document.body.appendChild(a); a.click(); a.remove();
              setTimeout(() => URL.revokeObjectURL(a.href), 2000);
            }}>Export</button>
            {confirmDelete === p.name ? (
              <button onClick={() => { deletePreset(p.name); setConfirmDelete(null); }}>confirm ×</button>
            ) : (
              <button className="secondary" onClick={() => setConfirmDelete(p.name)}>×</button>
            )}
          </div>
        ))}
        <div className="controls-row">
          <button className="secondary" onClick={() => fileRef.current?.click()}>Import preset file…</button>
          <input ref={fileRef} type="file" accept=".json" style={{ display: 'none' }}
            onChange={async (e) => {
              const f = e.target.files?.[0];
              if (!f) return;
              try {
                const parsed = parsePreset(await f.text(), registry);
                savePreset(parsed.name, parsed.config);
                setImportError(null);
              } catch (err) {
                setImportError(err instanceof Error ? err.message : String(err));
              } finally {
                e.target.value = '';
              }
            }} />
        </div>
        {importError && <div className="steps-errors">import failed: {importError}</div>}
      </section>
    </div>
  );
}
