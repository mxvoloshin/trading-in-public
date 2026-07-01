# SPY ORB Decision Note

## Scope

This note records the current family-level decision for the active ORB branch.

## What Was Tested

- one clean ORB baseline family
- baseline stop and trade-count variants
- exit-only variants off the midpoint-stop baseline

Related notes:

- `docs/research/spy-orb-thesis.md`
- `docs/research/spy-opening-range-breakout-trend-hold-baseline.md`
- `docs/research/spy-orb-exit-comparison.md`

## Result

Status: active research
Decision: keep

Summary:
- Window: active conclusions currently rely on one local one-year baseline window
  plus one separate one-year exit-comparison window
- What passed: the midpoint-stop baseline is the strongest tested branch so far
- What failed: exit-only variants did not improve the branch
- What remains unknown: larger-history behavior and entry-quality improvements
- Next action: test one entry-quality improvement at a time off the midpoint
  baseline and expand validation

## Current Working Baseline

- strategy: `spy-opening-range-breakout-trend-hold-midpoint-stop-max-1`
- family: `spy-opening-range-breakout-trend-hold`
- variant: `orb-midpoint-stop-max-1`

## Promotion Rule

Do not move this branch to paper trading until it passes:

- expanded validation on a larger history window
- acceptable base-cost expectancy
- acceptable stress behavior
- acceptable drawdown and concentration
- stable behavior outside one favorable window
