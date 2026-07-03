"""Structurally-new intraday mechanisms for MES — approaches NOT tested before in this repo.

The prior tracks all tested *within-session, price-only, single-signal* rules (ORB, VWAP/RSI
reversion, MA-cross momentum). They kept landing on the same wall because they ignored the one
thing the market-structure analysis actually found: **the S&P's return lives overnight and the
intraday move is close to a coin-flip.** So instead of another oscillator, this module tries
mechanisms that use information the earlier rules threw away:

- **N1 gap-and-go** and **N2 gap-fade** — condition the intraday trade on the *overnight gap*
  (prev close → today open), i.e. cross-session structure, not just today's bars.
- **N3 trend-day ride** — classify the *day type* from the first hour (range, gap alignment,
  close location) and only ride momentum to the close on predicted trend days.
- **N4 prior-day-level reversion** — fade extensions beyond *prior-day high/low* (the reference
  levels desk traders actually watch), not a rolling band.
- **N5 volatility-regime switch** — a meta-strategy that runs mean-reversion on quiet mornings
  and momentum on active ones, chosen by the first hour's realized range.
- **N6 volume-climax reversal** — fade a volume-spike exhaustion bar (uses volume, which no
  prior signal did).

Everything reuses the audited MES dollar simulator, the no-lookahead / flat-by-EOD finalizer,
and the same long+short, $2,000-account discipline as ``lib.py`` — only the *entry logic* is new.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from research.mes_intraday.lib import LSSignals, finalize_ls, session_vwap

# The first "hour" of a 5-minute RTH session is 12 bars (09:30-10:30).
FIRST_HOUR_BARS = 12


# ---------------------------------------------------------------------------
# Per-day feature frame (all computed with no lookahead into the trading window).
# ---------------------------------------------------------------------------
def _day_features(df: pd.DataFrame) -> pd.DataFrame:
    """Build one row per trade date with the cross-session / first-hour features.

    Columns (all knowable by 10:30 ET at the latest, so entries placed at/after the
    first hour never peek ahead):

    - ``prev_close`` — prior session's last close (overnight anchor).
    - ``day_open`` — today's first-bar open.
    - ``gap`` — overnight gap = day_open / prev_close - 1.
    - ``prev_high`` / ``prev_low`` — prior session's range (reference levels).
    - ``fh_high`` / ``fh_low`` / ``fh_range`` — first-hour high/low/range fraction.
    - ``fh_close`` — close of the 12th bar (end of first hour).
    - ``fh_loc`` — where fh_close sits in the first-hour range (0=low, 1=high).
    - ``fh_ret`` — first-hour return (day_open -> fh_close).
    """
    g = df.groupby("date")
    day_open = g["open"].first()
    day_close = g["close"].last()
    day_high = g["high"].max()
    day_low = g["low"].min()

    def _fh(col: str, fn: str) -> pd.Series:
        # Aggregate the first FIRST_HOUR_BARS rows of each day.
        return g.apply(lambda x: getattr(x[col].iloc[:FIRST_HOUR_BARS], fn)(), include_groups=False)

    fh_high = _fh("high", "max")
    fh_low = _fh("low", "min")
    fh_close = g.apply(
        lambda x: x["close"].iloc[min(FIRST_HOUR_BARS, len(x)) - 1], include_groups=False
    )

    feats = pd.DataFrame(index=day_open.index)
    feats["day_open"] = day_open
    feats["prev_close"] = day_close.shift(1)
    feats["prev_high"] = day_high.shift(1)
    feats["prev_low"] = day_low.shift(1)
    feats["gap"] = feats["day_open"] / feats["prev_close"] - 1.0
    feats["fh_high"] = fh_high
    feats["fh_low"] = fh_low
    feats["fh_close"] = fh_close
    rng = (fh_high - fh_low).replace(0, np.nan)
    feats["fh_range"] = rng / feats["day_open"]
    feats["fh_loc"] = (fh_close - fh_low) / rng
    feats["fh_ret"] = fh_close / feats["day_open"] - 1.0
    # Rolling 20-day median first-hour range = "normal" morning volatility.
    feats["fh_range_med"] = feats["fh_range"].rolling(20, min_periods=5).median()
    return feats


def _bar_pos(df: pd.DataFrame) -> pd.Series:
    """Zero-based bar index within each trade date (0 = 09:30 bar)."""
    return df.groupby("date").cumcount()


def _broadcast(df: pd.DataFrame, per_day: pd.Series) -> pd.Series:
    """Map a per-day value onto every bar of that day."""
    return df["date"].map(per_day)


def _empty(df: pd.DataFrame) -> pd.Series:
    return pd.Series(False, index=df.index)


# ---------------------------------------------------------------------------
# N1 — Overnight gap-and-go (momentum continuation of the overnight drift).
# ---------------------------------------------------------------------------
def gap_and_go(df: pd.DataFrame, *, gap_thr: float = 0.0015, entry_bar: int = 1) -> LSSignals:
    """Ride the overnight gap when the first bar confirms its direction.

    If the gap exceeds ``gap_thr`` and the opening bar closes in the gap's direction
    (the market is following through, not fading), enter in the gap direction just
    after the open and hold to EOD (or a stop applied by the simulator). This exploits
    the documented overnight drift bleeding into the cash session — cross-session info
    that no prior within-session rule used.
    """
    feats = _day_features(df)
    pos = _bar_pos(df)
    gap = _broadcast(df, feats["gap"])
    day_open = _broadcast(df, feats["day_open"])

    # First-bar follow-through: sign of (first bar close - open) matches the gap.
    first_close = _broadcast(df, df.groupby("date")["close"].first())
    confirm_up = (gap > gap_thr) & (first_close > day_open)
    confirm_dn = (gap < -gap_thr) & (first_close < day_open)

    at_entry = pos == entry_bar
    entry_long = (at_entry & confirm_up).fillna(False)
    entry_short = (at_entry & confirm_dn).fillna(False)
    return finalize_ls(entry_long, _empty(df), entry_short, _empty(df), df)


# ---------------------------------------------------------------------------
# N2 — Gap fade (revert an over-extended overnight gap back toward prior close).
# ---------------------------------------------------------------------------
def gap_fade(df: pd.DataFrame, *, gap_thr: float = 0.004, entry_bar: int = 1) -> LSSignals:
    """Fade a large overnight gap, targeting the prior close.

    A big gap with no news often round-trips. If the gap is large (> ``gap_thr``),
    short the open (gap up) / buy the open (gap down); exit when price reverts to the
    prior close, or at EOD. Explicit level-based exit (not a fixed fraction).
    """
    feats = _day_features(df)
    pos = _bar_pos(df)
    gap = _broadcast(df, feats["gap"])
    prev_close = _broadcast(df, feats["prev_close"])
    close = df["close"]

    at_entry = pos == entry_bar
    entry_short = (at_entry & (gap > gap_thr)).fillna(False)  # gap up -> fade down
    entry_long = (at_entry & (gap < -gap_thr)).fillna(False)  # gap down -> fade up
    # Exit when the gap has closed (price back to prior close).
    exit_short = (close <= prev_close).fillna(False)
    exit_long = (close >= prev_close).fillna(False)
    return finalize_ls(entry_long, exit_long, entry_short, exit_short, df)


# ---------------------------------------------------------------------------
# N3 — Trend-day detector, then ride to the close.
# ---------------------------------------------------------------------------
def trend_day_ride(
    df: pd.DataFrame,
    *,
    loc_thr: float = 0.7,
    range_mult: float = 1.2,
    entry_bar: int = FIRST_HOUR_BARS,
) -> LSSignals:
    """Classify the day from its first hour; on a predicted trend day, ride to the close.

    Trend-day fingerprint: the first hour has an above-normal range *and* closes near
    its extreme (``fh_loc`` high for up, low for down) — the market picked a direction
    and held it. On those days only, enter at the end of the first hour in that
    direction and hold to EOD. Range days (the majority) are skipped entirely, which
    is the point: it trades rarely and only when continuation is likely.
    """
    feats = _day_features(df)
    pos = _bar_pos(df)
    fh_loc = _broadcast(df, feats["fh_loc"])
    fh_range = _broadcast(df, feats["fh_range"])
    fh_range_med = _broadcast(df, feats["fh_range_med"])
    gap = _broadcast(df, feats["gap"])

    wide = fh_range > (range_mult * fh_range_med)
    up_day = wide & (fh_loc > loc_thr) & (gap >= 0)  # strong close-high, not fighting the gap
    dn_day = wide & (fh_loc < (1.0 - loc_thr)) & (gap <= 0)

    at_entry = pos == entry_bar
    entry_long = (at_entry & up_day).fillna(False)
    entry_short = (at_entry & dn_day).fillna(False)
    return finalize_ls(entry_long, _empty(df), entry_short, _empty(df), df)


# ---------------------------------------------------------------------------
# N4 — Prior-day-level mean reversion.
# ---------------------------------------------------------------------------
def prior_level_revert(df: pd.DataFrame, *, ext_thr: float = 0.0015) -> LSSignals:
    """Fade extensions beyond the prior day's high/low back into the range.

    Desk traders treat yesterday's high/low as magnets. When today's price pokes
    ``ext_thr`` above the prior-day high, short (bet the poke fails); below the
    prior-day low, buy. Exit back inside the prior range (through the level) or EOD.
    A different reference set than the session VWAP band tested before.
    """
    feats = _day_features(df)
    prev_high = _broadcast(df, feats["prev_high"])
    prev_low = _broadcast(df, feats["prev_low"])
    close = df["close"]

    entry_short = (close > prev_high * (1.0 + ext_thr)).fillna(False)
    exit_short = (close <= prev_high).fillna(False)
    entry_long = (close < prev_low * (1.0 - ext_thr)).fillna(False)
    exit_long = (close >= prev_low).fillna(False)
    return finalize_ls(entry_long, exit_long, entry_short, exit_short, df)


# ---------------------------------------------------------------------------
# N5 — Volatility-regime switch (meta-strategy).
# ---------------------------------------------------------------------------
def vol_regime_switch(df: pd.DataFrame, *, gap_thr: float = 0.0015) -> LSSignals:
    """Run momentum on active mornings and mean-reversion on quiet ones.

    If the first-hour range is above its 20-day median (an "active" day), trade the
    gap-and-go momentum leg; otherwise (a "quiet" day) fade stretches from the session
    VWAP. One adaptive book instead of committing to a single regime — the prior
    single-signal tests could only ever be right in one regime.
    """
    feats = _day_features(df)
    fh_range = _broadcast(df, feats["fh_range"])
    fh_range_med = _broadcast(df, feats["fh_range_med"])
    active = (fh_range > fh_range_med).fillna(False)

    momo = gap_and_go(df, gap_thr=gap_thr)  # already finalized
    # Quiet-day mean reversion: fade distance from session VWAP.
    vwap = session_vwap(df)
    dist = df["close"] - vwap
    sd = dist.groupby(df["date"]).transform(lambda s: s.rolling(20).std())
    z = (dist / sd.replace(0, np.nan)).fillna(0.0)
    rev = finalize_ls((z < -2.0), (z >= 0.0), (z > 2.0), (z <= 0.0), df)

    # Gate each leg by the regime (active -> momentum, quiet -> reversion).
    el = (momo.entry_long & active) | (rev.entry_long & ~active)
    es = (momo.entry_short & active) | (rev.entry_short & ~active)
    xl = (momo.exit_long & active) | (rev.exit_long & ~active)
    xs = (momo.exit_short & active) | (rev.exit_short & ~active)
    # Signals are already finalized; combine without re-shifting.
    return LSSignals(el.fillna(False), xl.fillna(False), es.fillna(False), xs.fillna(False))


# ---------------------------------------------------------------------------
# N6 — Volume-climax reversal.
# ---------------------------------------------------------------------------
def volume_climax_revert(
    df: pd.DataFrame, *, vol_mult: float = 3.0, ret_thr: float = 0.001
) -> LSSignals:
    """Fade a volume-spike exhaustion bar.

    When a bar's volume is ``vol_mult`` times the day's running-average bar volume
    *and* the bar moved sharply, bet on short-term exhaustion: short a volume-spike up
    bar, buy a volume-spike down bar. Exit on the next VWAP touch or EOD. Uses volume
    — an input none of the prior price-only signals looked at.
    """
    close = df["close"]
    vol = df["volume"]
    ret = close.groupby(df["date"]).pct_change()
    avg_vol = vol.groupby(df["date"]).transform(lambda s: s.expanding().mean())
    spike = vol > (vol_mult * avg_vol)

    entry_short = (spike & (ret > ret_thr)).fillna(False)
    entry_long = (spike & (ret < -ret_thr)).fillna(False)
    vwap = session_vwap(df)
    exit_short = (close <= vwap).fillna(False)
    exit_long = (close >= vwap).fillna(False)
    return finalize_ls(entry_long, exit_long, entry_short, exit_short, df)


NOVEL_STRATEGIES = {
    "N1 gap-and-go (overnight momentum)": gap_and_go,
    "N2 gap-fade to prior close": gap_fade,
    "N3 trend-day ride-to-close": trend_day_ride,
    "N4 prior-day-level reversion": prior_level_revert,
    "N5 vol-regime switch (meta)": vol_regime_switch,
    "N6 volume-climax reversal": volume_climax_revert,
}

__all__ = [
    "NOVEL_STRATEGIES",
    "gap_and_go",
    "gap_fade",
    "prior_level_revert",
    "trend_day_ride",
    "vol_regime_switch",
    "volume_climax_revert",
]
