# Backtest Architecture

The backtest system runs a single strategy over normalized OHLCV bars and
produces a public-safe summary with trade metrics, regime breakdowns, and
execution-cost stress analysis. It is split into two package trees:

  - **`apps/research/src/trade_research_app/backtest/`** — the runner, the
    bar-loop engine, fill simulation, per-trade diagnostics, post-trade
    enrichment, summary assembly, and cost-stress grid.
  - **`packages/trade_analytics/`** — shared analytics (trade metrics,
    breakdowns, session-regime tagging) that the backtest consumes but which
    are also usable by paper/live execution and reconciliation.

---

## File Map and Responsibilities

### Application-level: `backtest/` package

| File | Purpose |
|---|---|
| `__init__.py` | Public re-export shim so callers import from `trade_research_app.backtest`. Re-exports `run_minimal_backtest`, all records, `session_regime_tags`, and stress-report entry points. |
| `runner.py` | Thin shim (13 lines) re-exporting `run_minimal_backtest` from `engine.py` so old import paths keep working. New code should import from `engine` directly. |
| `engine.py` | Bar-by-bar loop (392 lines). Owns `_BacktestRunner` (mutable run state: position, PnL, pending orders) and the public `run_minimal_backtest` entry point. Loads bars from cache, iterates each bar, fills pending intents, updates MFE/MAE, asks the strategy for a decision, translates approved decisions into fills via `_handle_fill`, then delegates to enrichment and summary. |
| `fill_model.py` | Pure fill-accounting functions (206 lines). `simulate_next_open_fill` applies slippage/commission to a reference price. `apply_fill` updates position/entry-price/realized-PnL tuples. `closed_trade_pnl` calculates the PnL when a fill closes a trade. `call_on_entry` asks the strategy for its `OpenTradeDiagnostics` (initial stop price for R multiples) via a protocol seam. `risk_outcome_for_action` / `order_side_for_action` translate strategy decisions to broker-neutral order concepts. |
| `diagnostics.py` | `TradeDiagnosticsTracker` (113 lines) encapsulates the 14 in-flight state variables the bar loop previously carried as locals. Tracks entered-at, entry-side/price, commissions, MFE/MAE, and initial stop. `on_open` resets for a new trade, `update_mfe_mae` advances from each completed bar's high/low, `diagnostics` produces the typed `_TradeDiagnostics` dict at close time. |
| `enrichment.py` | Post-trade enrichment pipeline (126 lines). `enrich_closed_trades` chains `with_post_exit_max_favorable_pnl`, `_with_regime_tags`, `_with_signal_bar_quality_tags`, and `with_macro_event_tags` in order. Each step returns a new list with additional fields populated, so the enrichment explains the run without becoming implicit strategy input. Macro event tagging depends on the app-specific `macro_events` module and therefore lives here, not in `trade_analytics`. |
| `summary.py` | Summary assembly (273 lines). `build_summary` receives engine state plus the enriched trade list and calls into `trade_analytics` for all metrics and breakdowns. Constructs the immutable `BacktestSummary` record, writes the JSON artifact to disk when `output_path` is set. |
| `records.py` | Pure dataclasses (365 lines): `SimulatedFill`, `BacktestCostModel`, `CostStressScenario`, `CostStressRow`, `CostStressReport`, `BacktestSummary`. No execution logic. `BacktestSummary` has ~50 fields covering PnL totals, trade quality, drawdown, R-multiple diagnostics, and each breakdown dimension. |
| `cost_stress.py` | Execution-cost stress grid (169 lines). `default_cost_stress_scenarios` returns a tuple of 11 scenarios sweeping slippage (0–5 bps) and commission assumptions (IBKR fixed/tiered). `run_cost_stress_report` runs `run_minimal_backtest` once per scenario and builds a compact `CostStressReport` keyed by scenario name. |
| `cli_wiring.py` | Deterministic ID generation and reason-string parsing (79 lines). `strategy_run_id` produces a stable identifier from request + strategy name. `bar_close_time` calculates when a close-based signal becomes observable. `explicit_decision_reference_price` decodes `rule@price` from strategy reasons for same-bar fills. `strategy_family_name` / `strategy_variant_name` extract report labels. |

### Shared packages: `trade_analytics/`

| File | Purpose |
|---|---|
| `metrics.py` | Owns the `ClosedTrade` record (the primary trade representation across the systems) and pure aggregation functions: `_trade_metrics` (win/loss/distribution), `_compute_mfe_mae_r_diagnostics` (R multiple derivation), `_max_drawdown`, `_max_drawdown_duration_trades`, `_max_consecutive_losing_trades`, `_worst_rolling_pnl`, `_contribution_pct_of_total_pnl`. Depends only on `trade_core` for `OrderSide`. (413 lines) |
| `breakdowns.py` | Every `*_breakdown` function that groups closed trades into report buckets. `_closed_trade_breakdown` (by exit date), `_year_breakdown`, `_month_breakdown`, `_weekday_breakdown`, `_time_of_day_breakdown`, `_side_breakdown`, `_exit_reason_breakdown`, `_holding_time_breakdown`, `_regime_breakdown`, `_macro_event_day_breakdown`, `_macro_event_type_breakdown`, `_trade_contribution_breakdown`, `_day_contribution_breakdown`, `_chronological_split_breakdown`, `_rolling_window_breakdown`. The generic `BreakdownDimension` + `breakdown_by` collapsed the repeated "group by one accessor" pattern: exit-reason, holding-time, and each regime breakdown are now thin wrappers. Adding a new dimension is a one-line `BreakdownDimension` constant. (484 lines) |
| `session_regimes.py` | `SessionRegimeTags` dataclass and `session_regime_tags` function that derive gap/or/trend/rvol buckets from normalized OHLCV bars per market-local date. `_with_regime_tags` and `_with_signal_bar_quality_tags` are enrichment helpers consumed by the backtest's enrichment pipeline. Individual bucket functions: `_gap_bucket`, `_opening_range_state`, `_opening_range_pct_bucket`, `_opening_drive_return_bucket`, `_opening_drive_close_position_bucket`, `_daily_trend_state`, `_relative_volume_bucket`, `_signal_bar_quality_buckets`. (455 lines) |

### Shared packages: `trade_strategies/`

| File | Purpose |
|---|---|
| `protocols.py` | `Strategy` protocol (the minimal seam: `name` + `decide`), `StrategyWithDiagnostics` protocol (adds `on_entry` returning `OpenTradeDiagnostics`), and `StrategyDecisionContext` dataclass (runner-supplied facts). Strategies that implement `on_entry` contribute their initial stop price for R-multiple computation; those that don't get zero stop (R undefined). (107 lines) |

---

## Data Flow

```
run_minimal_backtest()
  │
  ├─ 1. Load normalized bars from LocalMarketDataStore
  ├─ 2. Create _BacktestRunner (flat state)
  ├─ 3. runner.run(bars)
  │     │
  │     └─ for each bar:
  │           ├─ Fill any pending order intent (next-bar open)
  │           ├─ Update MFE/MAE from bar high/low
  │           └─ Ask strategy: decide(bar, context)
  │                 │
  │                 ├─ DecisionAction.HOLD → skip
  │                 ├─ Action + rejected by risk gate → record risk decision
  │                 └─ Action + approved → _handle_fill
  │                       │
  │                       ├─ simulate_next_open_fill (apply slippage/commission)
  │                       ├─ closed_trade_pnl → if non-None, build ClosedTrade
  │                       ├─ Apply fill to position/entry-price/realized-PnL
  │                       ├─ call_on_entry → capture initial stop price
  │                       └─ diagnostics.on_open / on_close
  │
  ├─ 4. enrich_closed_trades(trades, bars, timezone)
  │     │
  │     ├─ with_post_exit_max_favorable_pnl
  │     ├─ _with_regime_tags (gap, OR, trend, rvol)
  │     ├─ _with_signal_bar_quality_tags
  │     └─ with_macro_event_tags
  │
  └─ 5. build_summary(..., enriched_trades, bars, strategy, cost_model)
        │
        ├─ _trade_metrics(closed_trades)   → win/loss/R/distribution
        ├─ _closed_trade_breakdown(...)     → daily PnL timeline
        ├─ _year_breakdown, _month_breakdown, etc.
        ├─ _side_breakdown(trades)          → long vs short
        ├─ _exit_reason_breakdown(trades)   → by strategy rule
        ├─ _holding_time_breakdown(trades)
        ├─ _regime_breakdown(trades, tag_name=...) → by each regime tag
        ├─ _macro_event_day/type_breakdown
        ├─ _trade/day_contribution_breakdown → concentration
        ├─ _chronological_split_breakdown
        ├─ _rolling_window_breakdown (3mo, 6mo)
        └─ Construct BacktestSummary → optionally write JSON artifact
```

The cost-stress grid uses the same flow but runs it N times (once per scenario)
and builds a compact `CostStressReport` instead of a full summary:

```
run_cost_stress_report()
  │
  └─ for each CostStressScenario:
        ├─ strategy_factory() → fresh strategy instance
        ├─ run_minimal_backtest(...)
        └─ _cost_stress_row(scenario, summary) → CostStressRow
  │
  └─ CostStressReport(strategy_name, instrument_id, timeframe, rows)
        └─ optionally write JSON artifact
```

---

## Key Design Decisions

**Engine owns no analytics.** The bar loop assembles `ClosedTrade` records with
regime fields set to sentinel values (`unknown_gap`, `unknown_opening_range`,
etc.). Enrichment fills them in after the loop completes, keeping the engine
fast and focused on fill accounting.

**Post-trade enrichment is app-level.** Regime tagging is shared in
`trade_analytics.session_regimes`, but calling it on each trade (`_with_regime_tags`
and `_with_signal_bar_quality_tags`) lives in the backtest enrichment module because
the pipeline also includes app-specific steps like `with_macro_event_tags` (which
depends on `trade_research_app.macro_events`).

**Strategy diagnostics seam.** Strategies that implement `on_entry` (via the
`StrategyWithDiagnostics` protocol) contribute their initial stop price after an
opening fill. The engine calls `call_on_entry(strategy)` via `getattr` detection
so strategies that only implement `Strategy` get a zero stop (R undefined). This
replaces any hard-coded state inspection in the engine.

**`ClosedTrade` carries every regime field.** All regime tags (gap, opening
range, trend, rvol, signal-bar quality) are fields on `ClosedTrade` rather than a
strategy-owned diagnostics map. This keeps the report JSON shape stable and means
breakdown functions (`_regime_breakdown`) can retrieve them by attribute name
without knowing which strategy produced the trade.

**Generic breakdown engine.** `BreakdownDimension` + `breakdown_by` centralize
the "group one accessor" pattern. `_exit_reason_breakdown`, `_holding_time_breakdown`,
and every `_regime_breakdown(tag_name=...)` caller are thin wrappers. Adding a new
report dimension is a `BreakdownDimension` constant and a thin wrapper (or just
a `breakdown_by` call) in `summary.py`.

**Each breakdown function is private and listed in `__all__`.** This satisfies
pyright's `reportUnusedFunction` for cross-package API functions that are
imported and used by name in `summary.py`.

**Cost-stress imports the runner lazily.** `cost_stress.py` imports
`run_minimal_backtest` inside its function body, not at module level, to avoid
a circular dependency (the runner imports records, and cost-stress imports the
runner).

---

## Verification

```
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run pyright
```
