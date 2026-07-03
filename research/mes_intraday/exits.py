"""Exit-strategy engine for MES intraday — hold the *entry* fixed and vary the *exit*.

Every earlier result used one of three crude exits: a fixed-percent stop/target, the
strategy's own signal cross-back, or the 15:55 EOD flatten. That leaves the entire exit
dimension unexplored — and the data already hinted it matters (ORB wanted wide targets to let
winners run; gap-and-go wanted tight ones). This module makes the exit the variable under study.

It provides one general simulator, :func:`simulate_with_exits`, that takes *entry* signals
(long/short, already no-lookahead-shifted) plus an :class:`ExitPolicy` and manages the trade
with any combination of:

- **Initial stop** — fixed fraction of entry, or ``k x ATR`` (volatility-scaled).
- **Profit target** — fixed fraction, or ``k x ATR``.
- **Trailing stop** — ratcheting, either a fixed fraction below the high-water mark or a
  ``k x ATR`` "chandelier" trail (lets winners run while protecting open profit).
- **Breakeven** — move the stop to entry once price reaches ``+R`` (R = initial stop distance).
- **Partial scale-out** — bank half the position at ``+R`` and trail the rest.
- **Time-of-day exit** — force flat at a chosen time (test whether the edge decays intraday).

All fills/costs reuse the same MES economics as ``lib.py`` ($5/point, tick slippage, per-side
commission), and it returns the same ``Trade`` records so ``compute_metrics`` works unchanged.
Partial exits are emitted as separate ``Trade`` rows (half size each) so P&L and trade stats
aggregate correctly.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from research.mes_intraday.lib import (
    COMMISSION_PER_SIDE,
    POINT_VALUE,
    SLIPPAGE_TICKS,
    SPY_TO_INDEX,
    TICK_POINTS,
    Trade,
)

MARKET_TZ = "America/New_York"
FLATTEN_HOUR, FLATTEN_MIN = 15, 55


def atr_series(df: pd.DataFrame, *, period: int = 14) -> pd.Series:
    """Wilder ATR in SPY price units, one value per bar (continuous series).

    True range = max(high-low, |high-prev_close|, |low-prev_close|), smoothed with
    Wilder's EMA (alpha = 1/period). Computed on the continuous close so an overnight
    gap contributes one wider TR per day — immaterial for a 14-bar average and the
    standard way intraday ATR stops are built. Warmup bars simply produce a slightly
    unstable early ATR; entries rarely fire in the first few minutes anyway.
    """
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(
        axis=1
    )
    return tr.ewm(alpha=1.0 / period, adjust=False).mean()


@dataclass(frozen=True, slots=True)
class ExitPolicy:
    """Declarative exit configuration. Distances are in *fraction of entry price* unless
    the matching ``*_atr`` multiple is set, in which case they are ``k x ATR`` (price units).

    Priority each bar: trailing-stop update -> breakeven check -> stop hit -> target hit ->
    time exit -> EOD flatten. Stop is always checked before target (conservative).
    """

    label: str = "exit"
    # Initial protective stop.
    stop_frac: float | None = None
    stop_atr: float | None = None
    # Profit target (full exit, or the scale-out level if partial is on).
    target_frac: float | None = None
    target_atr: float | None = None
    # Ratcheting trailing stop.
    trail_frac: float | None = None
    trail_atr: float | None = None
    # Move stop to breakeven once price reaches +breakeven_r * initial_risk.
    breakeven_r: float | None = None
    # Scale out half at +scaleout_r * initial_risk, trail the remainder.
    scaleout_r: float | None = None
    # Force flat at/after this local time (HH, MM), independent of the EOD backstop.
    time_exit: tuple[int, int] | None = None


def _fill_costs(comm: str, slip: str) -> tuple[float, float]:
    return COMMISSION_PER_SIDE[comm], SLIPPAGE_TICKS[slip] * TICK_POINTS


def simulate_with_exits(
    df: pd.DataFrame,
    entry_long: pd.Series,
    entry_short: pd.Series,
    policy: ExitPolicy,
    *,
    contracts: int = 1,
    commission_scenario: str = "mid",
    slippage_scenario: str = "one",
    atr_period: int = 14,
) -> list[Trade]:
    """Simulate one long/short book where exits are governed entirely by ``policy``.

    The strategy's own exit signals are intentionally ignored — this isolates the effect
    of the exit rule. An EOD flatten at 15:55 is always the final backstop so nothing is
    ever carried overnight.
    """
    comm, slip_pts = _fill_costs(commission_scenario, slippage_scenario)

    idx = (df["close"] * SPY_TO_INDEX).to_numpy()
    high_idx = (df["high"] * SPY_TO_INDEX).to_numpy()
    low_idx = (df["low"] * SPY_TO_INDEX).to_numpy()
    open_idx = (df["open"] * SPY_TO_INDEX).to_numpy()
    atr_idx = (atr_series(df, period=atr_period) * SPY_TO_INDEX).to_numpy()
    ts = df.index
    local = df.index.tz_convert(MARKET_TZ)
    hours = local.hour.to_numpy()
    minutes = local.minute.to_numpy()
    # Day changes → force any open position flat at the previous bar (safety; EOD handles it).
    dates = df["date"].to_numpy()

    el = entry_long.to_numpy()
    es = entry_short.to_numpy()

    trades: list[Trade] = []
    pos = 0
    entry_i = 0.0
    entry_t = ts[0]
    qty = contracts  # remaining contracts on the open position
    stop_px = 0.0
    target_px = 0.0
    init_risk = 0.0  # initial stop distance in index points
    did_breakeven = False
    did_scaleout = False

    def _emit(i: int, exit_px: float, direction: int, n: int) -> None:
        # Slippage worsens both sides; commission per side per contract.
        eff_entry = entry_i + slip_pts * direction
        eff_exit = exit_px - slip_pts * direction
        gross = direction * (eff_exit - eff_entry) * POINT_VALUE * n
        costs = 2.0 * comm * n
        trades.append(
            Trade(
                entry_ts=entry_t,
                exit_ts=ts[i],
                direction=direction,
                entry_index=entry_i,
                exit_index=exit_px,
                pnl=gross - costs,
            )
        )

    def _open(i: int, direction: int) -> None:
        nonlocal pos, entry_i, entry_t, qty, stop_px, target_px, init_risk
        nonlocal did_breakeven, did_scaleout
        pos = direction
        entry_i = idx[i]
        entry_t = ts[i]
        qty = contracts
        did_breakeven = False
        did_scaleout = False
        a = atr_idx[i]
        # Initial stop distance in points (fixed fraction or ATR multiple).
        if policy.stop_atr is not None:
            dist = policy.stop_atr * a
        elif policy.stop_frac is not None:
            dist = policy.stop_frac * entry_i
        else:
            dist = 0.0
        init_risk = dist
        stop_px = entry_i - dist * direction if dist > 0 else (0.0 if direction == 1 else 1e18)
        # Target.
        if policy.target_atr is not None:
            tdist = policy.target_atr * a
        elif policy.target_frac is not None:
            tdist = policy.target_frac * entry_i
        else:
            tdist = 0.0
        target_px = entry_i + tdist * direction if tdist > 0 else (1e18 if direction == 1 else 0.0)

    n = len(df)
    for i in range(n):
        is_eod = (hours[i] > FLATTEN_HOUR) or (
            hours[i] == FLATTEN_HOUR and minutes[i] >= FLATTEN_MIN
        )
        new_day = i > 0 and dates[i] != dates[i - 1]

        if pos != 0:
            a = atr_idx[i]
            direction = pos

            # 1) Ratchet the trailing stop toward price (chandelier or fixed-fraction).
            if policy.trail_atr is not None or policy.trail_frac is not None:
                if policy.trail_atr is not None:
                    tdist = policy.trail_atr * a
                else:
                    tdist = policy.trail_frac * entry_i  # type: ignore[operator]
                if direction == 1:
                    stop_px = max(stop_px, high_idx[i] - tdist)
                else:
                    stop_px = min(stop_px, low_idx[i] + tdist)

            # 2) Breakeven: once price reaches +R, pull the stop to entry.
            if policy.breakeven_r is not None and not did_breakeven and init_risk > 0:
                trigger = entry_i + direction * policy.breakeven_r * init_risk
                reached = high_idx[i] >= trigger if direction == 1 else low_idx[i] <= trigger
                if reached:
                    stop_px = entry_i if direction == 1 else entry_i
                    did_breakeven = True

            # 3) Partial scale-out: bank half at +R, keep trailing the rest.
            if policy.scaleout_r is not None and not did_scaleout and init_risk > 0 and qty > 1:
                trigger = entry_i + direction * policy.scaleout_r * init_risk
                reached = high_idx[i] >= trigger if direction == 1 else low_idx[i] <= trigger
                if reached:
                    half = qty // 2
                    fill = trigger  # assume the scale target fills at the level
                    _emit(i, fill, direction, half)
                    qty -= half
                    did_scaleout = True

            # 4) Stop hit (intrabar; gap-through fills at the open).
            stopped = (low_idx[i] <= stop_px) if direction == 1 else (high_idx[i] >= stop_px)
            has_stop = (
                init_risk > 0 or policy.trail_atr is not None or policy.trail_frac is not None
            )
            if has_stop and stopped:
                fill = min(stop_px, open_idx[i]) if direction == 1 else max(stop_px, open_idx[i])
                _emit(i, fill, direction, qty)
                pos = 0
                continue

            # 5) Target hit.
            if policy.target_frac is not None or policy.target_atr is not None:
                hit = (high_idx[i] >= target_px) if direction == 1 else (low_idx[i] <= target_px)
                if hit:
                    fill = (
                        max(target_px, open_idx[i])
                        if direction == 1
                        else min(target_px, open_idx[i])
                    )
                    _emit(i, fill, direction, qty)
                    pos = 0
                    continue

            # 6) Time-of-day exit.
            if policy.time_exit is not None:
                th, tm = policy.time_exit
                if (hours[i] > th) or (hours[i] == th and minutes[i] >= tm):
                    _emit(i, idx[i], direction, qty)
                    pos = 0
                    continue

            # 7) EOD flatten backstop (or a stale carry into a new day, which shouldn't happen).
            if is_eod or new_day:
                _emit(i, idx[i], direction, qty)
                pos = 0
                # fall through so a fresh same-bar entry is still possible below

        # Entries only when flat and not at/after the flatten bar.
        if pos == 0 and not is_eod:
            if el[i]:
                _open(i, 1)
            elif es[i]:
                _open(i, -1)

    return trades


# The exit-policy menu compared in the study. Each is a named ExitPolicy.
def exit_menu() -> list[ExitPolicy]:
    """The catalogue of exit strategies benchmarked against the same entries."""
    return [
        ExitPolicy(label="E0 EOD-only (no stop)"),
        ExitPolicy(label="E1 fixed 0.3%/0.6%", stop_frac=0.003, target_frac=0.006),
        ExitPolicy(label="E2 ATR 1.0/2.0", stop_atr=1.0, target_atr=2.0),
        ExitPolicy(label="E3 ATR chandelier 2.0 (let run)", stop_atr=1.5, trail_atr=2.0),
        ExitPolicy(label="E4 fixed trail 0.4%", stop_frac=0.005, trail_frac=0.004),
        ExitPolicy(
            label="E5 breakeven@1R + ATR trail", stop_atr=1.0, breakeven_r=1.0, trail_atr=2.0
        ),
        ExitPolicy(label="E6 scale½@1R + ATR trail", stop_atr=1.0, scaleout_r=1.0, trail_atr=2.0),
        ExitPolicy(label="E7 stop+BE@1R+target 3R", stop_atr=1.0, breakeven_r=1.0, target_atr=3.0),
        ExitPolicy(label="E8 time exit 12:00 (ATR stop)", stop_atr=1.0, time_exit=(12, 0)),
        ExitPolicy(label="E9 time exit 14:00 (ATR stop)", stop_atr=1.0, time_exit=(14, 0)),
    ]


__all__ = ["ExitPolicy", "atr_series", "exit_menu", "simulate_with_exits"]
