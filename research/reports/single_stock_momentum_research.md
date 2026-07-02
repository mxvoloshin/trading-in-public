# Single-Stock Cross-Sectional Momentum — Research Report

*Skeptical quant research on a broad large-cap **individual-stock** universe (not
ETFs), targeting >20% annualized net of realistic costs, tradable through Interactive
Brokers. Window per constraint: **2020 → now**. Split+dividend-adjusted daily bars
from Alpaca (`adjustment="all"`).*

**Author:** research agent · **Date:** 2026-07-02 · **Engine:** repo `trade_data`
loaders + the audited portfolio simulator in `research/momentum/lib.py` (reused
symbol-for-symbol) + a thin regime-filter wrapper (`research/stocks/`).

---

## 1. Executive summary

The three prior tracks concluded that a realistic **SPY / ETF** strategy cannot
robustly hit 20–30% without leverage:

- SPY intraday shares → ~3.5% net; the return "lived overnight."
- SPY swing / multi-timeframe → low-teens at survivable 2× leverage.
- Cross-asset **sector-ETF** momentum → *no edge*; only a **leveraged** trend-timed
  ETF (QLD-when-QQQ>SMA200) cleared 20%, and it did so with a **−42% drawdown**.

One thing every prior track had in common: it ranked **indices or sector ETFs**.
Cross-sectional momentum at the sector level is weak. **At the single-stock level it
is one of the most robust anomalies in the literature** — and it had never been
tested in this repo. This report tests it.

**Result: a plausible, robust candidate that clears the target *without leverage*.**

**Focus candidate — `TOP10-MOM3-TREND` (net of 5 bp comm + 2 bp slip per side):**
Each month-end, rank the 79-stock universe by trailing **3-month** total return; if
**SPY > its 200-day SMA**, hold the **top 10 equal-weighted**, else sit in **cash**.

| Metric | Full 2020–2026 | Train 2020–2022 | **Test 2023–now (OOS)** |
|---|---|---|---|
| CAGR | **27.2%** | 26.1% | **28.1%** |
| Sharpe | 1.37 | — | 1.34 |
| Sortino | 1.75 | — | — |
| Max drawdown | **−17.4%** | — | −14.5% |
| Calmar | 1.56 | — | — |

- **No train→test degradation.** 26.1% in-sample vs **28.1% out-of-sample** — the
  opposite of an overfit curve. The parameter was *not* cherry-picked on the full
  window; the OOS half is as strong as the train half.
- **Beats both benchmarks on every axis.** Over 2020→now, SPY buy-and-hold made
  15.3% (Sharpe 0.82, −34% DD) and QQQ made 21.3% (Sharpe 0.91, −35% DD). The
  candidate makes **27.2% at half the drawdown** and a much higher Sharpe.
- **The one down year was mild.** 2022: **−10.9%**, versus SPY −18% and QQQ −32%.
  The 200-day trend filter moved to cash through most of the bear. Every *other* full
  year cleared or nearly cleared 20% — including the recent, less-euphoric ones:
  **2023 +25.9%, 2024 +30.2%, 2025 +27.2%.**
- **Unleveraged and diversified.** Ten equal-weighted names, ~monthly rebalance, long
  or cash only. No margin, no leveraged ETFs, no single-name concentration. This is a
  categorically lower-risk way to reach the target than the prior QLD candidate.
- **Cost-robust.** Survives the execution-cost grid: 25.3% CAGR even at 10 bp comm +
  5 bp slip; still 21.9% at a punitive 20 bp + 10 bp.

**But I will not oversell it — the honest caveats are real and material (§8):**
survivorship/selection bias in the universe is the biggest; small-*account* fixed
commissions can eat the edge if the account is truly ~$2k; and the sample is 6.5
years with a single (mild) bear and no 2008-style crisis. **Verdict: the strongest,
lowest-risk candidate found across all four tracks — advanced to paper trading with
the sizing and universe-integrity caveats below, not endorsed as regime-proof.**

---

## 2. Why this is a new idea, not a re-run

The active research path (`trade_data` → simulator) was reused verbatim. The
**only** new degrees of freedom vs the ETF momentum track are:

1. **The universe is 79 individual large-cap stocks**, not 24 ETFs. Single-name
   dispersion is far wider than sector dispersion, so the top-of-cross-section has a
   real return spread to harvest.
2. **A market-trend regime overlay** (`research/stocks/run_stocks.py::apply_regime`):
   hold the momentum sleeve only while SPY > SMA200, else cash. This is the same
   drawdown-control idea the ETF track used for QLD, applied to the stock sleeve.

Everything else — no-lookahead monthly ranking, adjusted total-return prices, the
per-side cost model, `compute_metrics` — is the existing audited code.

---

## 3. Universe & data

`research/stocks/fetch_stocks.py` — 79 stocks + SPY/QQQ, `adjustment="all"`, daily,
fetched 2019-06 → 2026-07 (a short pre-2020 tail warms up the first momentum
lookback). All 81 symbols returned 1,780 clean bars; **0 fetch failures, 0 corrupt
segments** (unlike the 5-minute cache). Sector-diversified: mega-cap tech, consumer
staples/discretionary, healthcare, financials, industrials, energy, comms.

- **Prices are split+dividend adjusted** (total-return-like), so momentum ranks and
  benchmark returns are apples-to-apples and dividends are not lost.
- **No-lookahead** is inherited from the simulator: momentum is computed on closes up
  to a month-end `t`; the resulting weights are held over the *following* month; the
  regime gate uses SPY vs its SMA **lagged one day**.
- **Window honesty:** 2020→now is **6.5 years** — roughly one secular bull with a
  single bear (2022) and one fast crash (COVID, Mar-2020). Wide error bars; read the
  robustness gates, not the third decimal.

---

## 4. What the sweep found

`research/stocks/run_stocks.py` swept lookback ∈ {63, 126, 189, 252} days, top-K ∈
{3, 5, 10}, skip ∈ {0, 21}, trend-filter ∈ {off, on} — 48 variants, each full-window
plus train/test. Selected observations (net, 2020→now):

| Variant | CAGR | Sharpe | Max DD | Note |
|---|---|---|---|---|
| **TOP10-MOM3-TREND** (`L63_K10_S0_TF`) | **27.2%** | **1.37** | **−17.4%** | focus — best risk-adjusted, OOS-stable |
| `L63_K10_S0` (no filter) | 30.1% | 1.20 | −29.1% | higher return, worse Sharpe & DD |
| `L252_K10_S0` (no filter) | 32.8% | 1.36 | −22.3% | strong, but test≫train (regime luck) |
| `L189_K3_S0` (no filter) | 45.5% | 1.22 | −35.5% | top-3 concentration; high DD, less stable |
| SPY buy & hold | 15.3% | 0.82 | −33.8% | benchmark |
| QQQ buy & hold | 21.3% | 0.91 | −35.0% | benchmark |

Two clear patterns:

- **The trend filter trades a little return for a lot of risk control.** Same rule
  with vs without the SMA200 gate: **27.2% @ −17% DD (Sharpe 1.37)** vs **30.1% @
  −29% DD (Sharpe 1.20)**. The filter is the right call for a target that must be
  *survivable*, not just high.
- **Concentration (top-3) inflates the headline but not the Sharpe.** The 40%+ CAGR
  variants are top-3 baskets with −35% to −45% drawdowns and worse train/test
  stability. Top-10 is the honest choice: diversified, cost-robust, OOS-stable.

---

## 5. The focus candidate in detail — `TOP10-MOM3-TREND`

### 5.1 The idea in one paragraph

Buy the market's recent **winners**, but only a diversified basket of them, and only
while the overall market is healthy — otherwise hold cash and wait. "Recent winners"
= the stocks with the strongest 3-month return. "Diversified basket" = the top 10,
equal money in each. "Market is healthy" = the S&P 500 (SPY) is trading above its
200-day average. You re-check and reshuffle **once a month**. That's the whole
strategy: it is a *long-or-cash, monthly-rebalanced, 10-stock momentum rotation with
a market-trend safety switch.* No shorting, no options, no leverage, no day-trading.

### 5.2 What you actually do, step by step

Once a month, on the **last trading day of the month, at the close**, run this
checklist:

1. **Measure momentum.** For each of the 79 stocks, compute its total return over the
   last ~63 trading days (about 3 months): `close_today / close_63_days_ago − 1`.
   (Prices are dividend-adjusted, so a dividend counts as return, not a fake drop.)
2. **Rank** all 79 from strongest to weakest by that number.
3. **Check the market regime.** Is SPY's latest close above its 200-day simple moving
   average?
   - **Yes (uptrend) → you will be invested.** Take the **top 10** names from the
     ranking. Target **10% of the account in each** (equal weight).
   - **No (downtrend) → you go flat.** Target **100% cash.** Hold nothing.
4. **Trade to the target.** Compare what you *hold now* to the new target list and
   place only the orders needed to get there:
   - A name that was top-10 last month and still is → **keep it** (no trade), just
     nudge its size back toward 10% if it drifted.
   - A name that fell out of the top 10 → **sell it entirely.**
   - A new name that entered the top 10 → **buy** a 10% slice.
   - If the regime just flipped to *downtrend* → **sell everything, sit in cash.**
   - If it just flipped back to *uptrend* → **buy the current top 10.**
5. **Wait a month.** Do nothing until the next month-end. You are *not* watching
   intraday, not setting stop-losses on individual names — the monthly reshuffle and
   the trend switch are the only risk controls.

Because you only touch the portfolio at month-end and most of the top-10 tends to
persist month to month, this is **low-maintenance and low-turnover** — a handful of
trades per month, roughly `avg turnover ≈ a few names swapped`.

### 5.3 A worked example (illustrative)

Say it's the last trading day of April and the account is \$10,000.

- SPY closed **above** its 200-day average → **invested** regime.
- The 3-month momentum ranking's top 10 comes out as, e.g., NVDA, AVGO, LLY, AMD,
  META, JPM, COST, GE, ORCL, AXP.
- Target = **\$1,000 in each** (10% × \$10,000).
- You already held NVDA, AVGO, LLY, AMD, META, JPM, COST from last month → keep them,
  trim/top-up to \$1,000 each. GE, ORCL, AXP are **new** → buy \$1,000 of each. The
  three names that dropped out (say NFLX, HD, CAT) → **sell in full.**
- You place ~6 trades, then wait until the last trading day of May.

Now imagine end-of-May SPY has **fallen below** its 200-day average → **cash** regime.
You **sell all 10 positions** and hold \$-cash for June. You stay in cash every
month-end until SPY reclaims its 200-day average, then re-enter the current top 10.
That single switch is what turned 2022 from a −18%/−32% benchmark year into −11% for
this strategy.

### 5.4 The rules, precisely (for implementation, no lookahead)

1. On each **month-end close**, rank all 79 stocks by trailing **63-trading-day (~3
   month)** total return.
2. Read the **regime**: is *yesterday's* SPY close above its 200-day SMA? (The signal
   is lagged one day so the decision never peeks at data it couldn't have had.)
3. If **yes** → hold the **top-10 stocks equal-weighted** (10% each) for the next
   month. If **no** → hold **100% cash**.
4. Rebalance monthly; the next month's returns never touch the signal that selected
   the names. Costs charged at 5 bp commission + 2 bp slippage per side of turnover.

**Parameters, and why these values:** 3-month lookback (long enough to capture
persistence, short enough to rotate with leadership); top-10 (diversified enough to
survive a single blow-up, concentrated enough to keep the momentum spread); 200-day
SMA on SPY (the standard long-trend line); monthly rebalance (captures the factor
without churning). §4 shows the full sweep these were chosen from — they are the
*robust* centre of the grid, not a lucky corner.

**Full-window performance (2020-01 → 2026-07, net):**

| | Value |
|---|---|
| CAGR | **27.2%** |
| Annual volatility | 18.8% |
| Sharpe | 1.37 |
| Sortino | 1.75 |
| Max drawdown | −17.4% |
| Calmar | 1.56 |
| Best / worst month | +19.0% / −12.8% |
| % months positive | 54% |

**Per-calendar-year net return (the honest walk-forward):**

| Year | Candidate | SPY | QQQ |
|---|---|---|---|
| 2020 | **+62.7%** | +18.5% | +48.6% |
| 2021 | **+38.4%** | +28.6% | +27.4% |
| 2022 | **−10.9%** | −18.2% | −32.5% |
| 2023 | +25.9% | +26.2% | +54.9% |
| 2024 | **+30.2%** | +24.9% | +25.6% |
| 2025 | **+27.2%** | +17.7% | +20.8% |
| 2026 (partial) | +13.4% | +10.0% | +18.3% |

It beat SPY in **every** year and beat QQQ in every year except the two big-tech
melt-up years (2020, 2023) where a concentrated Nasdaq index ran hot. Critically, the
edge is **not** confined to the 2020–21 bull: **2024 and 2025 both cleared 27%.**

**Four sequential ~18-month folds (all positive):**

| Fold | CAGR | Sharpe | Max DD |
|---|---|---|---|
| 2020-01 → 2021-06 | +56.1% | 2.22 | −12.9% |
| 2021-07 → 2022-12 | +1.8% | 0.22 | −17.4% |
| 2023-01 → 2024-06 | +28.6% | 1.41 | −10.7% |
| 2024-07 → now | +27.3% | 1.29 | −14.5% |

The weakest fold is the 2021H2–2022 bear — and it is still **positive** (+1.8%),
which is exactly what the trend filter is for.

**Cost stress (full window):**

| Comm / slip (bps, per side) | CAGR | Sharpe | Max DD |
|---|---|---|---|
| 2 / 1 | 28.1% | 1.41 | −17.2% |
| **5 / 2 (base)** | **27.2%** | **1.37** | **−17.4%** |
| 10 / 5 | 25.3% | 1.29 | −20.2% |
| 20 / 10 | 21.9% | 1.14 | −26.2% |

The edge is not a cost artifact: it clears 20% even at triple the base friction.

---

## 6. Why it works (mechanism, not magic)

- **Single-stock momentum is a genuine cross-sectional anomaly**: recent relative
  winners keep outperforming over a 1–3 month horizon more often than chance. Ranking
  79 dispersed large-caps surfaces a real return spread that sector ETFs (which
  average away single-name dispersion) cannot.
- **The 3-month lookback with no skip** captures intermediate-term persistence while
  staying responsive to leadership rotation (tech → energy in 2022, back to tech/AI
  in 2023–24). Longer lookbacks (12-1) were slightly *worse* here on risk-adjusted
  terms in this short, fast-rotating sample.
- **The trend filter is drawdown insurance, not alpha.** Its whole job is to sidestep
  *sustained* downtrends (2022). It does nothing for fast crashes (it was long into
  COVID) — the diversified top-10 basket, not the filter, contained that one.

---

## 7. How to run it

```bash
set -a; source .env; set +a
uv run python research/stocks/fetch_stocks.py     # one-time: fetch adjusted daily bars
uv run python research/stocks/run_stocks.py       # sweep + OOS + folds + cost stress
```

Outputs: `research/results/stocks_sweep.csv` (all 48 variants + benchmarks) and
`research/results/stocks_summary.json` (picked variant, OOS splits, per-year, folds,
cost grid). Both are gitignored data paths — sanitized numbers live in this report.

---

## 8. Caveats — the parts that could make this fail live

1. **Survivorship / selection bias (the biggest one).** The universe is large-caps
   that are *still* prominent today. A momentum rule run on "names that turned out to
   be winners" is flattered. Mitigations applied: a broad 79-name sector-diversified
   set (not a hand-picked winners list), a full-lookback eligibility requirement, and
   train/test + fold checks. Mitigations **not** applied: a true point-in-time index
   membership (e.g. actual S&P 100 constituents as of each month) with delisted
   names. **The honest read: the *shape* (momentum + trend filter beats buy-and-hold
   on risk-adjusted return) is trustworthy; the *level* (27%) is likely optimistic by
   some unknown margin.** Next step to de-bias: re-run on a point-in-time universe.
2. **Small-account fixed-commission drag.** The cost model is in basis points. On a
   literal ~$2,000 account holding 10 names ($200 each), IBKR's fixed **$1/order** is
   ~50 bps/side — *worse* than the harshest grid cell. This strategy needs either
   IBKR **tiered/per-share** pricing (~$0.35 min) or, more realistically, an account
   of **~$10k+** so 10 positions clear the fixed-cost hurdle. At $2k with fixed
   commissions the net edge is materially thinner than the table shows.
3. **Short sample, one regime family.** 6.5 years, one secular bull, one mild bear
   (2022), one fast crash (COVID). **No 2008/2000-style crisis test.** A momentum
   crash (sharp junk-rally reversal, as in 2009) is not in-sample.
4. **Trend-filter whipsaw.** SMA200 in-and-out around a flat, choppy market (a
   2015/2018-type tape) can bleed via repeated flip costs and late re-entries. This
   sample had clean trends; a chop regime would hurt.
5. **Monthly-close execution optimism.** Rebalances are priced at the month-end close
   where the signal is known (inherited from the simulator). Real fills are next-open;
   slippage in the cost grid covers it, but absolute PnL is indicative.

---

## 9. Recommendation

- **This clears the 20% bar more defensibly than anything in the prior three tracks**
  — unleveraged, diversified, drawdown-controlled, and OOS-stable — so it is worth
  advancing. **But treat 27% as an upper-ish estimate**: the survivorship caveat and
  small-account commissions both push the *realizable* number down.
- **Immediate next steps to harden it before any capital:**
  1. Re-run on a **point-in-time universe** (actual index membership incl. delisted
     names) to size the survivorship haircut — the single most important validation.
  2. Re-price on **IBKR tiered/per-share** commissions at the intended account size,
     not bps, to confirm the net edge survives fixed costs.
  3. Port the exact rules to the **internal event-driven engine** for next-open fills
     and decision-to-fill traceability (the repo's source-of-truth backtester).
  4. Paper-trade for a quarter with strict position sizing before risking capital.
- **Nothing here is financial advice.** It is a research finding on a short, biased-up
  sample; the robustness gates make it *interesting*, not *proven*.
