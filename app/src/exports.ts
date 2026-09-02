import { labelForScore } from './steps';
import type { Registry, ScoringConfig } from './types';

function download(filename: string, mime: string, content: string): void {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([content], { type: mime }));
  a.download = filename;
  document.body.appendChild(a); // required by some browsers for programmatic clicks
  a.click();
  a.remove();
  // Synchronous revoke is flaky for large blobs (~30 MB GeoJSON): the download
  // may not have started reading the URL yet
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}

const csvCell = (v: unknown): string => {
  if (v == null) return '';
  const s = String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
};

/** For each stepped criterion (keyed off config.normalization), the class label
 *  (prefixed `~` when inexact) for a row. */
function classProperties(row: Record<string, unknown>, config: ScoringConfig): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [key, ov] of Object.entries(config.normalization)) {
    if (ov.mode !== 'steps') continue;
    const { label, exact } = labelForScore(ov.steps, Number(row[`m_${key}`]));
    out[`${key}_class`] = exact ? label : `~${label}`;
  }
  return out;
}

/** Full ranked parcel list -> CSV download. */
export function exportCSV(rows: Record<string, unknown>[], reg: Registry, config: ScoringConfig): void {
  const steppedKeys = reg.criteria
    .filter((c) => config.normalization[c.key]?.mode === 'steps')
    .map((c) => `${c.key}_class`);
  const cols = ['parcel_id', 'score', 'masked_frac', 'acres', 'FullOwnerName',
    'DistrictName', 'PropertyClassDescription', ...reg.criteria.map((c) => `m_${c.key}`), ...steppedKeys];
  const lines = [
    'rank,' + cols.join(','),
    ...rows.map((r, i) => {
      const withClass = { ...r, ...classProperties(r, config) };
      return `${i + 1},` + cols.map((c) => csvCell(withClass[c])).join(',');
    }),
  ];
  download('parcel_scores_54081.csv', 'text/csv', lines.join('\n'));
}

/** Scores merged onto the display geometry -> GeoJSON download. */
export function exportGeoJSON(
  rows: Record<string, unknown>[],
  parcelsGeojson: { type: string; features: { properties: { parcel_id: string } }[] },
  config: ScoringConfig,
): void {
  const byId = new Map(rows.map((r, i) => [String(r.parcel_id), { ...r, rank: i + 1 }]));
  const features = parcelsGeojson.features
    .filter((f) => byId.has(f.properties.parcel_id))
    .map((f) => {
      const r = byId.get(f.properties.parcel_id)!;
      return { ...f, properties: { ...f.properties, ...r, ...classProperties(r, config) } };
    });
  download('parcel_scores_54081.geojson', 'application/geo+json',
    JSON.stringify({ type: 'FeatureCollection', features }));
}
