import { labelForScore } from '../steps';
import type { Registry, ScoringConfig } from '../types';

const TOP_N = 500; // table shows the head; exports include every parcel

interface Props {
  registry: Registry;
  config: ScoringConfig;
  rows: Record<string, unknown>[];
  onRowClick: (parcelId: string) => void;
  onExportCSV: () => void;
  onExportGeoJSON: () => void;
}

export default function RankTable({ registry, config, rows, onRowClick, onExportCSV, onExportGeoJSON }: Props) {
  return (
    <div className="rank-dock">
      <div className="controls-row" style={{ padding: '6px 8px' }}>
        <strong>Ranked parcels</strong>
        <span>top {Math.min(TOP_N, rows.length)} of {rows.length.toLocaleString()} shown — exports include all</span>
        <span style={{ flex: 1 }} />
        <button onClick={onExportCSV}>Export CSV</button>
        <button className="secondary" onClick={onExportGeoJSON}>Export GeoJSON</button>
      </div>
      <table>
        <thead>
          <tr>
            <th>#</th><th>Parcel</th><th>Owner</th><th>Acres</th><th>Score</th><th>Masked</th>
            {registry.criteria.map((c) => <th key={c.key}>{c.label}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, TOP_N).map((r, i) => (
            <tr key={String(r.parcel_id)} onClick={() => onRowClick(String(r.parcel_id))}
                style={{ cursor: 'pointer' }}>
              <td>{i + 1}</td>
              <td>{String(r.parcel_id)}</td>
              <td style={{ textAlign: 'left' }}>{String(r.FullOwnerName ?? '')}</td>
              <td>{Number(r.acres).toFixed(1)}</td>
              <td><strong>{Number(r.score).toFixed(3)}</strong></td>
              <td className={Number(r.masked_frac) > 0 ? 'masked-flag' : ''}>
                {Number(r.masked_frac) > 0 ? `${(Number(r.masked_frac) * 100).toFixed(0)}%` : '—'}
              </td>
              {registry.criteria.map((c) => {
                const v = Number(r[`m_${c.key}`]);
                const ov = config.normalization[c.key];
                const lab = ov?.mode === 'steps' ? labelForScore(ov.steps, v) : null;
                return (
                  <td key={c.key}>
                    {v.toFixed(2)}
                    {lab && <div className="class-label">{lab.exact ? '' : '~'}{lab.label}</div>}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
