# Beyond SPY: Cross-Asset Momentum & Trend-Timed Leverage — Research Report

*Skeptical quant research on liquid US ETFs, targeting >20–30% annualized net of
realistic costs and tradable through Interactive Brokers on a ~$2,000 account.*

**Author:** research agent · **Date:** 2026-07-02 · **Engine:** repo `trade_data`
loaders + `trade_vectorbt` primitives + a purpose-built, auditable portfolio
simulator (`research/momentum/`).

---

## 1. Executive summary

I tested three families of strategy on a 24-ETF liquid universe over 2016–2026
(signals live from 2017-01 after warmup):

1. **Unleveraged cross-sectional momentum / sector rotation** — the "textbook"
   candidate. **Result: no edge.** It *underperformed* SPY buy-and-hold on CAGR
   and only modestly improved drawdown. Rejected as a return engine.
2. **Dual-momentum asset rotation** (equity vs. bonds/gold with an absolute-
   momentum gate) — improved risk (max DD −22% vs SPY −34%) but CAGR ~11–18%,
   **below the 20–30% target.** Kept only as a *defensive* option, not a hit.
3. **Trend-timed leveraged ETF** — hold a 2× Nasdaq ETF (**QLD**) only while QQQ
   is above its 200-day SMA, otherwise sit in T-bills (**BIL**). **This is the
   one candidate that meets the target and survives my robustness battery.**

**Focus candidate — `QLD when QQQ > SMA200, else BIL` (net of 8 bps/side costs):**

| Metric | Full 2017–2026 | Train 2017–2020 | **Test 2021–2026 (OOS)** |
|---|---|---|---|
| CAGR | **31.0%** | 35.0% | **28.9%** |
| Sharpe | 0.98 | 1.03 | 0.94 |
| Sortino | 1.12 | 1.11 | 1.16 |
| Max drawdown | **−42%** | −42% | −39% |
| Calmar | 0.73 | 0.83 | 0.74 |
| Switches/yr | ~4 | ~5 | ~4 |

It beats SPY buy-and-hold (15% CAGR) and QQQ buy-and-hold (22% CAGR, −35% DD) on
both return and risk-adjusted return, and it turns TQQQ buy-and-hold's −82%
drawdown into −42%. It is **cheap to run** (≈4 trades/year, one ETF) and trivially
executable at IBKR.

**But this is not a free lunch, and I will not oversell it.** The return is
fundamentally *leveraged US-tech beta harvested in a favorable regime*, with a
trend overlay whose main value is dodging *sustained* downtrends — not fast
crashes or chop. Realized in-sample it still had a **−13.8% single day** (Mar
2020), a **−42% drawdown**, a whipsaw year (**2018: −14% vs QQQ −0.1%**), and in
2022 it merely *matched* unleveraged QQQ (−31%) rather than escaping. History is
only 10.5 years, entirely inside a secular Nasdaq bull, with **no pre-2016 crisis
test** (2000–02, 2008). See §8–9.

**Verdict:** a *plausible, robust-within-sample* candidate that clears the return
bar — advanced to paper trading with strict position-sizing and drawdown rules,
**not** endorsed as low-risk or regime-proof.

---

## 2. Universe tested

All liquid, IBKR-tradable, no options/futures/crypto, no penny/illiquid names.
Split+dividend-**adjusted** daily bars from Alpaca (`adjustment="all"` → total
return; essential for fairly ranking bonds/REITs against equity).

- **Broad equity:** SPY, QQQ, IWM, EFA, EEM
- **Sector SPDRs:** XLK, XLE, XLF, XLV, XLY, XLP, XLI, XLU, XLB, XLRE, XLC
- **Bonds / defensive:** TLT, IEF, LQD, HYG, SHY *(SHY/BIL = cash proxy)*
- **Real assets:** GLD, VNQ, DBC
- **Leveraged (candidate only):** QLD (2× QQQ), TQQQ (3× QQQ), SSO (2× SPY),
  UPRO (3× SPY); **BIL** as the risk-off T-bill sleeve.

Data span: **2016-01-04 → 2026-07-01** (2,638 daily bars/symbol; XLC from 2018).

---

## 3. Data quality review

- **Source integrity:** fetched through the repo's own `AlpacaHistoricalBarsSource`
  → normalized `Bar` records → local JSONL cache; backtests read the cache, never
  the network. Cache is gitignored (`.data/momentum_adj/`).
- **Adjustment:** `adjustment="all"`. Verified this materially changes bond/REIT
  series (e.g. TLT 2016-01 adjusted close ≈ $90.8 vs. raw ≈ $122 — dividends
  reinvested). Using raw prices would have systematically penalized high-yield
  assets in momentum ranking; that bias is removed.
- **Coverage:** full for all 23 non-leveraged names; XLC ragged from 2018-06 and
  handled (never ranked before it has a full lookback).
- **Glitch scan:** 0 daily moves >40%. Max |daily move| are economically sensible
  (XLE −20% on 2020-03-09, IEF/SHY <3%). No corrupt segments found.
- **Free-SIP delay:** data ends ~15 min behind real time; irrelevant for a daily
  strategy.
- **Survivorship:** the leveraged/sector ETFs used all existed for the whole test
  window, so no survivorship inflation *within* the sample — but see §8 on regime.

---

## 4. Strategies tested (and why the failures failed)

### 4.1 Sector rotation (REJECTED)
Rank 11 sector SPDRs by trailing return, hold top-1/top-3, rebalance monthly.
- Top-3 6mo: **10.8% CAGR**, Sharpe 0.66 — worse than SPY on every axis.
- Top-3 12-1: 14.7% CAGR, still < SPY's 15.2%.
- Top-1 6mo: 13.8% CAGR, Sharpe 0.66, whippy.
**Why rejected:** cross-sectional sector momentum added turnover and tracking
error without adding return in a market where broad tech beta dominated. No edge.

### 4.2 Dual-momentum asset rotation (KEPT as defensive, not a hit)
Rank equity/bond/gold/REIT ETFs, hold top-K, gate each slot on positive absolute
momentum → rotate to IEF/SHY when negative.
- Asset top-1 12mo → IEF: **18.3% CAGR**, Sharpe 0.90, DD −31%.
- Asset top-3 6mo → IEF: 11.4% CAGR, **DD −22.6%**, Sharpe 0.86.
**Why not the answer:** the diversified versions cut drawdown nicely (the best
*risk* profile in the study) but cap CAGR well under 20%. The single-asset version
reaches 18% but is concentrated/whippy. Useful as a low-stress allocation, but it
does not meet the >20–30% mandate.

### 4.3 Blended / accelerating momentum (REJECTED)
Average of 1/3/6-month returns on a growth-tilted set, top-1/2/3, dual-momentum
gate. CAGR 10–14%, Calmar improved (~0.55) but return still sub-benchmark.
**Why rejected:** same story — better drawdown, not more return.

### 4.4 Trend-timed leveraged ETF (CANDIDATE)
Hold `lev` while `base > SMA(N)`, else BIL. Signal lagged 1 day (no lookahead).
Actual adjusted leveraged-ETF prices → decay/expense embedded.

Full-period MA robustness (net of 8 bps/side):

| Variant | CAGR | Sharpe | Max DD | Calmar |
|---|---|---|---|---|
| QLD / QQQ>SMA150 | 33.9% | 1.06 | −40% | 0.84 |
| QLD / QQQ>SMA175 | 35.7% | 1.09 | −40% | 0.88 |
| **QLD / QQQ>SMA200** | **31.0%** | **0.98** | **−42%** | **0.73** |
| QLD / QQQ>SMA225 | 28.4% | 0.91 | −45% | 0.63 |
| TQQQ / QQQ>SMA200 | 42.8% | 0.97 | −57% | 0.76 |
| SSO / SPY>SMA200 | 18.0% | 0.82 | −38% | 0.47 |
| UPRO / SPY>SMA200 | 24.8% | 0.80 | −52% | 0.48 |

The **QQQ-based** family is robust across MA 150–225 (all 28–36% CAGR, Sharpe
>0.9). The **SPY-based** family is materially weaker — SPY trends whipsaw more and
carry less momentum, so I anchor on the Nasdaq version. I select **SMA200** as the
canonical, least-overfit parameter (the standard trend filter), *not* the
best-scoring SMA175.

---

## 5. Best candidate — full metric set

`QLD when QQQ > 200-day SMA, else BIL` · monthly-ish switches · $2,000 start ·
8 bps/side (5 bps IBKR fixed commission + 3 bps slippage).

| Metric | Value |
|---|---|
| Total return (2017–2026, ~9.5y) | ~+1,300% |
| CAGR | **31.0%** |
| Annualized vol | 33.7% |
| Sharpe / Sortino | 0.98 / 1.12 |
| Max drawdown | −42.3% |
| Calmar | 0.73 |
| Best / worst calendar year | +72% (2017) / −31% (2022) |
| Worst single day | **−13.8%** (2020-03-09) |
| % months positive | ~63% |
| Time risk-on (holding QLD) | ~83% |
| Switches | ~40 total (~4/yr) |
| Avg turnover | ~2 sides/switch, ~8/yr |

Calendar years (strategy vs QQQ buy-hold): 2017 **+70% / +33**, 2018 **−14% /
−0.1**, 2019 +34 / +39, 2020 **+71 / +49**, 2021 **+55 / +27**, 2022 −31 / −33,
2023 **+72 / +55**, 2024 **+43 / +26**, 2025 +21 / +21.

Equity curve data: `research/results/momentum_equity_focus.csv`.

---

## 6. Robustness review

| Test | Setup | Result | Read |
|---|---|---|---|
| **Out-of-sample** | Train 2017–20 / Test 2021–26 | Test CAGR **28.9%**, Sharpe 0.94, DD −39% | ✅ Holds OOS through the 2022 bear |
| **Parameter (MA)** | SMA 150/175/200/225 | 28–36% CAGR, Sharpe 0.9–1.1 | ✅ No cliff — not a single-parameter fluke |
| **Cost sensitivity** | 0 / 8 / 16 / 32 / 60 bps per side | CAGR 32→31→30→28→**25%** | ✅ Low turnover → cost-insensitive |
| **Slippage stress** | included above (up to 25 bps slip/side) | still 25% CAGR | ✅ Survives 4× realistic slippage |
| **Execution delay** | act 1 / 2 / 3 days late | 31 / 32 / 36% CAGR | ✅ Not a fragile same-bar-timing artifact |
| **Leverage choice** | QLD (2×) vs TQQQ (3×) | 2× keeps DD −42% vs 3× −57% | ⚠️ Prefer 2× for survivability |

The candidate passes every quantitative robustness test I could run on the
available data. The remaining risks are *regime/structural*, not parameter
fragility (§8).

---

## 7. IBKR tradability assessment (~$2,000 account)

- **Instruments:** QLD and BIL are among the most liquid US ETFs (QLD ADV in the
  millions of shares, penny spreads). Zero liquidity concern at $2k size.
- **Order handling:** one signal check per day on the QQQ close; trade at/near the
  close with a **MOC or marketable-limit** order. QLD ≈ $100–150/share → $2,000
  buys 13–20 shares; whole-share sizing is fine.
- **Costs:** IBKR fixed = $1.00/order (=5 bps on $2k) or tiered ≈ $0.35 min
  (~1.75 bps). At ~8 orders/yr the annual commission drag is ~$8 — negligible, and
  the cost grid already stresses 4× this.
- **Margin:** strategy is **cash / long-only** (leverage comes from the ETF, not
  the account) — no margin, no Reg-T calls, no borrow.
- **Pattern-day-trader rule:** ~4 switches/yr is nowhere near the PDT threshold.
- **Frictions to respect live:** (1) leveraged-ETF spreads widen intraday — use
  limits; (2) daily-reset ETFs must be traded on **close-based** signals, never
  held on stale intraday levels; (3) a hard overnight gap can move QLD ±10%+
  before you can act — size for it.

**Conclusion:** fully practical to automate at IBKR for a $2k account.

---

## 8. Why I remain skeptical (structural risks)

1. **Single favorable regime.** 2016–2026 is one secular Nasdaq bull. Leveraged
   Nasdaq + trend filter is close to the *best-case* environment for this design.
   No dot-com (2000–02) or GFC (2008) test — the leveraged ETFs barely existed
   then. Much of the 31% CAGR is **2× beta** captured in that regime, not a
   market-neutral edge.
2. **Fast-crash tail.** The daily signal exits *after* the SMA is breached. In a
   gap crash the strategy holds 2× into the first leg — realized as a **−13.8%
   day** in Mar 2020. A 2× or 3× overnight gap is an uninsurable tail here.
3. **Whipsaw / chop.** In range-bound years the filter buys high and sells low
   repeatedly: **2018 −14% vs QQQ −0.1%**, and 2022 gave back the leverage
   advantage (−31%, ≈ unleveraged QQQ). Expect multi-year stretches of
   underperformance vs simply holding QQQ.
4. **−40%+ drawdowns are the norm, not the tail.** On $2k that is a real −$850
   paper loss with −$275 single days. Behavioral abandonment risk is high.
5. **Small number of decisions.** ~40 switches drive most of the timing value —
   modest statistical significance for the *overlay* specifically (the beta is
   the bulk of returns).
6. **Leverage decay.** Embedded via real prices, but a prolonged high-vol grind
   *above* the SMA would bleed the 2×/3× series regardless of the filter.

---

## 9. Final recommendation

- **Do not present any strategy as "safe" or regime-proof.** The unleveraged
  momentum/rotation work is an honest **"no robust return edge found"** — it
  helps risk, not return.
- **The trend-timed 2× Nasdaq (`QLD / QQQ>SMA200 → BIL`) is the one candidate that
  meets the >20–30% target and survives OOS, cost, slippage, execution-lag, and
  parameter-robustness testing.** Advance it to **paper trading**, not size-up:
  - Prefer **QLD (2×)** over TQQQ (3×) for drawdown survivability.
  - Fixed rules: check QQQ vs SMA200 on the close daily; switch on flips only;
    MOC/marketable-limit orders; no discretionary overrides.
  - Pre-commit to the −40%+ drawdown and the whipsaw years, or don't trade it.
  - Consider a **risk-scaled blend** (e.g. part QLD-trend for return + part
    dual-momentum asset sleeve for its −22% DD) to soften the equity curve.
- **Best next validation step:** extend the underlying (QQQ/NDX total return)
  history back to 2000 and *simulate* the 2× series to test 2000–02 and 2008. If
  the filter survives those, confidence rises substantially. Until then, treat the
  live edge as **leveraged bull-regime beta with a downside-trend brake.**

---

## 10. Files changed / added

| Path | Purpose |
|---|---|
| `research/momentum/fetch_universe.py` | Fetch adjusted daily bars for the 24-ETF universe into `.data/momentum_adj/` |
| `research/momentum/lib.py` | Panel loader, cost model, momentum signals, monthly rotation simulator, trend-timed leveraged simulator, metrics |
| `research/momentum/run_momentum.py` | Full study: benchmarks, rotation baselines, trend MA grid, OOS split, cost/slippage/execution-lag sensitivity |
| `research/reports/etf_momentum_and_leveraged_trend_research.md` | This report |
| `research/results/momentum_results.{json,csv}` | All runs, machine-readable |
| `research/results/momentum_equity_focus.csv` | Daily equity of the focus candidate vs QQQ/SPY buy-hold |

No production/strategy code paths were modified; all work is in the research
track. Leveraged ETFs were added to the gitignored data cache only.

## 11. Commands to rerun

```bash
# 1. Load Alpaca credentials (gitignored .env)
set -a; source .env; set +a

# 2. Fetch the full adjusted universe incl. leveraged ETFs (QLD/TQQQ/SSO/UPRO/BIL)
uv run python research/momentum/fetch_universe.py

# 3. Run the full study (writes results + prints the summary table)
uv run python research/momentum/run_momentum.py

# 4. Lint
uv run ruff check research/momentum/
```

## 12. Output locations

- Machine-readable results: `research/results/momentum_results.json` / `.csv`
- Focus equity curve: `research/results/momentum_equity_focus.csv`
- Adjusted data cache (gitignored): `.data/momentum_adj/market_data/bars/…`
- This report: `research/reports/etf_momentum_and_leveraged_trend_research.md`

---

*Nothing in this report is financial advice. Backtests are not predictive;
leveraged ETFs can lose the large majority of their value in adverse regimes.*
