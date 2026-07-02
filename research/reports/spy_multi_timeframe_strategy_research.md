# SPY Multi-Timeframe Strategy Research Report

*Instrument: SPY · Timeframes: daily (2016→2026), 1-hour / 15-minute / 4-hour resample (2025→2026) · Account: $2,000 IBKR Reg T (50% initial / 25% maintenance) · Shares only · Overnight & multi-day holds allowed · Engine: existing `trade_vectorbt` (vectorbt 1.0)*

All figures are **net of costs unless labelled "gross"**, on **clean data**, computed by the reusable swing harness in `research/lib/`. This study follows the prior [SPY 5-minute intraday report](./spy_5min_intraday_strategy_research.md), whose closing recommendation was explicit: *the overnight drift held ~all of SPY's return, so an overnight / swing hold changes the problem far more than any intraday tweak.* This report tests that.

---

## 1. Executive Summary

**Can a realistic SPY *shares* strategy plausibly target 20–30% annualized after costs, slippage, margin, and small-account constraints? Only in a favorable regime, and only with ~2× leverage — it is not robust across a full market cycle.** The honest answer is more nuanced than the intraday "no", because relaxing the intraday-only mandate removes the two constraints that killed the intraday study, but the target still fails the robustness bar.

- **What swing unlocks.** Holding overnight/multi-day means trades are *not* day-trades, so the **Pattern-Day-Trader rule no longer applies** — a sub-$25k account can actually use its Reg-T **2× buying power**. That is the single biggest change from the intraday study, which was capped at ~1× by PDT.
- **The benchmark is brutal.** Over the full **2016→2026 decade** (which includes the 2018 Q4 selloff, the 2020 COVID crash, and the 2022 bear), SPY buy & hold returned **+13.3% annualized** (Sharpe 0.80) but with a **−34% max drawdown**. In the **2025→2026 focus window** it returned **+17.8%** (Sharpe 1.01, −19% DD). No simple timing rule we tested beat buy & hold on *return* over the decade — the market-structure analysis explains why (below).
- **The only path to 20–30% is leverage, and naive leverage self-destructs.** A 2× buy & hold hits ~+20–30% annualized, but its −34% underlying drawdown **breaches the Reg-T 25% maintenance level (a >33.3% underlying drop triggers a margin call at 2×)** — i.e. it gets liquidated in the next real bear. 2× buy & hold is a coin flip on ruin, not a strategy.
- **The one defensible edge is drawdown control, not excess return.** A **Donchian breakout** (and the classic **200-day trend filter**) keep the *underlying* drawdown well under the 33% margin-call threshold (−11% and −22% respectively), so **2× is survivable**. But they deliver only **~8–9% unlevered / ~10–13% at 2×** over the decade — comfortably short of 20–30%.
- **20–30% appears only in the bull.** In 2025→2026, a 2× trend-filtered long (or 2× buy & hold) does reach ~27–30%. But the per-year walk-forward shows this is **regime luck**: the same rules earned +1.7% in 2024 and −15% in 2022. Ranking on the focus-window number alone would be textbook overfitting.

**Recommendation:** Do not represent 20–30% as an achievable *robust* target for SPY shares on a $2,000 account. The realistic, survivable ceiling is a **2× drawdown-controlled long (Donchian / 200-day trend) at roughly low-to-mid-teens annualized** — a real, cost-immune, PDT-legal edge, but not the stated goal. 20–30% is only a *favorable-regime* outcome and comes with genuine margin-call risk if the regime turns.

---

## 2. Repo Review

Reused the existing active path — `trade_data` store → `trade_vectorbt` adapter/runner — end-to-end, and added a thin, tested **swing** research layer alongside the intraday one (kept separate so neither regresses).

| Layer | Reused | Where |
|---|---|---|
| Data fetch (Alpaca → normalized JSONL cache) | `market-data fetch` CLI, `AlpacaHistoricalBarsSource` | `apps/research`, `packages/trade_data` |
| Bars → OHLCV DataFrame | `to_ohlcv_dataframe` (UTC index, de-dup) | `packages/trade_vectorbt/adapter.py` |
| Portfolio simulation | `run_vectorbt_backtest` (`Portfolio.from_signals`) | `packages/trade_vectorbt/runner.py` |

New research code (all under `research/`, importable + unit-tested):

- `research/lib/swing_data.py` — generic multi-timeframe loader (session-aware), **session-aware resampler** (never spans the overnight gap), **jump-based corruption cleaner** (safe over a decade of genuine price trend), chronological split, period restriction.
- `research/lib/swing_backtest.py` — swing harness: overnight/multi-day holds, IBKR per-share commissions → vectorbt fraction, cents/share slippage, Reg-T sizing, **timeframe-agnostic** annualization / drawdown-duration / holding-time, daily-return-based Sharpe/Sortino for cross-timeframe parity.
- `research/lib/swing_strategies.py` — no-lookahead swing generators (buy & hold, SMA trend, MA cross, Connors RSI(2), Donchian, dip-buy, overnight-hold).
- `research/validate_swing_data.py`, `research/swing_market_structure.py`, `research/run_swing_experiments.py` — the three runnable stages.

**Engine caveat (carried forward):** vectorbt's `Portfolio.from_signals` fills at the signal bar's close. Every indicator-based signal is **shifted forward one bar** (decide after this close, execute next bar) to remove same-bar lookahead. Absolute PnL is therefore indicative; promising ideas should be re-run on the internal event-driven engine for exact next-bar-open fills.

---

## 3. Data Quality Review

`research/results/swing_data_quality.json` (run `research/validate_swing_data.py`). Fetched fresh from Alpaca (SIP, `adjustment=raw`).

| Timeframe | Bars | Trade days | Range (market-local) | Dupes | OHLC violations | Corrupt days |
|---|---|---|---|---|---|---|
| **1Day** | 2,638 | 2,638 | 2016-01-04 → 2026-07-01 | 0 | 0 / 0 | **0** |
| **1Hour** | 2,244 | 374 | 2025-01-02 → 2026-07-01 | 0 | 0 / 0 | **0** |
| **15Min** | 9,724 | 374 | 2025-01-02 → 2026-07-01 | 0 | 0 / 0 | **0** |

- **Timezone:** stored UTC, converted to America/New_York for all session/date logic. Daily bars live in the `all` session partition (their midnight-ET timestamp is outside RTH); intraday in `regular`.
- **Schema:** `open, high, low, close, volume` present and numeric on every frame. Intraday coverage is uniform (1H = 6 bars/day, 15Min = 26 bars/day; no short/gap days in the window).
- **Corruption screen.** The intraday study found a corrupted 5-minute segment (June 2026 printed SPY at ~$100). The **freshly fetched daily/1H/15Min bars do not carry it** (0 flagged). The prior level-based cleaner would *false-flag* the legitimate 2016→2026 trend (SPY genuinely runs $183→$760), so this track uses a **jump-based cleaner** instead: it flags impossible close-to-close moves (>35%; SPY's worst real day here is −10.8%) and local spikes vs a centered rolling median. This is a whole-history cleaning pass — no lookahead reaches the strategies.
- **`adjustment=raw` caveat.** Raw prices exclude dividends (~1.2%/yr for SPY), so buy & hold *total* return is understated by roughly that much — it does not change any conclusion.
- **Sample honesty.** The daily set is ~10.5 years across **multiple regimes** (a real strength vs the intraday study's single year). The 1H/15Min set is ~18 months (one bull); intraday conclusions are directional.

---

## 4. Timeframes Tested

| Timeframe | Source | Window | Used for |
|---|---|---|---|
| **Daily (1Day)** | Alpaca 1Day | 2016→2026 | Primary — trend, momentum, mean-reversion, breakout, dip-buy; full-cycle robustness |
| **1-Hour** | Alpaca 1Hour | 2025→2026 | Intraday structure, resample base |
| **4-Hour** | resampled from 1H | 2025→2026 | Session-aware coarse timeframe (2 bars/day) |
| **15-Min** | Alpaca 15Min | 2025→2026 | Overnight-hold isolation, overnight/intraday decomposition |

Daily carries the weight because it is the only timeframe with enough history to separate a robust edge from a regime artifact — the central requirement of the goal.

---

## 5. Market Structure Analysis

`research/results/swing_market_structure.json`, charts in `research/charts/`.

**Return by regime (daily close-to-close):**

| Window | Ann. return | Ann. vol | Sharpe | Max DD | % up days |
|---|---|---|---|---|---|
| Full 2016→2026 | **+14.1%** | 17.6% | 0.80 | **−34.2%** | 55.0% |
| Focus 2025→2026 | **+18.0%** | 17.9% | 1.01 | −19.0% | 56.0% |

**Trend vs mean-reversion — variance ratios VR(q)** (VR>1 trending, <1 mean-reverting):

| horizon | 2d | 5d | 10d | 20d |
|---|---|---|---|---|
| Full | 0.88 | 0.87 | 0.84 | 0.83 |
| Focus | 0.88 | 0.78 | 0.70 | 0.73 |

→ **SPY daily is mean-*reverting* at every horizon** (all VR<1; lag-1 autocorrelation −0.12). This is the key structural fact: **trend-following/momentum fights the statistical grain**, which is exactly why every MA/trend rule *lagged* buy & hold on return (they buy strength that tends to fade and sell weakness that tends to bounce). Yet the market has a large positive drift, so the profitable response to mean-reversion is *buying dips*, not shorting strength.

**The drift rewards holding, not trading (forward return by hold length, full history):**

| hold | 1d | 3d | 5d | 10d | 20d | 60d |
|---|---|---|---|---|---|---|
| mean | +0.06% | +0.17% | +0.28% | +0.56% | +1.14% | **+3.35%** |
| % positive | 55% | 60% | 61% | 65% | 69% | **77%** |

→ The longer you hold, the higher the win rate and expectancy — the mathematical signature of a drift-dominated instrument. This is *the* reason buy & hold is so hard to beat and why any strategy that sits in cash (low exposure) sacrifices return.

**Mean-reversion is real but small (next-day return after N down closes):**

| condition | count | next-day mean | next-day % up |
|---|---|---|---|
| unconditional | 2,637 | +5.6 bps | 55.0% |
| after 1 down | 1,182 | +9.4 bps | 56.3% |
| after 2 down | 512 | +14.9 bps | 57.6% |
| after 3 down | 217 | **+25.7 bps** | 59.0% |

→ Buying deeper dips does improve the next-day edge — but at ~26 bps and only 217 setups/decade, it is a low-exposure, low-total-return edge (confirmed by the RSI(2) backtest below).

**Overnight vs intraday (15Min, 2025→2026):** overnight +9.0% ann vs intraday open-to-close +8.5% ann — **roughly even this window**, unlike the prior 2025-H2 sample where overnight dominated. Overnight is 35% of daily variance. So "just hold overnight" is no longer a standout edge on the wider sample.

---

## 6. Hypotheses Tested

Long-only, no-lookahead (1-bar shift), round-number parameters. Primary cost scenario = **Tiered Mid ($0.0020/sh) + full-spread slippage (1¢/side)**, 1× fully invested ($2,000). `H7` runs only on 15Min (2025→2026).

**Full decade 2016→2026 (net):**

| # | Hypothesis | Ann. | Sharpe | Max DD | DD dur | PF | Trades | Exp. | 2× ann* | 2× DD | 2× margin-call | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| H0 | Buy & hold | **+13.3%** | 0.80 | −34.2% | 745d | — | 1 | 100% | +20.6% | −68% | **YES ☠** | Benchmark |
| H1 | SMA(200) trend | +9.3% | 0.84 | −22.5% | 882d | 4.07 | 30 | 76% | +12.6% | −45% | no | **KEEP** |
| H2 | SMA(50) trend | +7.0% | 0.69 | −21.6% | — | 2.10 | 80 | 72% | +8.0% | −43% | no | Reject (bull-fit) |
| H3 | MA cross 20/100 | +7.4% | 0.65 | −21.9% | — | 3.79 | 13 | 76% | +8.9% | −44% | no | Reject |
| H4 | Connors RSI(2) | +2.9% | 0.51 | −16.3% | 1399d | 1.92 | 84 | **11%** | −0.2% | −33% | no | Reject (low exposure) |
| H5 | **Donchian 20/10 breakout** | +8.2% | **0.87** | **−11.3%** | 697d | 3.17 | 49 | 58% | +10.5% | −23% | no | **KEEP (best risk-adj)** |
| H6 | Dip-buy (3 down) | +0.3% | 0.10 | −15.9% | — | 1.10 | 88 | 6% | −5.3% | −32% | no | Reject |
| H7 | Overnight hold (15m) | +7.0% | 0.65 | −17.0% | — | 1.13 | 374 | 4% | +8.1% | −34% | no | Reject (2025–26 only) |

\* 2× projection = 2×(unlevered ann) − 6% margin interest on the borrowed half; drawdown ~2×. Margin-call flag fires when the **underlying** drawdown exceeds 33.3% (equity=50% of notional, 25% maintenance).

**Focus window 2025→2026 (net):**

| # | Hypothesis | Ann. | Sharpe | Max DD | 2× ann | 2× DD | margin-call |
|---|---|---|---|---|---|---|---|
| H0 | Buy & hold | +17.8% | 1.01 | −19.0% | **+29.5%** | −38% | no (this window) |
| H2 | SMA(50) trend | +16.4% | **1.62** | **−5.3%** | **+26.9%** | −11% | no |
| H3 | MA cross 20/100 | +12.3% | 1.29 | −5.1% | +18.5% | −10% | no |
| H5 | Donchian 20/10 | +8.6% | 0.95 | −8.2% | +11.1% | −16% | no |

**Reading the two tables together is the whole story:** the strategies that look like 20–30% engines in the bull (2× B&H, 2× SMA-50) are precisely the ones whose full-cycle numbers collapse or whose leverage is fatal.

---

## 7. Best Candidate — H5 Donchian Breakout (with H1 SMA-200 as the trend-filter alternative)

No candidate reaches 20–30% robustly. The **most defensible** strategy is the one with the best *risk-adjusted, full-cycle, leverage-survivable* profile — the **Donchian 20/10 breakout**.

**Rule (fully specified):**
- **Entry:** close makes a new **20-bar high** (channel built from *prior* bars only). Executed next bar (no lookahead).
- **Exit:** close makes a new **10-bar low**.
- **Sizing:** long-only; ≤ **5 shares** at 1× (ref ~$430 over the decade), ≤ 10 at 2× under Reg T. Impossible sizes rejected by the harness.
- **No-trade:** flat whenever neither channel is triggered (exposure ~58%).

**Full-decade metrics (2016→2026, Tiered Mid + full-spread, 1×):**

| Metric | Value | Metric | Value |
|---|---|---|---|
| Annualized | **+8.2%** | Total return | +129.6% |
| Sharpe | **0.87** (best) | Sortino | 0.83 |
| Calmar | **0.73** (best) | Max drawdown | **−11.3%** (best) |
| Max DD duration | 697 days | Exposure | 57.9% |
| Trades | 49 (≈0.4/mo) | Profit factor | 3.17 |
| Win rate | 55.1% | Avg hold | 45 days |
| 2× ann (proj.) | +10.5% | 2× max DD | −22.7% (no margin-call) |

**Why this one over buy & hold or SMA-50:** it earns two-thirds of buy & hold's return with **one-third of the drawdown**, and — critically — its underlying drawdown stays far under the 33% margin-call line, so **2× is survivable** where 2× buy & hold is not. SMA-200 (H1) is the close alternative: higher return (+9.3%) and near-identical Sharpe, but a deeper −22% drawdown and a very long 882-day underwater stretch.

**Cost & slippage sensitivity — annualized net %, full grid (`research/results/swing_experiments.json`):** for these low-frequency daily strategies (≈0.4 trades/month, ~5 shares) commissions are a **rounding error**. Donchian erodes from **+8.28%** (no cost) to **+8.22%** at the worst corner (**Fixed $0.0050 + 2¢ stress**) — a total of **~0.06 pp** across the entire grid. **Every candidate survives Fixed + stress comfortably**, clearing the goal's "must survive at least Tiered Mid, preferably Tiered High/Fixed" bar with enormous margin. Per-share commission is simply irrelevant at SPY's price and this trade frequency; the binding constraints are drift, regime, and leverage — not costs.

---

## 8. Robustness Review

**Per-calendar-year walk-forward (fixed rules, no refit) — annualized %:**

| Year | Regime | Buy & hold | SMA-50 | Donchian | 2× B&H margin-call? |
|---|---|---|---|---|---|
| 2016 | grind up | +11.3 | +2.9 | +11.5 | no |
| 2017 | low-vol bull | +18.9 | +5.6 | +7.5 | no |
| 2018 | Q4 selloff | −7.0 | −1.2 | −3.8 | no |
| 2019 | bull | +28.8 | +1.8 | +9.5 | no |
| 2020 | COVID crash+recovery | +15.3 | +20.3 | +19.7 | **YES (−34% DD)** |
| 2021 | bull | +29.1 | +12.8 | +9.2 | no |
| 2022 | bear | −20.2 | −15.3 | **0.0** | no (−25% DD, close) |
| 2023 | recovery | +25.2 | +17.6 | +9.9 | no |
| 2024 | grind up | +24.1 | **+1.7** | +7.8 | no |
| 2025 | vol + recovery | +16.7 | +16.2 | +4.8 | no |
| 2026* | bull | +19.6 | +18.9 | +15.6 | no |

\*partial year. → **Donchian is positive or flat in 10 of 11 years** (only −3.8% in 2018) — the hallmark of a genuine, if modest, edge. **SMA-50 whipsaws badly in trending-up years** (2017, 2019, 2021, 2024) and is negative in 2018/2022; its stellar 2025–26 Sharpe is regime-specific. **Buy & hold's two >20% drawdown years (2020, 2022) are exactly where 2× buy & hold margin-calls** — the ruin scenario is not hypothetical.

**Chronological 70/30 train/test (split 2023-05-04):**

| Strategy | Train ann. / Sharpe | Test ann. / Sharpe | Read |
|---|---|---|---|
| **Donchian 20/10** | +6.4% / 0.67 | +11.1% / 1.27 | positive both ✅ |
| SMA-200 | +6.9% / 0.66 | +9.6% / 0.94 | positive both ✅ |
| SMA-50 | +3.5% / 0.37 | +11.8% / 1.20 | positive both, weak train |
| Connors RSI(2) | +1.4% / 0.26 | +4.9% / 1.01 | positive but tiny |

→ The trend/breakout edge is **stable in sign** out-of-sample, but **modest in size** — nowhere near 20–30% unlevered.

**Residual risks even for the keeper:**
- **Long time under water.** Even Donchian spent ~697 days (≈2 years) below a prior peak over the decade; SMA-200 ~882 days. A real account would endure multi-year flat stretches.
- **Mean-reversion headwind.** Breakout/trend rules fight SPY's VR<1 structure; the edge comes from the drift and from cutting tails, not from timing skill.
- **Leverage is doing the heavy lifting.** Every 20-ish% figure in this report is a *levered* projection; the unlevered edge is high-single-digits. Real 2× adds margin interest, gap risk, and the ever-present bear-market margin-call tail.
- **Fill model.** Vectorbt fills at bar close (1-bar-shifted); confirm on the internal event-driven engine before any capital.

---

## 9. Small-Account & Margin Reality (why 20–30% is not *robust*)

- **Swing removes the PDT block.** This is the real gain over the intraday study: positions held overnight are not day-trades, so a $2,000 (sub-$25k) account can legally use **2× Reg-T buying power**. Leverage is finally on the table.
- **But 2× is only safe with drawdown control.** A fixed-fraction 2× long is margin-called when the underlying falls **>33.3%**. Buy & hold breached that in 2020 (−34%) and came close in 2022 (−25%). So **2× buy & hold ≈ ruin**; only strategies that cap underlying drawdown under ~25–30% (Donchian −11%, SMA-200 −22%) can wear 2× through a cycle.
- **The survivable 2× ceiling is ~low-to-mid-teens, not 20–30%.** Donchian 2× ≈ **+10.5%**, SMA-200 2× ≈ **+12.6%** annualized over the decade — real and PDT-legal, but short of the target. 20–30% shows up only in the 2025–26 bull.
- **Discreteness drag.** $2,000 buys ~**5 shares** of SPY at 1× (~10 at 2×). Coarse sizing adds slippage-to-plan the fractional backtest understates, and makes stops/scaling blunt.

Together: 20–30% net is **structurally a favorable-regime outcome** for SPY shares on this account, not a robust target — independent of signal cleverness.

---

## 10. Final Recommendation

1. **Do not treat 20–30% as an achievable robust target for SPY shares on $2,000.** Over a full cycle the survivable ceiling is low-to-mid-teens (2× drawdown-controlled long). The 20–30% seen in 2025–26 is regime-dependent and carries margin-call tail risk.
2. **If deploying anything, deploy the Donchian breakout (or SMA-200 trend) at ≤2×** as a *drawdown-controlled, cost-immune, PDT-legal* long — not as a 20–30% engine. Promote it to the **internal event-driven engine** for realistic fills/costs before capital.
3. **Prefer "buy the dips + hold" over "trend-follow" if chasing return.** The data says SPY is mean-reverting with strong drift: the profitable responses are *holding* (drift) and *buying weakness* (reversion), not buying breakouts. A dip-accumulation-in-uptrend variant with higher exposure is the most promising *unexplored* direction.
4. **Respect the leverage tail.** Any path to 20–30% runs through 2×; size it so a 30%+ SPY drop cannot force liquidation (keep effective leverage below the maintenance-breach point, or hold a cash buffer).
5. **Extend the sample and re-confirm.** The daily decade is solid; re-fetch multi-year 1H/15Min before trusting any intraday/overnight conclusion, and re-validate on the internal engine.

---

## 11. Files Changed

**New — swing research layer (importable, tested):**
- `research/lib/swing_data.py` — multi-timeframe loader, session-aware resampler, jump-based corruption cleaner, split/restrict helpers.
- `research/lib/swing_backtest.py` — swing harness (overnight/multi-day holds, IBKR costs, Reg-T sizing, timeframe-agnostic metrics, `underwater_duration_days`).
- `research/lib/swing_strategies.py` — no-lookahead swing signal generators.
- `research/validate_swing_data.py`, `research/swing_market_structure.py`, `research/run_swing_experiments.py` — runnable stages.

**New — tests:**
- `tests/research/test_swing_lib.py` — 15 tests: resample never spans overnight + OHLC aggregation, corruption detection (spike/jump caught, legitimate trend ignored), chronological split, period restriction, no-lookahead shift, buy&hold/overnight-hold discipline, cost monotonicity, impossible-size rejection, underwater duration.

**New — outputs:** `research/results/swing_*.json|csv`, `research/charts/buy_hold_*.png`, this report.

**Unchanged:** all existing engine/package code reused, not modified. The intraday research track (`research/lib/backtest.py`, `strategies.py`, `data_access.py`, etc.) is untouched.

**Quality gates:** `uv run pytest` → **100 passed**; `uv run ruff check` / `format --check` clean on `research`+`tests/research`; `uv run pyright` adds **0 new errors** (research/ scripts are outside the pyright `include` set, consistent with the existing intraday track; the only pre-existing errors are in `apps/research/chart_viewer/generate.py`).

*(Note: `AGENTS.md` shows as modified in git status from before this task — unrelated.)*

---

## 12. Commands to Rerun

```bash
# from repo root
set -a; source .env; set +a          # only needed to (re)fetch data; analysis uses the cache
uv sync

# 0. (Re)fetch data — daily decade + recent 1H/15Min (raw Alpaca stays gitignored)
uv run python -m trade_research_app market-data fetch --symbol SPY --timeframe 1Day  --start 2007-01-01 --end 2026-07-02 --session all
uv run python -m trade_research_app market-data fetch --symbol SPY --timeframe 1Hour --start 2025-01-01 --end 2026-07-02 --session regular
uv run python -m trade_research_app market-data fetch --symbol SPY --timeframe 15Min --start 2025-01-01 --end 2026-07-02 --session regular

# 1. Data quality  -> research/results/swing_data_quality.json
uv run python research/validate_swing_data.py

# 2. Market structure -> research/results/swing_market_structure.json + charts
uv run python research/swing_market_structure.py

# 3. All hypotheses + cost grid + train/test + per-year walk-forward
uv run python research/run_swing_experiments.py

# Tests + quality gates
uv run pytest tests/research -q
uv run ruff check research tests/research && uv run ruff format --check research tests/research
```

---

## 13. Output Locations

| Artifact | Path |
|---|---|
| Data-quality report | `research/results/swing_data_quality.json` |
| Market-structure stats | `research/results/swing_market_structure.json` |
| All experiment runs (machine-readable) | `research/results/swing_experiments.json` |
| Hypothesis summary table (flat) | `research/results/swing_experiments.csv` |
| Charts | `research/charts/buy_hold_equity_drawdown.png`, `research/charts/buy_hold_by_year.png` |
| This report | `research/reports/spy_multi_timeframe_strategy_research.md` |

*Raw Alpaca data and the `.data/` cache remain gitignored; every research output above is a sanitized aggregate containing no raw vendor data. Nothing in this report is financial advice.*
