"""MES (Micro E-mini S&P 500) intraday research harness — long+short, flat by EOD.

This module is the futures analog of the existing SPY-shares research layer
(``research/lib/``). The prior SPY track concluded that intraday-only SPY *shares*
cannot reach 20-30% on a $2,000 account because Reg-T caps leverage at 2x and the
$25k Pattern-Day-Trader minimum blocks margin day-trading. Futures change exactly
those two constraints, so this track re-tests the same family of well-known
intraday strategies under **MES contract economics**:

- **The data is still SPY** (the only instrument this repo can fetch). MES tracks
  the same S&P 500 index with >0.99 intraday correlation, so SPY 5-minute price
  *moves* are a faithful proxy. We convert SPY price into S&P 500 index points via
  ``index = SPY x 10`` (the long-standing ETF-to-index ratio) and price every trade
  in MES dollars: **$5 per index point per contract**. The ratio drifts ~1-2% over
  years — negligible for point-move P&L, and documented as a caveat in the report.
- **Long *and* short** (the prior track was long-only).
- **Futures cost model**: fixed commission per contract per side (not per share) and
  slippage measured in ticks (MES tick = 0.25 pts = $1.25), because a micro future
  is a fixed-multiplier instrument, not a percentage-of-notional one.
- **Multi-timeframe**: one strategy gates 5-minute entries on an hourly trend filter,
  satisfying the "decide on one timeframe, filter on another" requirement.

Nothing here carries a position overnight: every strategy is forced flat at 15:55 ET.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import time as dt_time
from typing import Any

import numpy as np
import pandas as pd

# --- MES contract economics ------------------------------------------------
# One MES contract is $5 per full S&P 500 index point. The E-mini ES is $50/pt
# and SPY is ~1/10th of the index, so 1 MES ~= holding 50 x SPY_price of notional.
POINT_VALUE = 5.0  # dollars per index point per contract
TICK_POINTS = 0.25  # minimum price increment in index points
TICK_VALUE = POINT_VALUE * TICK_POINTS  # $1.25 per tick per contract
SPY_TO_INDEX = 10.0  # S&P 500 index level ~= SPY price x 10

# IBKR all-in commission per side per MES contract (commission + exchange + NFA
# + regulatory). Real IBKR MES is ~$0.25 commission + ~$0.37 fees ~= $0.62/side;
# we sweep a grid around it. "none" is reference-only.
COMMISSION_PER_SIDE: dict[str, float] = {
    "none": 0.0,
    "low": 0.25,
    "mid": 0.62,
    "high": 0.85,
    "stress": 1.24,
}

# One-way slippage in ticks. MES is very liquid (tight 1-tick book most of the
# session), so 1 tick/side is a realistic default; 2 is a stress case.
SLIPPAGE_TICKS: dict[str, float] = {
    "none": 0.0,
    "half": 0.5,
    "one": 1.0,
    "stress": 2.0,
}

# --- Account assumptions ---------------------------------------------------
INIT_CASH = 2_000.0
# IBKR intraday margin per MES contract varies with volatility; ~$1,300-1,500 is
# typical for the day-trade rate. We use this only for the ruin/margin analysis,
# not for sizing the P&L (sizing is a fixed contract count).
INTRADAY_MARGIN_PER_CONTRACT = 1_400.0

MARKET_TZ = "America/New_York"
FLATTEN_TIME = dt_time(15, 55)  # force flat on the last RTH bar (15:55 -> 16:00)
LAST_ENTRY_TIME = dt_time(15, 45)  # no fresh entries in the final 10 minutes
TRADING_DAYS_PER_YEAR = 252


# ---------------------------------------------------------------------------
# Data cleaning (robust to a genuine multi-year trend, unlike the global-median
# filter in research/lib which only holds for a ~1yr sample).
# ---------------------------------------------------------------------------
def flag_corrupt_days_local(
    df: pd.DataFrame, *, window: int = 21, max_dev: float = 0.35
) -> list[object]:
    """Flag trade dates whose median price jumps implausibly vs the *local* trend.

    The prior ``flag_corrupt_days`` compares each day to the global median of the
    whole window. Over 2020-2026 SPY genuinely ranges from ~$220 (COVID crash) to
    ~$680, so a global comparison would false-flag real extremes. Instead we compare
    each day's median close to the median of the *previous ``window`` days*; a real
    session almost never moves >35% from its trailing trend (the worst COVID day was
    ~-11%), but a wrong-symbol/mis-adjusted cache segment (e.g. the old June-2026
    bug that printed ~$100 vs ~$750) deviates far more. Pure data hygiene over the
    full history — no lookahead reaches the strategies, which only see the clean frame.
    """
    daily_med = df.groupby("date")["close"].median()
    days = list(daily_med.index)
    values = daily_med.to_numpy()
    bad: list[object] = []
    for i in range(len(days)):
        lo = max(0, i - window)
        # Use the trailing window; for the very first days fall back to the leading one.
        ref = values[lo:i] if i > 0 else values[i + 1 : i + 1 + window]
        if len(ref) == 0:
            continue
        base = float(np.median(ref))
        if base <= 0:
            continue
        if abs(values[i] - base) / base > max_dev:
            bad.append(days[i])
    return bad


# ---------------------------------------------------------------------------
# Indicators (session-aware where relevant).
# ---------------------------------------------------------------------------
def session_vwap(df: pd.DataFrame) -> pd.Series:
    """Volume-weighted average price that resets each trade date.

    VWAP is *the* intraday reference for S&P futures traders. Typical price
    (H+L+C)/3 weighted by volume, accumulated within each session only (a fresh
    VWAP every morning), so it never leaks across the overnight gap.
    """
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    pv = typical * df["volume"]
    cum_pv = pv.groupby(df["date"]).cumsum()
    cum_v = df["volume"].groupby(df["date"]).cumsum()
    vwap = cum_pv / cum_v.replace(0, np.nan)
    # Fill any zero-volume warmup bar with the typical price of that bar.
    return vwap.fillna(typical)


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _rsi(close: pd.Series, window: int = 14) -> pd.Series:
    """Wilder RSI on the continuous close series (warmup NaNs => no early signal)."""
    delta = close.diff()
    up = delta.clip(lower=0.0)
    down = -delta.clip(upper=0.0)
    roll_up = up.ewm(alpha=1.0 / window, adjust=False).mean()
    roll_down = down.ewm(alpha=1.0 / window, adjust=False).mean()
    rs = roll_up / roll_down.replace(0, np.nan)
    return (100.0 - 100.0 / (1.0 + rs)).fillna(50.0)


def hourly_trend_sign(df: pd.DataFrame, *, ema_span: int = 8) -> pd.Series:
    """Higher-timeframe trend sign (+1/-1/0) from resampled hourly bars, lag-safe.

    Resamples the 5-minute closes to 1-hour bars, takes sign(close - EMA(close)),
    and forward-fills that onto the 5-minute grid **shifted one hour** so a given
    bar only ever sees hourly information that was already complete. This is the
    multi-timeframe filter: the 5-minute strategy decides entries, the hourly trend
    decides which direction is allowed.
    """
    # Resample within UTC index; label each hourly bucket by its close.
    hourly_close = df["close"].resample("1h").last().dropna()
    ema = _ema(hourly_close, ema_span)
    sign = np.sign(hourly_close - ema).fillna(0.0)
    # Shift by one hourly bar so the completed hour's trend applies to the *next*
    # hour of 5-minute bars (no lookahead), then align back onto the 5-min index.
    sign_lagged = sign.shift(1).reindex(df.index, method="ffill").fillna(0.0)
    return sign_lagged


# ---------------------------------------------------------------------------
# Long+short signal container and the no-lookahead / EOD-flat finalizer.
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class LSSignals:
    """Boolean entry/exit signals for both directions, aligned to the bar index."""

    entry_long: pd.Series
    exit_long: pd.Series
    entry_short: pd.Series
    exit_short: pd.Series


def _local_times(df: pd.DataFrame) -> pd.Series:
    if "time" in df.columns:
        return df["time"]
    local = df.index.tz_convert(MARKET_TZ)
    return pd.Series(local.time, index=df.index)


def finalize_ls(
    entry_long: pd.Series,
    exit_long: pd.Series,
    entry_short: pd.Series,
    exit_short: pd.Series,
    df: pd.DataFrame,
    *,
    last_entry_time: dt_time = LAST_ENTRY_TIME,
    flatten_time: dt_time = FLATTEN_TIME,
    shift: bool = True,
) -> LSSignals:
    """Apply the shared intraday discipline to raw long/short signals.

    1. **No lookahead** — shift every series forward one bar within its own day so
       execution happens on the *next* bar (a bar you have fully observed). The
       within-day shift stops a late signal leaking across the overnight gap.
    2. **No fresh entries into the close** — block entries at/after ``last_entry_time``.
    3. **Flat by EOD** — force both exit series true at/after ``flatten_time``.
    """
    dates = df["date"]
    if shift:
        entry_long = entry_long.groupby(dates).shift(1, fill_value=False).astype(bool)
        exit_long = exit_long.groupby(dates).shift(1, fill_value=False).astype(bool)
        entry_short = entry_short.groupby(dates).shift(1, fill_value=False).astype(bool)
        exit_short = exit_short.groupby(dates).shift(1, fill_value=False).astype(bool)

    times = _local_times(df)
    late = times >= flatten_time
    can_enter = times < last_entry_time

    entry_long = (entry_long & can_enter).fillna(False)
    entry_short = (entry_short & can_enter).fillna(False)
    exit_long = (exit_long | late).fillna(False)
    exit_short = (exit_short | late).fillna(False)
    return LSSignals(entry_long, exit_long, entry_short, exit_short)


# ---------------------------------------------------------------------------
# Strategy signal generators (the five well-known intraday setups).
# ---------------------------------------------------------------------------
def _opening_range(df: pd.DataFrame, bars: int) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Per-bar opening-range high/low/mid, computed from the first ``bars`` of each day."""
    high, low = df["high"], df["low"]
    dates = df["date"]
    or_high = pd.Series(np.nan, index=df.index)
    or_low = pd.Series(np.nan, index=df.index)
    for _d, g in df.groupby(dates):
        if len(g) < bars:
            continue
        h = high.loc[g.index[:bars]].max()
        low_ = low.loc[g.index[:bars]].min()
        or_high.loc[g.index] = h
        or_low.loc[g.index] = low_
    or_mid = (or_high + or_low) / 2.0
    return or_high, or_low, or_mid


def orb_ls(df: pd.DataFrame, *, opening_range_bars: int = 6) -> LSSignals:
    """Strategy 1 — Opening-Range Breakout, both directions.

    Long on the first close above the first-30-min high; short on the first close
    below the first-30-min low. Exit back through the opening-range midpoint or EOD.
    One entry per side per day. The canonical S&P futures day-trade setup.
    """
    close = df["close"]
    dates = df["date"]
    or_high, or_low, or_mid = _opening_range(df, opening_range_bars)

    raw_long = (close > or_high) & or_high.notna()
    raw_short = (close < or_low) & or_low.notna()
    entry_long = raw_long & (raw_long.groupby(dates).cumsum() == 1)
    entry_short = raw_short & (raw_short.groupby(dates).cumsum() == 1)
    exit_long = ((close <= or_mid) & or_mid.notna()).fillna(False)
    exit_short = ((close >= or_mid) & or_mid.notna()).fillna(False)
    return finalize_ls(entry_long, exit_long, entry_short, exit_short, df)


def vwap_revert_ls(df: pd.DataFrame, *, window: int = 20, k: float = 2.0) -> LSSignals:
    """Strategy 2 — VWAP mean-reversion, both directions.

    Fade stretches away from the session VWAP: go long when price is ``k`` rolling
    standard deviations *below* VWAP (over-sold vs the day's fair value), short when
    ``k`` sigma *above*; exit when price reverts back to VWAP or at EOD. Mean-reversion
    is supported by SPY's slightly negative short-lag 5-minute autocorrelation.
    """
    close = df["close"]
    vwap = session_vwap(df)
    dist = close - vwap
    sd = dist.groupby(df["date"]).transform(lambda s: s.rolling(window).std())
    z = dist / sd.replace(0, np.nan)
    entry_long = (z < -k).fillna(False)
    exit_long = (z >= 0.0).fillna(False)
    entry_short = (z > k).fillna(False)
    exit_short = (z <= 0.0).fillna(False)
    return finalize_ls(entry_long, exit_long, entry_short, exit_short, df)


def rsi_revert_ls(
    df: pd.DataFrame,
    *,
    window: int = 14,
    lower: float = 30.0,
    upper: float = 70.0,
    exit_level: float = 50.0,
) -> LSSignals:
    """Strategy 3 — RSI(14) mean-reversion, both directions.

    Long when RSI is oversold (< ``lower``), short when overbought (> ``upper``),
    exit back through the 50 midline or at EOD. A textbook oscillator reversion.
    """
    rsi = _rsi(df["close"], window)
    entry_long = (rsi < lower).fillna(False)
    exit_long = (rsi > exit_level).fillna(False)
    entry_short = (rsi > upper).fillna(False)
    exit_short = (rsi < exit_level).fillna(False)
    return finalize_ls(entry_long, exit_long, entry_short, exit_short, df)


def ema_cross_ls(df: pd.DataFrame, *, fast: int = 9, slow: int = 21) -> LSSignals:
    """Strategy 4 — EMA(9/21) crossover momentum, both directions.

    Long when the fast EMA crosses above the slow EMA, short when it crosses below;
    the opposite cross is the exit (so the book flips with the trend), plus EOD flat.
    The most common trend-following intraday setup.
    """
    close = df["close"]
    ema_fast = _ema(close, fast)
    ema_slow = _ema(close, slow)
    above = ema_fast > ema_slow
    cross_up = above & ~above.shift(1, fill_value=False)
    cross_dn = ~above & above.shift(1, fill_value=False)
    return finalize_ls(cross_up, cross_dn, cross_dn, cross_up, df)


def vwap_trend_mtf_ls(df: pd.DataFrame, *, ema_span: int = 8) -> LSSignals:
    """Strategy 5 — VWAP re-cross *in the direction of the hourly trend* (multi-timeframe).

    Decision timeframe is 5-minute (a re-cross of the session VWAP), but each entry is
    filtered by the **hourly** trend: only take longs when the hourly close is above its
    EMA, only take shorts when below. Exit when price crosses back through VWAP or at EOD.
    This is the "trade the pullback in the direction of the higher-timeframe trend" play
    that S&P futures day-traders lean on, and it exercises the two-timeframe requirement.
    """
    close = df["close"]
    vwap = session_vwap(df)
    above_vwap = close > vwap
    cross_up = above_vwap & ~above_vwap.shift(1, fill_value=False)  # crossed up through VWAP
    cross_dn = ~above_vwap & above_vwap.shift(1, fill_value=False)  # crossed down through VWAP

    trend = hourly_trend_sign(df, ema_span=ema_span)
    entry_long = cross_up & (trend > 0)
    entry_short = cross_dn & (trend < 0)
    # Exit a long when it falls back below VWAP; exit a short when it climbs back above.
    exit_long = cross_dn.fillna(False)
    exit_short = cross_up.fillna(False)
    return finalize_ls(entry_long, exit_long, entry_short, exit_short, df)


def buy_hold_intraday_ls(df: pd.DataFrame) -> LSSignals:
    """Benchmark — long the first bar each day, flat at the close (intraday beta)."""
    dates = df["date"]
    times = _local_times(df)
    first_bar = ~dates.duplicated(keep="first")
    entry_long = pd.Series(first_bar.to_numpy(), index=df.index) & (times < LAST_ENTRY_TIME)
    false = pd.Series(False, index=df.index)
    return finalize_ls(entry_long, false, false, false, df, shift=False)


# ---------------------------------------------------------------------------
# The MES dollar simulator: turn long/short signals into per-trade futures P&L.
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Trade:
    entry_ts: pd.Timestamp
    exit_ts: pd.Timestamp
    direction: int  # +1 long, -1 short
    entry_index: float  # S&P index points at entry fill
    exit_index: float
    pnl: float  # dollars, net of costs, for the simulated contract count


def simulate_mes(
    df: pd.DataFrame,
    signals: LSSignals,
    *,
    contracts: int = 1,
    commission_scenario: str = "mid",
    slippage_scenario: str = "one",
    stop_frac: float | None = None,
    target_frac: float | None = None,
) -> list[Trade]:
    """Walk the bars, run a flat/long/short state machine, and price each trade in MES $.

    Signals are already shifted forward one bar, so filling at the signal bar's close
    reproduces a realistic next-bar fill. Index points = SPY close x 10; dollar P&L =
    direction x (exit_pts - entry_pts) x $5 x contracts, minus per-side commission and
    minus slippage (``slip_ticks`` x $1.25) charged on both entry and exit.

    Optional **per-trade risk control** (how these setups are really traded, and the
    difference between surviving and liquidating a small futures account):

    - ``stop_frac``: hard stop at ``stop_frac`` of entry price against the position.
      Checked intrabar against each bar's low (long) / high (short); if the bar gaps
      through the stop we fill at the worse of the stop and the bar open.
    - ``target_frac``: profit target at ``target_frac`` of entry price. Checked the
      same way. If a bar hits both, the stop is assumed first (conservative).
    """
    comm = COMMISSION_PER_SIDE[commission_scenario]
    slip_pts = SLIPPAGE_TICKS[slippage_scenario] * TICK_POINTS

    idx = (df["close"] * SPY_TO_INDEX).to_numpy()
    high_idx = (df["high"] * SPY_TO_INDEX).to_numpy()
    low_idx = (df["low"] * SPY_TO_INDEX).to_numpy()
    open_idx = (df["open"] * SPY_TO_INDEX).to_numpy()
    ts = df.index
    el = signals.entry_long.to_numpy()
    xl = signals.exit_long.to_numpy()
    es = signals.entry_short.to_numpy()
    xs = signals.exit_short.to_numpy()

    trades: list[Trade] = []
    pos = 0
    entry_i = 0.0
    entry_t = ts[0]
    stop_px = 0.0
    target_px = 0.0

    def close_trade(i: int, exit_price: float, direction: int) -> None:
        # Slippage worsens both fills: pay up entering, give up exiting.
        eff_entry = entry_i + slip_pts * direction
        eff_exit = exit_price - slip_pts * direction
        gross = direction * (eff_exit - eff_entry) * POINT_VALUE * contracts
        costs = 2.0 * comm * contracts
        trades.append(
            Trade(
                entry_ts=entry_t,
                exit_ts=ts[i],
                direction=direction,
                entry_index=entry_i,
                exit_index=exit_price,
                pnl=gross - costs,
            )
        )

    def open_position(i: int, direction: int) -> None:
        nonlocal pos, entry_i, entry_t, stop_px, target_px
        pos = direction
        entry_i = idx[i]
        entry_t = ts[i]
        if stop_frac is not None:
            stop_px = entry_i * (1.0 - stop_frac) if direction == 1 else entry_i * (1.0 + stop_frac)
        if target_frac is not None:
            target_px = (
                entry_i * (1.0 + target_frac) if direction == 1 else entry_i * (1.0 - target_frac)
            )

    n = len(df)
    for i in range(n):
        # 1) Intrabar stop / target while holding (checked on THIS bar's range, which
        #    is realistic because the entry filled on the prior bar's close).
        if pos == 1 and (stop_frac is not None or target_frac is not None):
            if stop_frac is not None and low_idx[i] <= stop_px:
                fill = min(stop_px, open_idx[i])  # gap-through fills at the open
                close_trade(i, fill, 1)
                pos = 0
            elif target_frac is not None and high_idx[i] >= target_px:
                fill = max(target_px, open_idx[i])
                close_trade(i, fill, 1)
                pos = 0
        elif pos == -1 and (stop_frac is not None or target_frac is not None):
            if stop_frac is not None and high_idx[i] >= stop_px:
                fill = max(stop_px, open_idx[i])
                close_trade(i, fill, -1)
                pos = 0
            elif target_frac is not None and low_idx[i] <= target_px:
                fill = min(target_px, open_idx[i])
                close_trade(i, fill, -1)
                pos = 0

        # 2) Signal exits (processed before entries so an EMA flip can close then re-open).
        if pos == 1 and xl[i]:
            close_trade(i, idx[i], 1)
            pos = 0
        elif pos == -1 and xs[i]:
            close_trade(i, idx[i], -1)
            pos = 0

        # 3) Entries when flat.
        if pos == 0:
            if el[i]:
                open_position(i, 1)
            elif es[i]:
                open_position(i, -1)
    return trades


# ---------------------------------------------------------------------------
# Metrics.
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class MesMetrics:
    label: str
    contracts: int
    commission_scenario: str
    slippage_scenario: str
    n_days: int
    span_days: int
    # Dollar results on the fixed contract count
    total_pnl: float
    ending_equity: float
    total_return_pct: float
    annual_return_pct: float  # avg annual $ P&L / starting equity (non-compounding)
    cagr_pct: float | None  # compounded, treating the equity curve as an account
    # Risk
    sharpe: float | None
    sortino: float | None
    max_drawdown_pct: float | None
    max_drawdown_dollars: float | None
    calmar: float | None
    worst_day_dollars: float | None
    best_day_dollars: float | None
    # Ruin / margin
    would_blow_up: bool  # any single day loss >= (equity - intraday margin) at that point
    min_equity: float
    # Trade stats
    total_trades: int
    trades_per_day: float
    long_trades: int
    short_trades: int
    win_rate_pct: float | None
    profit_factor: float | None
    avg_win: float | None
    avg_loss: float | None
    expectancy: float | None
    per_year: dict[str, float] = field(default_factory=dict)

    def to_row(self) -> dict[str, Any]:
        row = asdict(self)
        row.pop("per_year", None)
        return row


def _safe(x: float) -> float | None:
    f = float(x)
    return None if (np.isnan(f) or np.isinf(f)) else f


def compute_metrics(
    df: pd.DataFrame,
    trades: list[Trade],
    *,
    label: str,
    contracts: int,
    commission_scenario: str,
    slippage_scenario: str,
    init_cash: float = INIT_CASH,
) -> MesMetrics:
    """Aggregate trades into a daily equity curve and a full metric set.

    Because every trade closes intraday, we bucket P&L by exit date to get a clean
    daily return series for Sharpe/drawdown, then build the account equity path as
    ``init_cash + cumulative P&L`` (fixed contract sizing => non-compounding dollars).
    """
    all_dates = sorted(set(df["date"]))
    n_days = len(all_dates)
    span_days = int((df.index.max() - df.index.min()).days)

    daily = pd.Series(0.0, index=pd.Index(all_dates, name="date"))
    for t in trades:
        d = t.exit_ts.tz_convert(MARKET_TZ).date()
        daily.loc[d] = daily.get(d, 0.0) + t.pnl

    equity = init_cash + daily.cumsum()
    total_pnl = float(daily.sum())
    ending = float(equity.iloc[-1]) if len(equity) else init_cash

    # Sharpe/Sortino on daily *dollar* returns relative to starting equity.
    ret = daily / init_cash
    mean, std = ret.mean(), ret.std()
    downside = ret[ret < 0].std()
    sharpe = _safe(mean / std * np.sqrt(TRADING_DAYS_PER_YEAR)) if std and std > 0 else None
    sortino = (
        _safe(mean / downside * np.sqrt(TRADING_DAYS_PER_YEAR))
        if downside and downside > 0
        else None
    )

    # Drawdown on the equity curve.
    running_max = equity.cummax()
    dd = equity - running_max
    dd_pct = dd / running_max
    max_dd_dollars = _safe(dd.min())
    max_dd_pct = _safe(dd_pct.min() * 100)

    years = span_days / 365.25 if span_days else 0.0
    annual_return_pct = (total_pnl / init_cash / years * 100) if years > 0 else 0.0
    cagr = None
    if years > 0 and ending > 0:
        cagr = _safe(((ending / init_cash) ** (1.0 / years) - 1.0) * 100)
    calmar = _safe(annual_return_pct / abs(max_dd_pct)) if max_dd_pct and max_dd_pct < 0 else None

    # Ruin check: at each day, would the day's loss have breached the margin buffer?
    # buffer = current equity - intraday margin required for the held contracts.
    margin_req = INTRADAY_MARGIN_PER_CONTRACT * contracts
    would_blow_up = False
    prev_eq = init_cash
    for d in all_dates:
        buffer = prev_eq - margin_req
        if daily.loc[d] < 0 and (-daily.loc[d]) >= buffer:
            would_blow_up = True
        prev_eq = prev_eq + daily.loc[d]
    min_equity = float(equity.min()) if len(equity) else init_cash

    pnls = np.array([t.pnl for t in trades], dtype=float)
    wins = pnls[pnls > 0]
    losses = pnls[pnls < 0]
    total_trades = len(trades)
    win_rate = _safe(len(wins) / total_trades * 100) if total_trades else None
    gross_win = wins.sum() if len(wins) else 0.0
    gross_loss = -losses.sum() if len(losses) else 0.0
    profit_factor = _safe(gross_win / gross_loss) if gross_loss > 0 else None

    # Per-calendar-year total P&L (regime view).
    per_year: dict[str, float] = {}
    for d in all_dates:
        y = str(d.year)
        per_year[y] = per_year.get(y, 0.0) + float(daily.loc[d])

    return MesMetrics(
        label=label,
        contracts=contracts,
        commission_scenario=commission_scenario,
        slippage_scenario=slippage_scenario,
        n_days=n_days,
        span_days=span_days,
        total_pnl=round(total_pnl, 2),
        ending_equity=round(ending, 2),
        total_return_pct=round(total_pnl / init_cash * 100, 2),
        annual_return_pct=round(annual_return_pct, 2),
        cagr_pct=round(cagr, 2) if cagr is not None else None,
        sharpe=round(sharpe, 2) if sharpe is not None else None,
        sortino=round(sortino, 2) if sortino is not None else None,
        max_drawdown_pct=round(max_dd_pct, 2) if max_dd_pct is not None else None,
        max_drawdown_dollars=round(max_dd_dollars, 2) if max_dd_dollars is not None else None,
        calmar=round(calmar, 2) if calmar is not None else None,
        worst_day_dollars=round(float(daily.min()), 2) if len(daily) else None,
        best_day_dollars=round(float(daily.max()), 2) if len(daily) else None,
        would_blow_up=would_blow_up,
        min_equity=round(min_equity, 2),
        total_trades=total_trades,
        trades_per_day=round(total_trades / n_days, 2) if n_days else 0.0,
        long_trades=int(sum(1 for t in trades if t.direction == 1)),
        short_trades=int(sum(1 for t in trades if t.direction == -1)),
        win_rate_pct=round(win_rate, 1) if win_rate is not None else None,
        profit_factor=round(profit_factor, 2) if profit_factor is not None else None,
        avg_win=round(float(wins.mean()), 2) if len(wins) else None,
        avg_loss=round(float(losses.mean()), 2) if len(losses) else None,
        expectancy=round(float(pnls.mean()), 2) if total_trades else None,
        per_year={k: round(v, 2) for k, v in sorted(per_year.items())},
    )


# Registry of the five strategies + benchmark, by report label.
STRATEGIES: dict[str, Any] = {
    "BENCH buy-open/flat-close": buy_hold_intraday_ls,
    "S1 ORB (long+short)": orb_ls,
    "S2 VWAP mean-reversion": vwap_revert_ls,
    "S3 RSI(14) mean-reversion": rsi_revert_ls,
    "S4 EMA(9/21) momentum": ema_cross_ls,
    "S5 VWAP+hourly-trend (MTF)": vwap_trend_mtf_ls,
}

__all__ = [
    "COMMISSION_PER_SIDE",
    "INIT_CASH",
    "INTRADAY_MARGIN_PER_CONTRACT",
    "POINT_VALUE",
    "SLIPPAGE_TICKS",
    "SPY_TO_INDEX",
    "STRATEGIES",
    "LSSignals",
    "MesMetrics",
    "Trade",
    "compute_metrics",
    "finalize_ls",
    "flag_corrupt_days_local",
    "hourly_trend_sign",
    "session_vwap",
    "simulate_mes",
]
