"""Chart the regime diagnosis: where the gap edge lives, and how filtering to it helps.

Panel 1 — average follow-through (entry→13:00, in the gap direction) by gap-size bucket,
split by era. The edge is concentrated in large gaps (>0.5%) and is present in *both* eras;
small gaps are ~zero in both — i.e. the baseline was trading noise.
Panel 2 — per-year P&L, baseline (gap>0.15%) vs the fix (gap>0.5%). The fix turns the
2016-2019 out-of-sample years from red to (mostly) green while keeping the big trend years.

Run: uv run python research/mes_intraday/make_regime_chart.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

CHARTS_DIR = Path("research/charts")
RESULTS = Path("research/results/mes_regime_diagnosis.json")


def main() -> None:
    CHARTS_DIR.mkdir(parents=True, exist_ok=True)
    d = json.loads(RESULTS.read_text())

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5.2))

    # --- Panel 1: edge (avg continuation bps) by gap-size bucket, by era ------
    buckets = d["gap_bucket_followthrough"]["buckets"]
    labels = [b["bucket"] for b in buckets]
    avg = [b["avg_cont_bps"] for b in buckets]
    # Green only for the large-gap buckets (>0.5%) where the edge is real and stable;
    # the smaller buckets are noise regardless of a lucky positive average.
    colors = ["#27ae60" if b["bucket"].startswith(("0.50", "0.80")) else "#95a5a6" for b in buckets]
    ax1.bar(labels, avg, color=colors)
    ax1.axhline(0, color="black", lw=0.8)
    ax1.axvspan(2.5, 4.5, color="#27ae60", alpha=0.06)
    ax1.set_title(
        "Where the edge lives: gap follow-through (entry→13:00) by gap size\n"
        "grey = no edge (noise we were trading); green = real edge",
        fontsize=10,
    )
    ax1.set_ylabel("Avg continuation in gap direction (bps)")
    ax1.set_xlabel("|overnight gap| bucket")
    ax1.tick_params(axis="x", labelrotation=20)
    # Annotate the "both eras" fact for the >0.5% bucket.
    era = d["gap_bucket_followthrough"]["by_era"]["big_gap_gt_0.5"]
    ax1.text(
        3.5,
        max(avg) * 0.62,
        f">0.5% gap edge\nexists in BOTH eras:\n'16-19 {era['2016-2019']['avg_cont_bps']:+.1f}bps\n"
        f"'20-26 {era['2020-2026']['avg_cont_bps']:+.1f}bps",
        fontsize=8,
        ha="center",
        color="#1e8449",
        weight="bold",
    )
    ax1.grid(True, axis="y", alpha=0.25)

    # --- Panel 2: per-year P&L, baseline vs fix -------------------------------
    fix = d["baseline_vs_fix"]
    base_py = fix[0]["per_year"]
    fix_py = fix[1]["per_year"]
    years = sorted(base_py)
    xb = np.arange(len(years))
    w = 0.4
    ax2.bar(
        xb - w / 2,
        [base_py[y] for y in years],
        w,
        label="baseline gap>0.15%",
        color="#c0392b",
        alpha=0.75,
    )
    ax2.bar(
        xb + w / 2,
        [fix_py[y] for y in years],
        w,
        label="fix: gap>0.5%",
        color="#27ae60",
        alpha=0.85,
    )
    ax2.axhline(0, color="black", lw=0.8)
    ax2.axvspan(-0.5, 3.5, color="#e74c3c", alpha=0.06)  # 2016-2019 OOS region
    ax2.text(
        1.5,
        ax2.get_ylim()[1] * 0.8,
        "2016-2019\n(out-of-sample)",
        ha="center",
        fontsize=8,
        color="#c0392b",
    )
    ax2.set_xticks(xb)
    ax2.set_xticklabels(years, rotation=45, fontsize=8)
    ax2.set_title(
        "Per-year P&L ($, 1 MES): baseline vs the gap>0.5% fix\n"
        "the fix rescues the 2016-2019 years and cuts drawdown (−52%→−28%)",
        fontsize=10,
    )
    ax2.set_ylabel("P&L ($, 1 contract)")
    ax2.legend(loc="upper left", fontsize=8)
    ax2.grid(True, axis="y", alpha=0.25)

    fig.tight_layout()
    out = CHARTS_DIR / "mes_regime_diagnosis.png"
    fig.savefig(out, dpi=120)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
