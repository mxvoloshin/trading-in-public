# MES Intraday — Novel Mechanisms (Beyond the Standard Playbook)

*Companion to [mes_intraday_strategy_research.md](mes_intraday_strategy_research.md). Same
instrument proxy (SPY 5-min → MES, $5/pt), same account ($2,000, IBKR, long+short, flat by
15:55 ET), same 2020→2026 window and audited dollar simulator. What is new here is the
**strategy mechanism** — this round deliberately abandons the standard oscillator/breakout
playbook the prior tracks reused.*

**Author:** research agent · **Date:** 2026-07-02

---

## 1. Why this round exists

Fair critique of the first MES report: it re-tested the *same five setups* the earlier SPY
study already ran (ORB, VWAP/RSI reversion, MA-cross, VWAP-trend) — just with shorts and futures
math bolted on. That is a re-run, not research.

So this round asks a different question. The market-structure work established the one durable
fact about this instrument: **the S&P's return lives overnight; the intraday move is close to a
coin-flip.** Every prior rule was *within-session and price-only* — it structurally could not use
the information that actually carries signal. This round tests **six mechanisms that use inputs
the earlier rules threw away**:

| # | Mechanism | New information it uses | Family |
|---|---|---|---|
| N1 | **Gap-and-go** | overnight gap + first-bar follow-through | cross-session momentum |
| N2 | **Gap-fade to prior close** | overnight gap magnitude | cross-session reversion |
| N3 | **Trend-day ride-to-close** | first-hour *day-type* (range, close location, gap alignment) | conditional momentum |
| N4 | **Prior-day-level reversion** | yesterday's high/low as magnets | level reversion |
| N5 | **Vol-regime switch (meta)** | first-hour realized range → regime | adaptive combiner |
| N6 | **Volume-climax reversal** | volume spikes | order-flow reversion |

All six reuse the same no-lookahead / flat-by-EOD finalizer and the same MES dollar simulator;
**only the entry logic is new.** Code: `research/mes_intraday/novel.py`,
`research/mes_intraday/run_novel.py`. Two extra unit tests pin the gap feature and gap-and-go's
no-lookahead direction (12 tests total in the suite).

---

## 2. Results (1 contract, $0.62/side, 1-tick slippage)

**Naive (signal/level exit, no hard stop):**

| Strategy | Ann. % | PF | Sharpe | Max DD % | Worst day $ | Trades | Blows up? |
|---|---|---|---|---|---|---|---|
| N1 gap-and-go | −10.9 | 0.97 | −0.11 | −129 | −1,059 | 575 | Yes |
| N2 gap-fade | −33.0 | 0.92 | −0.32 | −387 | −740 | 701 | Yes |
| N3 trend-day ride | −9.3 | 0.92 | −0.16 | −110 | −1,357 | 208 | Yes |
| N4 prior-day-level reversion | −54.2 | 0.91 | −0.51 | −492 | −812 | 1,748 | Yes |
| N5 vol-regime switch | −82.7 | 0.85 | −0.84 | −433 | −1,038 | 1,679 | Yes |
| N6 volume-climax reversal | −29.3 | 0.68 | −0.72 | −201 | −996 | 236 | Yes |

**Risk-managed (0.30% stop / 0.60% target):**

| Strategy | Ann. % | PF | Sharpe | Max DD % | Worst day $ | Blows up? |
|---|---|---|---|---|---|---|
| **N1 gap-and-go** | **+7.8** | 1.04 | 0.17 | **−44** | **−117** | Yes |
| N2 gap-fade | −32.6 | 0.86 | −0.70 | −270 | −117 | Yes |
| N3 trend-day ride | −2.5 | 0.96 | −0.10 | −48 | −115 | Yes |
| N4 prior-day-level reversion | −135.2 | 0.88 | −1.41 | −899 | −873 | Yes |
| N5 vol-regime switch | −80.5 | 0.86 | −1.11 | −488 | −1,145 | Yes |
| N6 volume-climax reversal | −17.4 | 0.78 | −0.78 | −147 | −244 | Yes |

**What changed vs the baselines:**

- **The momentum-continuation ideas (N1, N3) are the best-behaved strategies in the entire
  study.** With a stop, N1's worst day is **−$117** and N3's is **−$115** — versus ORB's −$615
  and the reversion strategies' −$700 to −$2,000. A stop *helps* these (it hurt ORB), because
  they cut losers fast and let the occasional trend-day winner pay for them.
- **The reversion novelties (N2, N4, N5, N6) fail just like the old ones.** Fading the S&P
  intraday — off any reference (VWAP, prior-day levels, volume climaxes) — loses money over
  2020→2026. This is now a *robust negative result* across many references, not a one-off.

---

## 3. The standout, examined honestly — N1 gap-and-go

N1 risk-managed is the only new mechanism worth a second look: **+7.8%/yr, Sharpe 0.17, max DD
−44%, worst day −$117.** Small, controlled per-trade risk — exactly what a small account needs.
But it does **not** clear the bar, for the same three reasons as everything else:

**(a) Not robust out-of-sample.** Chronological 70/30 split (risk-managed):

| | Ann. % | PF | Max DD % |
|---|---|---|---|
| **Train (2020→2024)** | **−0.4** | 1.00 | −44 |
| **Test (2024→2026)** | **+26.9** | 1.11 | −43 |

The entire edge is in the recent half; the training half is flat-to-negative. Same regime
concentration that flagged ORB.

**(b) Per-year P&L alternates sign — noise, not persistence** ($, 1 contract, risk-managed):
2020 **−$238** · 2021 **+$443** · 2022 **+$877** · 2023 **−$411** · 2024 **+$636** · 2025
**−$614** · 2026 **+$321**. Three losing years, four winning — no stable edge you could size on.

**(c) It still blows up $2,000, and reaching 20% makes it worse.** Every parameter corner is a
margin call:

| Config | Ann. % | Max DD % | Worst day $ |
|---|---|---|---|
| gap>0.15%, 0.3% stop, 2:1 | +7.8 | −44 | −117 |
| gap>0.30%, 0.3% stop, 2:1 | +13.1 | −31 | −116 |
| gap>0.15%, **0.3% stop, 3:1** | **+18.0** | **−66** | −117 |
| gap>0.15%, **0.2% stop, 3:1** | **+14.9** | −36 | −79 |

To push toward 20% you widen the target to 3:1 — which raises the drawdown to −66% and re-creates
the tail-dependent, "hope a trend day shows up" profile. There is no corner that is
simultaneously ≥20%, low-drawdown, robust, **and** survivable on $2,000.

---

## 4. Conclusion — the wall is structural, confirmed from a new direction

The value of this round is not a winner; it is a stronger negative result. The first report
could be dismissed as "you tested the wrong five strategies." This one tested **six mechanically
different ones** — cross-session gaps, day-type conditioning, prior-day levels, regime-switching,
and volume — and reached the same place:

- **Momentum-continuation (gap/trend-day) has a whisper of edge with tight stops** — best-behaved
  by far — but it is regime-concentrated, sign-alternating year to year, and sub-20%.
- **Intraday reversion loses off every reference tried.**
- **Nothing survives 16× leverage on $2,000.**

Across both reports that is **11 distinct mechanisms in two idea-families**, all hitting the same
wall. The bottleneck was never the choice of signal; it is the two structural facts that no
intraday rule can change: the index's directionality lives overnight, and a $2,000 MES account is
too thin to survive the leverage that any 20% target requires. The productive moves remain the
ones in §10 of the main report — **more capital, or relax the intraday-only constraint** (where
the [single-stock momentum track](single_stock_momentum_research.md) actually cleared 20%
unlevered).

If you want to keep exploring intraday specifically, the honest next step is not another signal
but a **larger account** ($10-25k, so 1 MES is 1.4-3.4× not 16×), where N1/N3's small-loss
profile could at least be *traded* without instant ruin — and even then only as a low-return,
skill-building exercise, not a 20% engine.

---

## 5. Files & rerun

**New:** `research/mes_intraday/novel.py` (6 mechanisms + per-day feature frame),
`research/mes_intraday/run_novel.py`, `research/results/mes_novel_summary.json`, two added tests
in `tests/research/test_mes_intraday.py`, this report.

```bash
uv run python research/mes_intraday/run_novel.py
uv run pytest tests/research/test_mes_intraday.py -q
uv run ruff check research/mes_intraday tests/research/test_mes_intraday.py
```

*The `.data/` cache stays gitignored; outputs here are sanitized aggregates. Nothing in this
report is financial advice.*
