"""Data-quality validation for the SPY multi-timeframe (swing) cache.

Runs the standard OHLCV hazard checks -- schema, timezone, duplicates, invalid
prices, OHLC integrity, session-coverage consistency, and corruption screening --
across every timeframe the swing track uses (daily, 1-hour, 15-minute). Writes a
JSON report to ``research/results/swing_data_quality.json`` and prints a summary.

Run:
    uv run python research/validate_swing_data.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from research.lib.swing_data import flag_corrupt_days, load_bars_df  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = REPO_ROOT / ".data"
RESULTS_DIR = REPO_ROOT / "research" / "results"

# Expected regular-session bar counts per full trading day, used to spot short
# days (early closes) vs. random mid-session gaps.
EXPECTED_BARS_PER_DAY: dict[str, int] = {"1Hour": 6, "15Min": 26}


def validate_timeframe(df: pd.DataFrame, timeframe: str) -> dict[str, object]:
    """Run all data-quality checks for one timeframe and return a JSON report."""
    report: dict[str, object] = {}
    report["n_bars"] = int(len(df))
    report["columns"] = list(df.columns)
    report["start_local"] = str(df["local_ts"].min())
    report["end_local"] = str(df["local_ts"].max())
    report["index_tz"] = str(df.index.tz)
    report["n_trade_days"] = int(df["date"].nunique())

    # Duplicates (the adapter de-dupes on timestamp; confirm none survive).
    report["duplicate_timestamps"] = int(df.index.duplicated().sum())

    # Invalid prices / OHLC integrity.
    non_positive = (df[["open", "high", "low", "close"]] <= 0).any(axis=1)
    report["non_positive_prices"] = int(non_positive.sum())
    hi_ok = df["high"] >= df[["open", "close", "low"]].max(axis=1)
    lo_ok = df["low"] <= df[["open", "close", "high"]].min(axis=1)
    report["ohlc_high_violations"] = int((~hi_ok).sum())
    report["ohlc_low_violations"] = int((~lo_ok).sum())
    report["negative_volume"] = int((df["volume"] < 0).sum())

    # Session coverage: for intraday frames, how many days are full length?
    per_day = df.groupby("date").size()
    report["bars_per_day_min"] = int(per_day.min())
    report["bars_per_day_median"] = float(per_day.median())
    report["bars_per_day_max"] = int(per_day.max())
    expected = EXPECTED_BARS_PER_DAY.get(timeframe)
    if expected is not None:
        report["full_session_days"] = int((per_day == expected).sum())
        report["short_session_days"] = int((per_day < expected).sum())

    # Implausible single-bar moves.
    ret = df["close"].pct_change()
    report["max_abs_bar_return_pct"] = float(ret.abs().max() * 100)

    # Corruption screen (wrong-symbol / mis-adjusted segments).
    corrupt = flag_corrupt_days(df)
    report["corrupt_days_count"] = len(corrupt)
    report["corrupt_days"] = [str(d) for d in corrupt]

    return report


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    full: dict[str, object] = {}
    for timeframe in ("1Day", "1Hour", "15Min"):
        df = load_bars_df(CACHE_DIR, timeframe=timeframe)
        full[timeframe] = validate_timeframe(df, timeframe)

    out = RESULTS_DIR / "swing_data_quality.json"
    out.write_text(json.dumps(full, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print("=== SPY multi-timeframe data quality ===")
    for tf, rep in full.items():
        r = rep  # type: ignore[assignment]
        print(
            f"{tf}: bars={r['n_bars']} days={r['n_trade_days']} "  # type: ignore[index]
            f"range={r['start_local']}..{r['end_local']} "  # type: ignore[index]
            f"dupes={r['duplicate_timestamps']} ohlc_viol="  # type: ignore[index]
            f"{r['ohlc_high_violations']}/{r['ohlc_low_violations']} "  # type: ignore[index]
            f"corrupt={r['corrupt_days_count']}"  # type: ignore[index]
        )
    print("wrote", out)


if __name__ == "__main__":
    main()
