"""Panel loader + monthly rotation backtest for the ETF momentum study.

Design choices that keep the study honest:

- **No lookahead.** Signals are computed from adjusted closes up to and including
  a month-end date ``t``. The resulting weights are held over the *next* month
  (``t+1`` .. next month-end). Returns for month ``t+1`` never touch the signal
  that selected them. The rebalance trade is priced at the month-end close where
  the signal is known (a mild optimism vs. next-open execution; slippage covers
  it, and we stress it in the cost grid).
- **Adjusted (total-return) prices.** Loaded from the ``adjustment="all"`` cache
  so dividends are included for every asset — essential when ranking bonds and
  REITs against equity.
- **Ragged inception.** XLC starts 2018; an asset is only eligible on dates where
  it has a full lookback window of history. Before that it is simply not ranked.
- **Realistic costs.** Per-rebalance turnover is charged commission + slippage in
  basis points (see ``CostModel``), sized for a small IBKR account.

This is a portfolio-level simulator (cross-sectional monthly rotation), which the
single-asset ``trade_vectorbt`` signal runner cannot express. It is deliberately
simple and auditable: daily equity compounding of the selected sleeve's returns,
minus rebalance costs.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from trade_data import HistoricalBarsRequest, Instrument, LocalMarketDataStore
from trade_data.sessions import get_market_session_config

REPO_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = REPO_ROOT / ".data" / "momentum_adj"
TRADING_DAYS = 252


# --------------------------------------------------------------------------
# Data loading
# --------------------------------------------------------------------------
def load_close_panel(
    symbols: list[str],
    *,
    cache_dir: Path = CACHE_DIR,
    timeframe: str = "1Day",
    session: str = "all",
) -> pd.DataFrame:
    """Load adjusted closes for many symbols into one date x symbol DataFrame.

    Index is tz-naive market dates (UTC bar timestamps floored to date); columns
    are the bare symbols. Missing days (ragged inception) stay NaN.
    """
    store = LocalMarketDataStore(cache_dir)
    series: dict[str, pd.Series] = {}
    for symbol in symbols:
        instrument = Instrument.us_equity(symbol)
        session_config = get_market_session_config(instrument.market)
        req = HistoricalBarsRequest(
            instrument=instrument,
            timeframe=timeframe,
            start_utc=datetime(2000, 1, 1, tzinfo=UTC),
            end_utc=datetime(2100, 1, 1, tzinfo=UTC),
            session=session,
        )
        bars = store.load_bars(req, session_config)
        if not bars:
            raise ValueError(f"no cached bars for {symbol} — run fetch_universe.py")
        idx = (
            pd.to_datetime([b.timestamp_utc for b in bars])
            .tz_convert("America/New_York")
            .normalize()
            .tz_localize(None)
        )
        series[symbol] = pd.Series([b.close for b in bars], index=idx, name=symbol)
    panel = pd.DataFrame(series).sort_index()
    # Collapse any duplicate dates (defensive) and forward nothing across gaps.
    panel = panel[~panel.index.duplicated(keep="last")]
    return panel


# --------------------------------------------------------------------------
# Cost model (small IBKR account)
# --------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class CostModel:
    """Round-trip-agnostic per-side cost in basis points of traded notional.

    IBKR reference for a ~$2,000 account:
    - Commission: fixed $1.00/order = 5 bps on a $2,000 order; tiered ~$0.35 min
      = ~1.75 bps. We default to ``commission_bps=5`` (conservative fixed plan).
    - Slippage on SPY/sector ETFs: ~1 bp (penny spreads). Less-liquid legs (DBC,
      XLC) ~2-3 bps. Default ``slippage_bps=2`` (one-way).

    ``per_side_bps`` is applied to the *notional traded on each side* of a
    rebalance; a full switch out of one ETF into another is 2 sides.
    """

    commission_bps: float = 5.0
    slippage_bps: float = 2.0

    @property
    def per_side_frac(self) -> float:
        return (self.commission_bps + self.slippage_bps) / 10_000.0


# --------------------------------------------------------------------------
# Signals
# --------------------------------------------------------------------------
def month_end_dates(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Last available trading date within each calendar month."""
    s = pd.Series(index, index=index)
    return pd.DatetimeIndex(s.groupby([index.year, index.month]).last().values)


def total_return_momentum(
    panel: pd.DataFrame, lookback_days: int, *, skip_days: int = 0
) -> pd.DataFrame:
    """Trailing total-return momentum: close[t-skip] / close[t-skip-lookback] - 1.

    ``skip_days`` implements the classic 1-month skip (12-1 momentum) to avoid the
    short-term reversal in the most recent weeks. Result aligned to date ``t``.
    """
    shifted = panel.shift(skip_days)
    return shifted / shifted.shift(lookback_days) - 1.0


# --------------------------------------------------------------------------
# Backtest
# --------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class RotationResult:
    equity: pd.Series  # daily equity curve (starts at init_cash)
    weights: pd.DataFrame  # month-start target weights (date x symbol)
    holdings_log: pd.DataFrame  # rebalance log: date, held symbols, turnover, cost
    daily_returns: pd.Series  # net daily returns


def run_rotation(
    panel: pd.DataFrame,
    *,
    lookback_days: int,
    top_k: int,
    skip_days: int = 0,
    absolute_filter: bool = False,
    safe_asset: str | None = None,
    cost: CostModel | None = None,
    init_cash: float = 2_000.0,
    start: str | None = None,
) -> RotationResult:
    """Monthly cross-sectional momentum rotation, equal-weighting the top-K.

    Parameters:
        panel: date x symbol adjusted-close DataFrame (rank candidates only —
            put the ``safe_asset`` in ``panel`` too if used).
        lookback_days: momentum lookback in trading days (~21/mo).
        top_k: number of assets to hold, equal-weighted.
        skip_days: recent days skipped in the momentum window (e.g. 21 = skip 1mo).
        absolute_filter: dual-momentum gate — an asset is only held if its own
            momentum is positive; otherwise its slot rotates to ``safe_asset``.
        safe_asset: symbol to hold when the absolute filter rejects a slot (e.g.
            "SHY" cash proxy or "IEF"/"TLT"). Must be a column in ``panel``.
        cost: CostModel; defaults to CostModel() (5 bp comm + 2 bp slip per side).
        init_cash: starting equity.
        start: optional ISO date to begin the equity curve (signals still use
            full history before it). Trims warmup.
    """
    cost = cost or CostModel()
    if safe_asset is not None and safe_asset not in panel.columns:
        raise ValueError(f"safe_asset {safe_asset!r} not in panel columns")

    daily_ret = panel.pct_change(fill_method=None)
    mom = total_return_momentum(panel, lookback_days, skip_days=skip_days)

    rebal_dates = month_end_dates(panel.index)  # signal computed at these closes
    # Enforce a minimum warmup so early months with no valid momentum are skipped.
    min_hist = lookback_days + skip_days + 1

    # Build target weights held over the month FOLLOWING each rebalance date.
    weight_rows: dict[pd.Timestamp, pd.Series] = {}
    for rd in rebal_dates:
        pos = panel.index.get_loc(rd)
        if pos < min_hist:
            continue
        m = mom.loc[rd].dropna()
        # Rank candidates (exclude the safe asset from the ranking universe so it
        # is only ever held via the absolute-momentum gate, not the ranking).
        if safe_asset is not None:
            m = m.drop(labels=[safe_asset], errors="ignore")
        if m.empty:
            continue
        ranked = m.sort_values(ascending=False)
        chosen = list(ranked.index[:top_k])
        w = pd.Series(0.0, index=panel.columns)
        slot = 1.0 / top_k
        for sym in chosen:
            if absolute_filter and ranked[sym] <= 0.0:
                # Dual-momentum: negative absolute momentum -> go to safe asset.
                if safe_asset is not None:
                    w[safe_asset] += slot
            else:
                w[sym] += slot
        weight_rows[rd] = w

    if not weight_rows:
        raise ValueError("no rebalance dates survived warmup — lookback too long for data")

    weights = pd.DataFrame(weight_rows).T.sort_index()

    # Expand month-end target weights to a daily held-weights frame. Weights set
    # at rebalance close rd apply from the NEXT trading day through the next rd.
    daily_w = pd.DataFrame(0.0, index=panel.index, columns=panel.columns)
    rebal_list = list(weights.index)
    for i, rd in enumerate(rebal_list):
        start_pos = panel.index.get_loc(rd) + 1  # hold begins next day (lag)
        if i + 1 < len(rebal_list):
            end_pos = panel.index.get_loc(rebal_list[i + 1])  # inclusive of next rd
        else:
            end_pos = len(panel.index) - 1
        if start_pos > end_pos:
            continue
        daily_w.iloc[start_pos : end_pos + 1] = weights.loc[rd].values

    # Portfolio daily gross return = sum(weight * asset daily return).
    port_ret = (daily_w * daily_ret).sum(axis=1)

    # Rebalance cost: charged on the day the new weights take effect (start_pos).
    # Turnover = sum(|new_w - old_w|); a full single-asset switch = 2.0.
    cost_series = pd.Series(0.0, index=panel.index)
    turnover_log: list[dict] = []
    prev_w = pd.Series(0.0, index=panel.columns)
    for rd in rebal_list:
        start_pos = panel.index.get_loc(rd) + 1
        if start_pos >= len(panel.index):
            continue
        new_w = weights.loc[rd]
        turnover = float((new_w - prev_w).abs().sum())
        c = turnover * cost.per_side_frac
        eff_date = panel.index[start_pos]
        cost_series.loc[eff_date] += c
        held = [s for s in new_w.index if new_w[s] > 0]
        turnover_log.append(
            {"date": eff_date, "held": ",".join(held), "turnover": turnover, "cost_frac": c}
        )
        prev_w = new_w

    net_ret = port_ret - cost_series

    # Trim to requested start (after signals/costs computed on full history).
    if start is not None:
        mask = panel.index >= pd.Timestamp(start)
        net_ret = net_ret[mask]
        daily_w = daily_w[mask]

    net_ret = net_ret.fillna(0.0)
    equity = init_cash * (1.0 + net_ret).cumprod()

    holdings_log = pd.DataFrame(turnover_log)
    if not holdings_log.empty and start is not None:
        holdings_log = holdings_log[holdings_log["date"] >= pd.Timestamp(start)]

    return RotationResult(
        equity=equity,
        weights=weights,
        holdings_log=holdings_log,
        daily_returns=net_ret,
    )


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class PerfMetrics:
    label: str
    start: str
    end: str
    years: float
    total_return_pct: float
    cagr_pct: float
    ann_vol_pct: float
    sharpe: float
    sortino: float
    max_drawdown_pct: float
    calmar: float
    best_month_pct: float
    worst_month_pct: float
    pct_months_positive: float
    n_rebalances: int
    avg_annual_turnover: float
    exposure_pct: float

    def to_row(self) -> dict:
        return asdict(self)


def _sortino(daily: pd.Series) -> float:
    downside = daily[daily < 0]
    dd = downside.std()
    if dd == 0 or np.isnan(dd):
        return float("nan")
    return float(daily.mean() / dd * np.sqrt(TRADING_DAYS))


def compute_metrics(
    daily_returns: pd.Series,
    equity: pd.Series,
    *,
    label: str,
    holdings_log: pd.DataFrame | None = None,
    daily_weights: pd.DataFrame | None = None,
) -> PerfMetrics:
    """Full metric set from a net daily-return series and equity curve."""
    daily = daily_returns.dropna()
    if daily.empty:
        raise ValueError("empty return series")
    years = len(daily) / TRADING_DAYS
    total_return = float(equity.iloc[-1] / equity.iloc[0] - 1.0)
    cagr = (1.0 + total_return) ** (1.0 / years) - 1.0 if years > 0 else float("nan")
    ann_vol = float(daily.std() * np.sqrt(TRADING_DAYS))
    sharpe = (
        float(daily.mean() / daily.std() * np.sqrt(TRADING_DAYS)) if daily.std() else float("nan")
    )
    sortino = _sortino(daily)

    running_max = equity.cummax()
    dd = equity / running_max - 1.0
    max_dd = float(dd.min())
    calmar = cagr / abs(max_dd) if max_dd < 0 else float("nan")

    monthly = (1.0 + daily).groupby([daily.index.year, daily.index.month]).prod() - 1.0
    best_m = float(monthly.max())
    worst_m = float(monthly.min())
    pct_pos = float((monthly > 0).mean())

    n_rebal = int(len(holdings_log)) if holdings_log is not None else 0
    avg_turnover = float("nan")
    if holdings_log is not None and not holdings_log.empty and years > 0:
        avg_turnover = float(holdings_log["turnover"].sum() / years)
    exposure = float("nan")
    if daily_weights is not None:
        invested = daily_weights.sum(axis=1)
        exposure = float((invested > 0).mean() * 100)

    return PerfMetrics(
        label=label,
        start=str(daily.index[0].date()),
        end=str(daily.index[-1].date()),
        years=round(years, 2),
        total_return_pct=round(total_return * 100, 2),
        cagr_pct=round(cagr * 100, 2),
        ann_vol_pct=round(ann_vol * 100, 2),
        sharpe=round(sharpe, 3),
        sortino=round(sortino, 3),
        max_drawdown_pct=round(max_dd * 100, 2),
        calmar=round(calmar, 3) if not np.isnan(calmar) else float("nan"),
        best_month_pct=round(best_m * 100, 2),
        worst_month_pct=round(worst_m * 100, 2),
        pct_months_positive=round(pct_pos * 100, 1),
        n_rebalances=n_rebal,
        avg_annual_turnover=round(avg_turnover, 2) if not np.isnan(avg_turnover) else float("nan"),
        exposure_pct=round(exposure, 1) if not np.isnan(exposure) else float("nan"),
    )


def run_trend_timed(
    panel: pd.DataFrame,
    *,
    base: str,
    lev: str,
    ma: int,
    safe: str = "BIL",
    cost: CostModel | None = None,
    signal_lag: int = 1,
    init_cash: float = 2_000.0,
    start: str | None = None,
    end: str | None = None,
):
    """Trend-timed leveraged ETF: hold ``lev`` while ``base`` > SMA(``ma``), else ``safe``.

    No lookahead: the position for day ``t`` is decided by the base close vs its
    SMA lagged by ``signal_lag`` days. ``signal_lag=1`` (default) means the signal
    from the prior close drives today's holding (MOC/next-open entry). Increasing
    the lag (e.g. 2) simulates acting a full day late — an execution-delay stress.

    Switching cost = 2 sides * per-side cost, charged on days the position flips.
    Returns (daily_returns, equity, n_switches). Leveraged/decay/expense effects
    are embedded because ``lev`` uses the actual adjusted leveraged-ETF series.
    """
    cost = cost or CostModel()
    base_px = panel[base]
    sma = base_px.rolling(ma).mean()
    long_sig = (base_px > sma).shift(signal_lag).fillna(False).astype(bool)

    lev_ret = panel[lev].pct_change(fill_method=None)
    safe_ret = panel[safe].pct_change(fill_method=None)
    port = pd.Series(
        np.where(long_sig.to_numpy(), lev_ret.to_numpy(), safe_ret.to_numpy()), index=panel.index
    )

    switch = long_sig.astype(int).diff().abs().fillna(0.0)
    port = port - switch * 2.0 * cost.per_side_frac

    mask = pd.Series(True, index=panel.index)
    if start is not None:
        mask &= panel.index >= pd.Timestamp(start)
    if end is not None:
        mask &= panel.index <= pd.Timestamp(end)
    port = port[mask].fillna(0.0)
    equity = init_cash * (1.0 + port).cumprod()
    n_switches = int(switch[mask].sum())
    return port, equity, n_switches


def buy_and_hold(
    panel: pd.DataFrame,
    symbol: str,
    *,
    start: str | None = None,
    end: str | None = None,
    init_cash: float = 2_000.0,
):
    """Benchmark: buy-and-hold a single symbol (adjusted total return)."""
    ret = panel[symbol].pct_change(fill_method=None)
    mask = pd.Series(True, index=panel.index)
    if start is not None:
        mask &= panel.index >= pd.Timestamp(start)
    if end is not None:
        mask &= panel.index <= pd.Timestamp(end)
    ret = ret[mask].fillna(0.0)
    equity = init_cash * (1.0 + ret).cumprod()
    return ret, equity
