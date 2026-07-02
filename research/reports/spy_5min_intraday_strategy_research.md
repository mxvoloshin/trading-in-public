# SPY 5-Minute Intraday Strategy Research Report

*Instrument: SPY · Timeframe: 5-minute · Account: $2,000 IBKR Reg T (50% initial / 25% maintenance) · Shares only, intraday-only, flat by EOD · Engine: existing `trade_vectorbt` (vectorbt 1.0)*

Generated on the local Alpaca SPY 5-minute cache. All figures are **net of costs unless labelled "gross"**, computed on **clean data** (a corrupted segment was quarantined — see Data Quality).

---

## 1. Executive Summary

**Can a realistic intraday SPY shares strategy plausibly target 20–30% annualized after costs, slippage, margin, and small-account constraints? No — not at any leverage a $2,000 Reg T account can legally or safely use.**

- The one strategy that survived every robustness gate — an **Opening-Range Breakout (ORB)** — earns roughly **+3.5% annualized net, unlevered** (Sharpe 1.9, max drawdown −2.2%). It is genuinely robust: positive in **all four** sequential walk-forward folds and in both train and test halves, and it barely moves across the entire commission×slippage grid.
- To reach the 20–30% target from a +3.5% edge you would need **~6–8× leverage**. Reg T caps a cash-funded account at **2× intraday** (and the $2,000 balance is far below the $25,000 Pattern-Day-Trader minimum, so *daily* margin day-trading is not even permitted). At the achievable 2×, ORB projects to roughly **+7% annualized** — well short of the goal.
- The deeper reason is structural, and the market-structure analysis makes it explicit: **SPY's return over the sample lived overnight, not intraday.** Close-to-close was +18% annualized (Sharpe 1.5), but **open-to-close was only +4.2%**. A flat-by-EOD mandate deliberately forgoes the part of the day where the money was.
- Higher-returning ideas existed on paper (an intraday z-score mean-reversion showed +5.3% net, Sharpe 2.1) but **failed validation**: zero edge in the training half and two negative walk-forward folds. Chasing its headline number would have been overfitting to one regime.

**Recommendation:** Do not deploy an intraday-only SPY shares strategy against a 20–30% target on a $2,000 account. ORB is the only defensible edge found, and it is a low-single-digit-return, low-drawdown strategy — interesting as a paper-trading / learning candidate, not a path to the stated return.

---

## 2. Repo Review

The active research path is `trade_data` → `trade_vectorbt` → the `backtest vbt` runner. This study **reused that engine end-to-end** and added a thin, tested research layer on top.

| Layer | Reused | Where |
|---|---|---|
| Data load (normalized JSONL cache, never Alpaca directly) | `LocalMarketDataStore.load_bars`, `Instrument.us_equity`, `get_market_session_config` | `packages/trade_data` |
| Bars → OHLCV DataFrame | `to_ohlcv_dataframe` (UTC index, de-dup) | `packages/trade_vectorbt/adapter.py` |
| Portfolio simulation | `run_vectorbt_backtest` (`Portfolio.from_signals`) | `packages/trade_vectorbt/runner.py` |
| Reference signals (ORB logic mirrored) | `orb_signals` and friends | `packages/trade_vectorbt/signals.py` |

New research code (all under `research/`, importable + unit-tested):

- `research/lib/data_access.py` — one load seam, corrupt-day quarantine, chronological split.
- `research/lib/strategies.py` — intraday, no-lookahead, flat-by-EOD signal generators.
- `research/lib/backtest.py` — realistic cost model (IBKR per-share → vectorbt fraction), Reg T sizing/reject, full metric set.
- `research/validate_data.py`, `research/market_structure.py`, `research/run_experiments.py` — the three runnable stages.

**Engine caveat carried forward from the repo docs:** vectorbt's `Portfolio.from_signals` fills at the **signal bar's close**. To avoid same-bar lookahead, every research signal is **shifted forward one bar** before simulation (execute next bar, not the bar you just observed). This is a vectorized approximation of the internal engine's next-bar-open fills; absolute PnL is therefore indicative, not identical to the event-driven engine. Promising ideas should be re-run there for exact fills.

---

## 3. Data Quality Review

`research/results/data_quality.json` (run `research/validate_data.py`).

| Check | Result |
|---|---|
| Bars | 19,500 across **250** trade days |
| Range (market-local) | 2025-06-30 09:30 → 2026-06-26 15:55 ET |
| Timezone | stored UTC, converted to America/New_York for all session logic |
| Schema | `open, high, low, close, volume` — all present, numeric |
| Session coverage | **every** day has exactly 78 bars (full 9:30–16:00 RTH); no short/half days in sample |
| Duplicate timestamps | 0 |
| Non-positive prices | 0 · OHLC high/low violations 0 · negative volume 0 · zero-volume bars 0 |
| Intraday gaps (missing bars mid-session) | 0 |

**Critical finding — corrupted price segment.** Ten consecutive trade dates (**2026-06-01 → 2026-06-12**) print SPY at ~$100 instead of ~$750 (daily-median $106 vs the surrounding $616–$757). This injects fake overnight jumps of **−87%** into and **+588%** out of the segment — enough to dominate any backtest. It looks like a wrong-symbol or mis-adjusted cache fetch.

These days are **quarantined** by `flag_corrupt_days` (a day whose median close deviates >50% from the global median of daily medians) before any strategy runs, leaving **240 clean trade days (~11.3 months)**. All results in this report are on the cleaned set.

**Sample-size honesty:** ~11 months / 240 sessions is a *small* sample. One year is roughly one macro regime; Sharpe and annualized figures here have wide error bars and should be read as directional, not precise.

---

## 4. Market Structure Analysis

`research/results/market_structure.json` and charts in `research/charts/`.

**Return decomposition (the key result):**

| Series | Mean/day | Annualized | Sharpe (naive) | % up |
|---|---|---|---|---|
| Close-to-close (overnight + intraday) | +7.2 bps | **+18.2%** | 1.52 | 55.2% |
| **Open-to-close (intraday only)** | +1.7 bps | **+4.2%** | — | 50.4% |
| Overnight (close→next open) | — | — | — | 41.3% of daily variance |

→ **Most of SPY's drift and directionality accrued overnight.** Intraday is close to a coin flip (50.4% up days). This is the headwind an intraday-only, flat-by-EOD strategy fights.

**5-minute return autocorrelation** (within-day, so no overnight leakage):

| lag | 1 | 2 | 3 | 6 | 12 |
|---|---|---|---|---|---|
| autocorr | −0.026 | −0.029 | −0.015 | −0.012 | +0.001 |

→ Slight **mean-reversion** at short lags, decaying to zero. Weak, but it points to mean-reversion over momentum for 5-min horizons.

**Opening range (first 30 min):** average range ≈ 39 bps. 74.6% of days break the OR high at some point and 67.5% break the OR low — **most days break both** (whipsaw). Breakout *continuation* is weak: of days that break up, only **55%** close above the OR high (48% for downside). → ORB has a small edge at best; fading is not obviously better.

**Time of day:** classic **U-shaped** volatility and volume (peaks at 9:30–10:00 and 15:30–15:55). **No** persistent directional drift by time of day — every 5-minute bucket's mean return is within ±1.5 bps and noisy. → Time-of-day "seasonality" strategies are unsupported here.

**Day of week (open-to-close):** Mon +15.7 bps, Thu −15.5 bps — interesting but almost certainly noise over ~48 weeks; not traded.

---

## 5. Hypotheses Tested

All strategies are **long-only, one direction, no-lookahead (1-bar shift), no entries in the final 10 min, force-flat at 15:55**, round-number parameters (no fine-tuning). Primary cost scenario = **Tiered Mid commission ($0.0020/sh) + full-spread slippage (1¢/side)**. Sizing: $2,000, fully invested (1×).

| # | Hypothesis | Behavior targeted | Entry | Exit | Ann. net | Sharpe | MaxDD | Trades | PF | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| H0 | Buy-open / sell-close | Intraday beta benchmark | first bar | 15:55 | +1.1% | 0.38 | −11.0% | 240 | 1.02 | **Benchmark** |
| H1 | **ORB breakout (6-bar)** | Opening-range momentum | close > OR high | < OR mid / EOD | **+3.5%** | **1.88** | **−2.2%** | 163 | 1.18 | **KEEP** |
| H2 | ORB fade | Reversion of OR break | close < OR low | > OR mid / EOD | −3.6% | −1.63 | −6.0% | 138 | 0.84 | Reject |
| H3 | RSI(14) mean-reversion | Short-lag reversion | RSI<30 | RSI>55 / EOD | +0.2% | 0.17 | −4.9% | 289 | 1.01 | Reject (no edge) |
| H4 | Z-score(20) mean-reversion | Short-lag reversion | z<−1.5 | z>0 / EOD | +5.3% | 2.07 | −4.9% | 460 | 1.14 | **Reject (fragile)** |
| H5 | MA(9/21) cross | Intraday momentum | fast>slow | fast<slow / EOD | −1.2% | −0.44 | −7.1% | 455 | 0.97 | Reject |

Notes on the rejects:
- **H2/H5** lose money net — the data (weak continuation, no trend persistence) predicted this.
- **H3** has essentially zero edge after the 1-bar no-lookahead shift (the raw same-bar RSI signal is where the apparent edge lived — a lookahead artifact).
- **H4** is the important cautionary tale — it *looks* best on the full sample but is regime-driven (see §6). Ranking on profit alone would have selected it.

---

## 6. Best Candidate — H1 Opening-Range Breakout

**Rule (fully specified):**
- **Opening range** = high/low of the first **6 bars** (9:30–10:00 ET).
- **Entry:** first bar whose close > OR high, in the window 10:00–15:45; **one entry per day**; executed next bar (no lookahead).
- **Exit:** close falls back below the OR **midpoint**, OR forced flat at **15:55**.
- **Sizing:** long-only, ≤ 5 shares at ref price $676 under Reg T (impossible sizes rejected by the harness).

**Full metrics (240 days, Tiered Mid + full-spread, 1× / unlevered):**

| Metric | Value | Metric | Value |
|---|---|---|---|
| Net profit | **+$69.90** on $2,000 | Total return | +3.50% |
| Annualized | **+3.54%** | Gross (no-cost) | +4.09% |
| Sharpe | 1.88 | Sortino | 2.65 |
| Calmar | 9.50 | Max drawdown | **−2.24%** |
| Max DD duration | 44 days | Exposure | 35.1% |
| Trades | 163 | Trades/month | 13.7 |
| Win rate | 46.6% | Profit factor | 1.18 |
| Avg win / loss | +$6.05 / −$4.49 | Expectancy | +$0.43/trade |
| Largest win / loss | +$32.64 / −$18.05 | Avg hold | 201 min |
| Best / worst day | +1.60% / −0.88% | | |

Classic breakout profile: win rate < 50% but average win > average loss (asymmetry does the work). Low exposure (35%) and shallow drawdown, hence the high Calmar.

**Cost sensitivity — annualized net %, full grid (`research/results/experiments.json`):**

| commission ↓ / slippage → | none | half-spread | full-spread | stress (2¢) |
|---|---|---|---|---|
| none | 4.14 | 3.89 | 3.64 | 3.13 |
| tiered_low ($0.0005) | 4.12 | 3.87 | 3.61 | 3.11 |
| tiered_mid ($0.0020) | 4.04 | 3.79 | 3.54 | 3.03 |
| tiered_high ($0.0035) | 3.97 | 3.71 | 3.46 | 2.96 |
| **fixed ($0.0050)** | 3.89 | 3.64 | 3.39 | **2.88** |

→ ORB **survives the worst corner (Fixed commission + 2¢ stress slippage) at +2.88%** — a total erosion of only ~1.3 percentage points across the entire grid. For SPY shares, per-share commission is a rounding error (≈0.06 bps of a $676 price); slippage matters more but the low trade frequency (13.7/mo, 201-min holds) keeps it cheap. **This clears the "must survive at least Tiered Mid, preferably Tiered High/Fixed" bar comfortably.**

---

## 7. Robustness Review

**Chronological train/test (70/30, split 2026-03-02):**

| Strategy | Train ann. | Train Sharpe/PF | Test ann. | Test Sharpe/PF | Read |
|---|---|---|---|---|---|
| **H1 ORB** | **+2.3%** | 1.35 / 1.13 | **+6.2%** | 2.81 / 1.24 | positive both halves ✅ |
| H4 z-score | **−0.1%** | 0.05 / 1.00 | +15.9% | 5.78 / 1.46 | **no edge in train ❌** |

**Walk-forward (4 sequential blocks, ~60 days each, fixed rules / no refit):**

| Fold (dates) | H1 ORB ann. / PF | H4 z-score ann. / PF |
|---|---|---|
| 1 (Jul–Sep '25) | +5.9% / 1.42 | +11.8% / 1.53 |
| 2 (Sep–Dec '25) | +4.5% / 1.21 | −0.1% / 1.00 |
| 3 (Dec–Mar '26) | +1.7% / 1.10 | −2.2% / 0.95 |
| 4 (Mar–Jun '26) | +2.6% / 1.10 | +12.8% / 1.40 |

→ **H1 is positive in every fold (PF ≥ 1.10 throughout)** — the hallmark of a small-but-real edge. **H4 is positive in only 2 of 4** and its full-sample number is carried by folds 1 and 4; it is a regime bet dressed up as a strategy. This is exactly why the research rules forbid ranking on profit alone.

**Residual risks even for H1:**
- **Sample:** one ~11-month bull regime, 240 days. The edge is real *in this sample*; it has not seen a bear market, a volatility spike, or a sideways year.
- **Fill model:** vectorbt fills at bar close (1-bar-shifted). Real ORB fills happen on the breakout tick with real spread/impact; the internal event-driven engine should confirm.
- **Magnitude:** the edge is small enough that modest degradation (a wider real spread, a worse regime) could halve it.

---

## 8. Small-Account & Margin Reality (why 20–30% is out of reach)

- **Fractional edge → leverage math.** ORB's ~+3.5% unlevered, flat-overnight, fixed-fraction profile scales roughly linearly with leverage. Target 20–30% ⇒ **~6–8× leverage**, with drawdown scaling too (−2.2% → ~−13–18%).
- **Reg T caps the account at 2× intraday** (50% initial margin). At 2×, ORB ≈ **+7% annualized, ~−4.5% DD** — still far below target.
- **Pattern-Day-Trader rule blocks it entirely.** A $2,000 balance is below the **$25,000** PDT minimum, so more than 3 day-trades / 5 business days on margin is prohibited. ORB trades ~14×/month — it **cannot be run on margin at this balance at all**; a cash account avoids PDT but then there is *no* leverage and settlement limits reuse of funds.
- **Discreteness drag:** $2,000 buys ~3 shares cash / ~5 shares at 2× of a $676 SPY — coarse position sizing that adds real slippage-to-plan the fractional backtest understates.

Together these make 20–30% net structurally implausible for intraday SPY shares on a $2,000 account, independent of how clever the signal is.

---

## 9. Final Recommendation

1. **Do not pursue the 20–30% intraday-shares target on this account.** The math (small real edge × capped leverage × PDT prohibition) does not support it. Pursuing it would require leverage the account cannot access and would invite ruinous drawdowns.
2. **ORB is the one keeper** — as a *low-return, low-drawdown, cost-robust* strategy for **paper trading and further validation**, not as a 20–30% engine. Promote it to the **internal event-driven engine** (`apps/research/.../backtest/`) for realistic next-bar fills and cost-stress before any capital.
3. **If higher returns are the real goal, relax a constraint that the data says matters:** the overnight drift held ~all of SPY's return. An **overnight / swing** hold, or a larger account that lifts the PDT/leverage ceiling, changes the problem far more than any intraday signal tweak will.
4. **Get more data.** 240 clean days is one regime. Re-fetch a multi-year history (and fix the corrupted June-2026 segment at the source) before trusting any Sharpe here.

---

## 10. Files Changed

**New — research layer (importable, tested):**
- `research/lib/data_access.py` — load seam, `flag_corrupt_days`, `load_clean_spy_5min`, `chronological_split`.
- `research/lib/strategies.py` — `finalize_intraday` (no-lookahead + EOD-flat), ORB/ORB-fade/RSI/z-score/MA/benchmark generators.
- `research/lib/backtest.py` — `run_intraday_backtest`, IBKR commission + slippage scenarios, Reg T sizing/reject, `BacktestMetrics`.
- `research/validate_data.py`, `research/market_structure.py`, `research/run_experiments.py` — runnable stages.
- `research/__init__.py`, `research/lib/__init__.py`.

**New — tests:**
- `tests/research/test_research_lib.py` — 7 tests: corrupt-day detection, chronological split (no overlap), no-lookahead shift, EOD flatten, no overnight carry, cost monotonicity, impossible-size rejection.

**New — outputs:** `research/results/*.json|csv`, `research/charts/*.png`, this report.

**Unchanged:** all existing engine/package code was reused, not modified. Full suite: **85 passed**.

*(Note: `AGENTS.md` shows as modified in git status from before this task — unrelated to this work.)*

---

## 11. Commands to Rerun

```bash
# from repo root
set -a; source .env; set +a          # only needed to (re)fetch data; analysis uses the cache

uv sync

# 1. Data quality (writes research/results/data_quality.json)
uv run python research/validate_data.py

# 2. Market structure (writes research/results/market_structure.json + charts)
uv run python research/market_structure.py

# 3. All hypotheses + cost grid + train/test + walk-forward
uv run python research/run_experiments.py

# Tests + quality gates
uv run pytest tests/research -q
uv run ruff check research tests/research
uv run ruff format --check research tests/research
```

---

## 12. Output Locations

| Artifact | Path |
|---|---|
| Data-quality report | `research/results/data_quality.json` |
| Market-structure stats | `research/results/market_structure.json` |
| All experiment runs (machine-readable) | `research/results/experiments.json` |
| Hypothesis summary table | `research/results/experiments.csv` |
| Charts | `research/charts/time_of_day_profile.png`, `research/charts/time_of_day_mean_return.png` |
| This report | `research/reports/spy_5min_intraday_strategy_research.md` |

*Raw Alpaca data and the `.data/` cache remain gitignored; every research output above is a sanitized aggregate containing no raw vendor data. Nothing in this report is financial advice.*
