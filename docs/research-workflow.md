# Strategy Research Workflow

This document defines the standard workflow for researching, validating, and
either rejecting or advancing a strategy candidate toward paper trading.

## Goal

The goal is to answer one question clearly:

```text
Does this strategy family show a durable cost-adjusted edge that is strong
enough to justify paper trading?
```

If the answer is no, reject the family and move on.

## Core Rules

- Start from one clean baseline thesis.
- Test one material change at a time.
- Do not stack filters by default.
- Use costed results for decisions, not gross-only results.
- Keep long and short results separate when both sides are traded.
- Preserve exact run assumptions: date window, session, cost model, and sizing.
- Every run must end with an explicit decision: `keep`, `reject`,
  `diagnostic-only`, `blocked`, or `paper-candidate-after-more-validation`.

## Standard Artifact Map

Use these paths consistently.

### Inputs

- Strategy notes: `docs/research/*.md`
- Process and architecture docs:
  `docs/architecture/*.md`, `docs/backtesting.md`, `docs/market-data.md`
- Raw provider pages: `.data/alpaca/...`
- Normalized bar cache:
  `.data/market_data/bars/<instrument>/<timeframe>/<market>/<session>/*.jsonl`

### Outputs

- Backtest summary:
  `.data/backtests/minimal/<strategy>/<instrument>_<timeframe>_<start>_<end>.json`
- Cost-stress summary:
  `.data/backtests/cost-stress/<strategy>/<instrument>_<timeframe>_<start>_<end>.json`
- Validation artifact:
  `.data/validation/<topic>/*.json`
- Narrative result note:
  `docs/research/*.md`

## Naming Rules

Use this naming model:

- `strategy_name`: full runnable strategy slug
- `family_name`: strategy family slug when the strategy class exposes one
- `variant_name`: narrower branch or variant slug

Examples:

- family: `spy-opening-range-breakout-trend-hold`
- variant: `orb-midpoint-stop-max-1`
- runnable strategy: `spy-opening-range-breakout-trend-hold-midpoint-stop-max-1`

Use full strategy slugs in machine artifact paths. Reserve shorthand like `ORB`
or `VWAP` for prose only.

## Workflow Stages

### 0. Thesis Intake

Before coding, write a short thesis note in `docs/research/`.

Required inputs:

- strategy family name
- instrument, timeframe, market, and session
- exact market behavior being targeted
- why the edge should exist
- intended side: long-only, short-only, or long/short
- known failure mode
- kill criteria

Required output:

- one research note that states the hypothesis and the first baseline to test

Minimum structure:

```text
Hypothesis
Instrument / timeframe / session
Baseline rules to test first
Why this may work
Why this may fail
Kill criteria
Next implementation step
```

### 1. Data Readiness

Confirm that the required historical data exists before drawing any conclusion.

Required inputs:

- symbol
- timeframe
- start date
- end date
- market
- session

Required outputs:

- raw provider cache under `.data/alpaca/...`
- normalized bars under `.data/market_data/...`

Required checks:

- the requested window is actually covered
- the session filter matches the thesis
- the bar timeframe matches the strategy rules
- provider assumptions are documented

Stop here if data coverage is incomplete.

### 2. Baseline Definition

Implement the cleanest version of the strategy thesis before filters.

Required inputs:

- entry rules
- exit rules
- stop logic
- allowed entry hours
- forced flat rules
- trade side(s)
- sizing convention
- base cost model

Required outputs:

- strategy implementation
- a reproducible strategy name
- a baseline research note

Rules:

- the baseline should be runnable through the normal research surface
- avoid encoding optimization choices that belong to later filter tests

### 3. Baseline Backtest

Run the baseline on the local normalized cache.

Required outputs:

- minimal summary JSON
- cost-stress JSON when costs matter for the thesis
- note section that records the exact run window and assumptions

At minimum, record:

- `strategy_name`
- `variant_name`
- `trades`
- `long_trades`
- `short_trades`
- `gross_pnl`
- `costed_pnl`
- `profit_factor`
- `expectancy_per_trade`
- `max_drawdown`
- `worst_rolling_3_month`
- `worst_rolling_6_month`
- concentration metrics

The JSON file is the source of truth.

### 4. Variant Or Filter Test

Each experiment should answer one question.

Required inputs:

- one baseline
- one changed assumption
- one reason for the change

Required outputs:

- one variant run
- a direct baseline-versus-variant comparison
- one label:
  `keep`, `reject`, or `diagnostic-only`

Rules:

- one material change per test
- no silent stacking of previous filters
- if a filter helps only by collapsing the sample, label it
  `diagnostic-only` or `reject`

### 5. Robustness Review

This stage decides whether a variant is merely interesting or actually
promising.

Required checks:

- costed expectancy
- base-cost profit factor
- 2 bps slippage stress
- 3 bps slippage stress
- maximum drawdown
- worst rolling 3-month and 6-month windows
- long/short split
- trade-count sufficiency
- concentration risk

Use explicit sample-size rules for the active research cycle and write them into
the thesis or decision note before testing variants.

### 6. Decision

Every strategy family or cycle ends with one explicit decision note.

Allowed decisions:

- `keep`
- `reject`
- `diagnostic-only`
- `blocked`
- `paper-candidate-after-more-validation`

Every decision note must state:

- what was tested
- what passed
- what failed
- what remains unknown
- the next action

Use this result block format:

```text
## Result

Status:
Decision:

Summary:
- Window:
- Trades:
- Long trades:
- Short trades:
- Costed PnL:
- Profit factor:
- Expectancy:
- Max DD:
- Worst 6mo:
- Notes:
- Next action:
```

### 7. Expanded Validation Before Paper Trading

No strategy should move to paper trading based only on the current one-year
window.

A candidate can move forward only after expanded validation passes.

Minimum gates:

- tested on at least 5 years of data
- average trades per year is still adequate
- total sample is large enough to matter
- positive costed expectancy
- base-cost profit factor is acceptable
- 2 bps stress still passes
- no concentration blow-up
- no catastrophic rolling window
- out-of-sample behavior is acceptable
- no future-looking labels are used for entry logic

If expanded validation is blocked by data, the correct status is `blocked`, not
`approved later`.

### 8. Paper-Trading Handoff

Only after expanded validation passes should the candidate receive a
paper-trading handoff note.

That handoff should freeze:

- entry rules
- exit rules
- stop rules
- parameter values
- trading hours
- session assumptions
- cost assumptions used in research
- known failure modes
- explicit reasons the strategy may still fail in live conditions

## GitHub Issue Workflow

GitHub issues are a good fit here as long as they mirror the research cycle
instead of replacing it.

Recommended structure:

- one parent issue per strategy family or research cycle
- one child issue per baseline or single-filter experiment
- one closing issue for the final family decision

Suggested issue fields:

- thesis
- baseline
- change being tested
- required inputs
- expected outputs
- acceptance / pause / kill criteria
- result
- next action

Good issue titles:

- `Research: SPY ORB baseline`
- `Research: SPY ORB break-even exit variant`
- `Research: SPY ORB expanded validation`
- `Decision: SPY ORB paper-trading candidate`

Keep issues tightly scoped:

- one issue for one baseline
- one issue for one variant question
- one issue for one final family decision
