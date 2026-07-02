"""Data-quality validation for the SPY 5-minute intraday cache.

Confirms schema, date range, timezone, session coverage, and screens for the
classic intraday data hazards: missing bars, duplicate timestamps, invalid
OHLC relationships, non-positive prices, and abnormal volume. Writes a JSON
report to ``research/results/data_quality.json`` and prints a summary.

Run:
    uv run python research/validate_data.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

# research/ is not part of the uv workspace, so make it importable when run
# as a plain script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from research.lib.data_access import flag_corrupt_days, load_spy_5min  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = REPO_ROOT / ".data"
RESULTS_DIR = REPO_ROOT / "research" / "results"

# Regular NYSE session for 5-minute bars: 9:30 -> 16:00 ET = 78 bars/day.
EXPECTED_BARS_PER_DAY = 78


def validate(df: pd.DataFrame) -> dict[str, object]:
    """Run all data-quality checks and return a JSON-serializable report."""
    report: dict[str, object] = {}

    # --- Schema & basic shape ---------------------------------------------
    report["n_bars"] = int(len(df))
    report["columns"] = list(df.columns)
    report["start_utc"] = str(df.index.min())
    report["end_utc"] = str(df.index.max())
    report["start_local"] = str(df["local_ts"].min())
    report["end_local"] = str(df["local_ts"].max())
    report["index_tz"] = str(df.index.tz)
    report["n_trade_days"] = int(df["date"].nunique())

    # --- Duplicates --------------------------------------------------------
    # The adapter already de-dupes on timestamp; confirm none survive.
    report["duplicate_timestamps"] = int(df.index.duplicated().sum())

    # --- Invalid prices / OHLC integrity ----------------------------------
    non_positive = (df[["open", "high", "low", "close"]] <= 0).any(axis=1)
    report["non_positive_prices"] = int(non_positive.sum())
    # high must be the max and low the min of the bar; violations indicate
    # corrupt bars.
    hi_ok = df["high"] >= df[["open", "close", "low"]].max(axis=1)
    lo_ok = df["low"] <= df[["open", "close", "high"]].min(axis=1)
    report["ohlc_high_violations"] = int((~hi_ok).sum())
    report["ohlc_low_violations"] = int((~lo_ok).sum())
    report["negative_volume"] = int((df["volume"] < 0).sum())
    report["zero_volume_bars"] = int((df["volume"] == 0).sum())

    # --- Session coverage / missing bars ----------------------------------
    per_day = df.groupby("date").size()
    report["bars_per_day_min"] = int(per_day.min())
    report["bars_per_day_max"] = int(per_day.max())
    report["bars_per_day_median"] = float(per_day.median())
    # Full sessions vs short/half days (holidays, early closes).
    full_days = int((per_day == EXPECTED_BARS_PER_DAY).sum())
    report["full_session_days"] = full_days
    report["short_session_days"] = int((per_day < EXPECTED_BARS_PER_DAY).sum())
    report["over_length_days"] = int((per_day > EXPECTED_BARS_PER_DAY).sum())
    # List the short days so we can eyeball them (early closes are expected;
    # random gaps are not).
    short = per_day[per_day < EXPECTED_BARS_PER_DAY]
    report["short_days_detail"] = {str(d): int(n) for d, n in short.items()}

    # --- Intraday gap check: within a session, consecutive 5-min bars -----
    # Count intraday gaps larger than 5 minutes (missing bars mid-session).
    gap_days = 0
    total_intraday_gaps = 0
    for _date, g in df.groupby("date"):
        deltas = g.index.to_series().diff().dropna()
        big = deltas[deltas > pd.Timedelta(minutes=5)]
        if len(big):
            gap_days += 1
            total_intraday_gaps += int(len(big))
    report["days_with_intraday_gaps"] = gap_days
    report["total_intraday_gaps"] = total_intraday_gaps

    # --- Abnormal volume (per-bar, robust z via median/MAD) ---------------
    vol = df["volume"].astype(float)
    med = vol.median()
    mad = (vol - med).abs().median()
    # 1.4826 scales MAD to be a consistent estimator of sigma for normal data.
    robust_sigma = 1.4826 * mad if mad > 0 else vol.std()
    z = (vol - med) / robust_sigma if robust_sigma > 0 else vol * 0
    report["volume_median"] = float(med)
    report["volume_max"] = float(vol.max())
    report["abnormal_volume_bars_z>10"] = int((z > 10).sum())

    # --- Return sanity: implausible 5-min moves ---------------------------
    ret = df["close"].pct_change()
    report["max_abs_5min_return"] = float(ret.abs().max())
    report["bars_return_gt_5pct"] = int((ret.abs() > 0.05).sum())

    # --- Corrupt price-level segments -------------------------------------
    # Detect trade dates whose price level is implausibly far from trend
    # (wrong-symbol / mis-adjusted cache segments). These are quarantined by
    # load_clean_spy_5min before any backtest runs.
    corrupt = flag_corrupt_days(df)
    report["corrupt_days_count"] = len(corrupt)
    report["corrupt_days"] = [str(d) for d in corrupt]
    report["clean_trade_days"] = int(df["date"].nunique() - len(corrupt))

    return report


def main() -> None:
    df = load_spy_5min(CACHE_DIR)
    report = validate(df)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / "data_quality.json"
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print("=== SPY 5-Minute Data Quality ===")
    for k, v in report.items():
        if k in {"short_days_detail"}:
            print(f"{k}: {len(v)} days")  # type: ignore[arg-type]
            continue
        if k == "corrupt_days":
            print(f"{k}: {v}")
            continue
        print(f"{k}: {v}")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
