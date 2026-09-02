import { describe, expect, it } from 'vitest';
import { degToPct, effectiveSteps, labelForScore, metersToMiles, milesToMeters, pctToDeg, validateSteps } from '../src/steps';
import type { Step } from '../src/types';

const GOOD: Step[] = [
  { max: 8.75, score: 1.0, label: 'no limitations' },
  { max: 17.63, score: 0.5, label: 'some grading' },
  { score: 0.0, label: 'not advised' },
];

describe('validateSteps', () => {
  it('accepts a valid 3-class scheme', () => expect(validateSteps(GOOD)).toEqual([]));
  it('rejects fewer than 2 classes', () =>
    expect(validateSteps([{ score: 1, label: 'x' }])).not.toEqual([]));
  it('rejects missing catch-all', () =>
    expect(validateSteps([{ max: 1, score: 1, label: 'a' }, { max: 2, score: 0, label: 'b' }])
      .join()).toMatch(/catch-all/));
  it('rejects a catch-all not in last position', () =>
    expect(validateSteps([{ score: 0, label: 'z' }, { max: 5, score: 1, label: 'a' }])
      .join()).toMatch(/last/));
  it('rejects non-ascending bounds', () =>
    expect(validateSteps([{ max: 10, score: 1, label: 'a' }, { max: 5, score: 0.5, label: 'b' },
      { score: 0, label: 'c' }]).join()).toMatch(/ascending/));
  it('rejects out-of-range scores and empty labels', () => {
    expect(validateSteps([{ max: 1, score: 1.5, label: 'a' }, { score: 0, label: 'b' }])
      .join()).toMatch(/\[0,1\]/);
    expect(validateSteps([{ max: 1, score: 1, label: '  ' }, { score: 0, label: 'b' }])
      .join()).toMatch(/label/);
  });
});

describe('unit conversions', () => {
  it('5 degrees is ~8.75 percent slope, and round-trips', () => {
    expect(degToPct(5)).toBeCloseTo(8.7489, 3);
    expect(pctToDeg(degToPct(23.4))).toBeCloseTo(23.4, 9);
  });
  it('miles round-trip', () =>
    expect(metersToMiles(milesToMeters(3.2))).toBeCloseTo(3.2, 9));
});

describe('effectiveSteps', () => {
  const defSteps = [{ max: 10, score: 1, label: 'near' }, { score: 0, label: 'far' }];
  const curveCrit = { membership: { fn: 'small', midpoint: 1, spread: 1 } } as never;
  const stepsCrit = { membership: { fn: 'steps', steps: defSteps } } as never;
  it('override wins', () =>
    expect(effectiveSteps(stepsCrit, { mode: 'steps', steps: [{ score: 1, label: 'a' },
      { score: 0, label: 'b' }] })?.[0].label).toBe('a'));
  it('registry default steps apply when no override', () =>
    expect(effectiveSteps(stepsCrit, undefined)?.[0].label).toBe('near'));
  it('curve criterion without override has no steps', () =>
    expect(effectiveSteps(curveCrit, undefined)).toBeNull());
});

describe('labelForScore', () => {
  it('exact match', () =>
    expect(labelForScore(GOOD, 0.5)).toEqual({ label: 'some grading', exact: true }));
  it('nearest match flagged inexact', () =>
    expect(labelForScore(GOOD, 0.72)).toEqual({ label: 'some grading', exact: false }));
});
