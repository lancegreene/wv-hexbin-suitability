import type { Step } from './types';

/** Returns [] when valid, else human-readable problems (shown inline in the drawer). */
export function validateSteps(steps: Step[]): string[] {
  const errors: string[] = [];
  if (steps.length < 2) errors.push('need at least 2 classes');
  const catchalls = steps.filter((s) => s.max === undefined);
  if (catchalls.length !== 1) errors.push('exactly one catch-all class (no upper bound) required');
  else if (steps.length && steps[steps.length - 1].max !== undefined) {
    errors.push('the catch-all class must be last');
  }
  let prev = -Infinity;
  for (const s of steps) {
    if (s.max !== undefined) {
      if (!Number.isFinite(s.max)) errors.push(`bound ${s.max} is not a finite number`);
      else if (s.max <= prev) errors.push(`bounds must be strictly ascending (${s.max} after ${prev})`);
      if (Number.isFinite(s.max)) prev = s.max;
    }
    if (!Number.isFinite(s.score) || s.score < 0 || s.score > 1) {
      errors.push(`score ${s.score} outside [0,1]`);
    }
    if (!s.label.trim()) errors.push('every class needs a label');
  }
  return errors;
}

export const degToPct = (deg: number): number => Math.tan((deg * Math.PI) / 180) * 100;
export const pctToDeg = (pct: number): number => (Math.atan(pct / 100) * 180) / Math.PI;
export const milesToMeters = (mi: number): number => mi * 1609.344;
export const metersToMiles = (m: number): number => m / 1609.344;

/** Class label whose score is nearest the (possibly averaged) shown value. */
export function labelForScore(steps: Step[], score: number): { label: string; exact: boolean } {
  let best = steps[0];
  let bestD = Infinity;
  for (const s of steps) {
    const d = Math.abs(s.score - score);
    if (d < bestD) { bestD = d; best = s; }
  }
  return { label: best.label, exact: bestD < 1e-9 };
}
