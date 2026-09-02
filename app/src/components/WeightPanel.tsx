import type { Registry, ScoringConfig } from '../types';

interface Props {
  registry: Registry;
  config: ScoringConfig;
  onChange: (cfg: ScoringConfig) => void;
}

export default function WeightPanel({ registry, config, onChange }: Props) {
  const groups = [...new Set(registry.criteria.map((c) => c.group))];
  const total = Object.values(config.weights).reduce((s, w) => s + w, 0);

  return (
    <div className="panel">
      {groups.map((g) => (
        <div key={g}>
          <div className="group-title">{g}</div>
          {registry.criteria.filter((c) => c.group === g).map((c) => (
            <div className="slider-row" key={c.key}>
              <label>
                <span>
                  {c.label}
                  {c.confidence !== 'authoritative' && <span className="badge">{c.confidence}</span>}
                </span>
                <span>{total > 0 ? ((config.weights[c.key] / total) * 100).toFixed(0) : '—'}%</span>
              </label>
              <input
                type="range" min={0} max={100} step={1}
                value={Math.round(config.weights[c.key] * 100)}
                onChange={(e) =>
                  onChange({ ...config, weights: { ...config.weights, [c.key]: Number(e.target.value) / 100 } })}
                style={{ width: '100%' }}
              />
            </div>
          ))}
        </div>
      ))}

      <div className="group-title">Constraints (hard masks)</div>
      {registry.masks.map((m) => (
        <div className="controls-row" key={m.key}>
          <label>
            <input
              type="checkbox"
              checked={config.masksEnabled[m.key]}
              onChange={(e) =>
                onChange({ ...config, masksEnabled: { ...config.masksEnabled, [m.key]: e.target.checked } })}
            />{' '}
            {m.label}
          </label>
          {m.key === 'slope_limit' && (
            <input
              type="number" min={5} max={100} step={5}
              value={config.slopeThreshold}
              onChange={(e) => onChange({ ...config, slopeThreshold: Number(e.target.value) })}
              style={{ width: 55 }}
            />
          )}
        </div>
      ))}

      <div className="group-title">Scoring</div>
      <div className="controls-row">
        <label><input type="radio" checked={config.aggregation === 'wlc'}
          onChange={() => onChange({ ...config, aggregation: 'wlc' })} /> Weighted sum</label>
        <label><input type="radio" checked={config.aggregation === 'geometric'}
          onChange={() => onChange({ ...config, aggregation: 'geometric' })} /> Geometric</label>
      </div>

      <div className="group-title">Display</div>
      <div className="controls-row">
        <label>Hex res{' '}
          <select value={config.resolution}
            onChange={(e) => onChange({ ...config, resolution: Number(e.target.value) as 8 | 9 | 10 })}>
            <option value={8}>8 (coarse)</option>
            <option value={9}>9</option>
            <option value={10}>10 (full)</option>
          </select>
        </label>
        <label><input type="radio" checked={config.displayMode === 'hex'}
          onChange={() => onChange({ ...config, displayMode: 'hex' })} /> Hexes</label>
        <label><input type="radio" checked={config.displayMode === 'parcel'}
          onChange={() => onChange({ ...config, displayMode: 'parcel' })} /> Parcels</label>
      </div>
      {total === 0 && <p className="masked-flag">All weights are zero — scoring disabled.</p>}
    </div>
  );
}
