# Research Artifacts

This document defines the artifact rules for strategy research in this repo.

Use it to keep the working set small, consistent, and easy to navigate.

## Purpose

Every research artifact should have one clear role:

- explain a strategy idea
- record a decision
- store normalized market data
- store a canonical backtest result
- store a validation result

If an artifact does not clearly fit one of those roles, do not keep it.

## Allowed Locations

### Narrative Documents

- Strategy notes and decision writeups:
  `docs/research/*.md`
- Architecture and system docs:
  `docs/architecture/*.md`
- Research process docs:
  `docs/research-workflow.md`
  `docs/research-artifacts.md`

### Data And Machine Outputs

- Raw provider payloads:
  `.data/alpaca/...`
- Normalized market data:
  `.data/market_data/bars/<instrument>/<timeframe>/<market>/<session>/*.jsonl`
- Canonical backtest summaries:
  `.data/backtests/minimal/<strategy>/<instrument>_<timeframe>_<start>_<end>.json`
- Canonical cost-stress summaries:
  `.data/backtests/cost-stress/<strategy>/<instrument>_<timeframe>_<start>_<end>.json`
- Validation artifacts:
  `.data/validation/<topic>/*.json`

## Keep Only Canonical Outputs

The canonical machine outputs are:

- one summary JSON per strategy run
- one cost-stress JSON per stress run
- one validation folder per validation topic

Do not keep extra copies of the same result under issue folders, study folders,
or root-level ad hoc filenames.

## Naming Rules

Use full strategy slugs in machine-facing names.

Examples:

- `spy-opening-range-breakout-trend-hold-midpoint-stop-max-1`
- `spy-opening-range-breakout-trend-hold-atr-trail-1-5-max-1`

Use prose abbreviations only in human-readable text.

Examples:

- `ORB`
- `VWAP`

## Document Types

Keep narrative research docs limited to these types:

### Thesis Note

Use for:

- the strategy idea
- the baseline rules to test
- the reason the edge may exist
- the kill criteria

### Baseline Note

Use for:

- one clean baseline result
- exact run assumptions
- the baseline verdict

### Comparison Note

Use for:

- one baseline versus one or more closely related variants
- one validation pass
- one bug-fix recheck

### Decision Note

Use for:

- final family-level verdict
- paper-trading handoff verdict
- permanent keep/reject decision

## Deletion Rule

Delete an artifact when it is no longer needed to:

- run the active workflow
- understand the current active strategy family
- preserve one canonical result
- preserve one final decision

Do not keep old exploratory clutter just because it exists.

## Working Rule

Before creating any new file, decide:

1. Is this a thesis note, baseline note, comparison note, or decision note?
2. Is this canonical machine output or temporary scratch output?
3. If it is temporary, should it exist at all after the result is recorded?

If the answer is unclear, do not keep the file.
