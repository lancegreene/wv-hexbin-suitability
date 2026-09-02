import type { Registry } from './types';

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

/** Full ranked parcel list -> CSV download. */
export function exportCSV(rows: Record<string, unknown>[], reg: Registry): void {
  const cols = ['parcel_id', 'score', 'masked_frac', 'acres', 'FullOwnerName',
    'DistrictName', 'PropertyClassDescription', ...reg.criteria.map((c) => `m_${c.key}`)];
  const lines = [
    'rank,' + cols.join(','),
    ...rows.map((r, i) => `${i + 1},` + cols.map((c) => csvCell(r[c])).join(',')),
  ];
  download('parcel_scores_54081.csv', 'text/csv', lines.join('\n'));
}

/** Scores merged onto the display geometry -> GeoJSON download. */
export function exportGeoJSON(
  rows: Record<string, unknown>[],
  parcelsGeojson: { type: string; features: { properties: { parcel_id: string } }[] },
): void {
  const byId = new Map(rows.map((r, i) => [String(r.parcel_id), { ...r, rank: i + 1 }]));
  const features = parcelsGeojson.features
    .filter((f) => byId.has(f.properties.parcel_id))
    .map((f) => ({ ...f, properties: { ...f.properties, ...byId.get(f.properties.parcel_id) } }));
  download('parcel_scores_54081.geojson', 'application/geo+json',
    JSON.stringify({ type: 'FeatureCollection', features }));
}
