/**
 * Absolute URL for a published artifact, resolved against the page URL —
 * not the domain root — so the app works when hosted under a subpath
 * (GitHub Pages serves it at /<repo>/). Absolute because DuckDB fetches
 * from its worker, which would resolve a relative URL against assets/.
 */
export function assetUrl(name: string): string {
  return new URL(name, document.baseURI).href;
}
