import type { ScoringConfig } from '../types';

const OPTIONS = ['none', 'streets', 'imagery'] as const;

interface Props {
  config: ScoringConfig;
  onChange: (cfg: ScoringConfig) => void;
}

export default function MapControls({ config, onChange }: Props) {
  return (
    <div className="map-card map-card-topright">
      <div className="seg">
        {OPTIONS.map((b) => (
          <button
            key={b}
            className={config.basemap === b ? 'seg-on' : ''}
            onClick={() => onChange({ ...config, basemap: b })}
          >
            {b}
          </button>
        ))}
      </div>
      <label className="opacity-row">
        scores {Math.round(config.scoreOpacity * 100)}%
        <input
          type="range" min={10} max={100} step={5}
          value={Math.round(config.scoreOpacity * 100)}
          onChange={(e) => onChange({ ...config, scoreOpacity: Number(e.target.value) / 100 })}
        />
      </label>
    </div>
  );
}
