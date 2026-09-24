"""논문 그림을 만든다. 새 측정은 하지 않는다.

**harness 가상환경에서 실행한다** (``--extra figures``의 matplotlib).

    $KPX scripts/paper_figures.py    # -> figures/*.svg, figures/*.png (300 dpi)

- ``experimental_design`` — Source → Bronze → Silver → Gold → Analysis, monolithic 경로,
  S1–S4가 무효화하는 경계, equivalence gate의 위치.
- ``timing_paired_ratio`` — task × engine 네 panel. 시나리오마다 같은 round 쌍 5개의
  ratio(monolithic ÷ materialized)와 그 median, 기준선 1. 쌍은 ``timing_raw_*``에서 다시
  짝짓고, median이 ``timing_comparison.csv``와 같은지 확인한 뒤 그린다.

라벨은 영어다. 한글 글꼴은 기계마다 달라 SVG가 다른 곳에서 깨진다.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd  # noqa: E402
from _paths import EXPERIMENTS  # noqa: E402

RESULTS = EXPERIMENTS / "results"
FIGURES = EXPERIMENTS / "figures"
SCENARIOS = ["S1", "S2", "S3", "S4"]
PANELS = [("task01", "pandas"), ("task01", "polars"), ("task03", "pandas"), ("task03", "polars")]
TASK_LABEL = {"task01": "T1", "task03": "T3"}


def paired_ratios() -> pd.DataFrame:
    raw = pd.concat(
        [pd.read_parquet(RESULTS / f"timing_raw_{e}.parquet") for e in ("pandas", "polars")]
    )
    measured = raw[~raw["warmup"]]
    pairs = measured.pivot_table(
        index=["task", "engine", "scenario", "round"], columns="strategy", values="seconds"
    ).reset_index()
    pairs["ratio"] = pairs["monolithic"] / pairs["materialized"]

    medians = pairs.groupby(["task", "engine", "scenario"])["ratio"].median()
    expected = pd.read_csv(RESULTS / "timing_comparison.csv").set_index(
        ["task", "engine", "scenario"]
    )["median_paired_ratio"]
    if not medians.sort_index().round(9).equals(expected.sort_index().round(9)):
        raise SystemExit("짝지은 ratio의 median이 timing_comparison.csv와 다르다")
    return pairs


def timing_figure(pairs: pd.DataFrame):  # type: ignore[no-untyped-def]
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 2, figsize=(9, 5.6), sharex=True, sharey=True)
    for ax, (task, engine) in zip(axes.flat, PANELS, strict=True):
        cell = pairs[(pairs["task"] == task) & (pairs["engine"] == engine)]
        for y, scenario in enumerate(SCENARIOS):
            ratios = cell.loc[cell["scenario"] == scenario, "ratio"].to_numpy()
            offsets = [(i - (len(ratios) - 1) / 2) * 0.07 for i in range(len(ratios))]
            ax.scatter(ratios, [y + o for o in offsets], s=16, color="#4a6fa5", zorder=3)
            median = float(pd.Series(ratios).median())
            ax.plot([median, median], [y - 0.3, y + 0.3], color="#c0392b", lw=2, zorder=4)
            ax.annotate(
                f"{median:.2f}",
                (median * 1.12, y + 0.3),
                ha="left",
                va="center",
                fontsize=7,
                color="#c0392b",
            )
        ax.axvline(1.0, color="0.3", lw=1, ls="--", zorder=1)
        ax.set_xscale("log")
        ax.set_title(f"{TASK_LABEL[task]} · {engine}", fontsize=10)
        ax.set_yticks(range(len(SCENARIOS)), SCENARIOS)
        ax.set_ylim(len(SCENARIOS) - 0.4, -0.6)
        ax.grid(axis="x", which="major", color="0.9", zorder=0)
    for ax in axes[-1]:
        ax.set_xlabel("monolithic ÷ materialized (same-round pair, log scale)")
    fig.text(
        0.5,
        0.005,
        "> 1: materialized faster · < 1: monolithic faster · dots: 5 pairs · bar: median",
        ha="center",
        fontsize=8,
        color="0.35",
    )
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    return fig


def design_figure():  # type: ignore[no-untyped-def]
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Polygon

    fig, ax = plt.subplots(figsize=(10, 5.2))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 5.6)
    ax.axis("off")

    def box(x: float, y: float, text: str, color: str, w: float = 1.45, h: float = 0.8) -> None:
        ax.add_patch(
            FancyBboxPatch(
                (x - w / 2, y - h / 2),
                w,
                h,
                boxstyle="round,pad=0.02,rounding_size=0.08",
                fc=color,
                ec="0.25",
                lw=1,
            )
        )
        ax.text(x, y, text, ha="center", va="center", fontsize=8.5)

    def arrow(x0: float, y0: float, x1: float, y1: float, style: str = "-") -> None:
        ax.add_patch(
            FancyArrowPatch(
                (x0, y0), (x1, y1), arrowstyle="-|>", mutation_scale=10, lw=1, ls=style, color="0.2"
            )
        )

    top, bottom = 3.2, 1.3
    xs = {"source": 0.85, "bronze": 2.55, "silver": 4.25, "gold": 5.95, "analysis": 7.65}
    box(xs["source"], top, "Source snapshot\n(JSONL, fixed)", "#eeeeee")
    box(xs["bronze"], top, "Bronze\n(Parquet)", "#e9d8c4")
    box(xs["silver"], top, "Silver\n(contract)", "#d9d9e8")
    box(xs["gold"], top, "Gold\n(task aggregate)", "#f3e3a6")
    box(xs["analysis"], top, "Analysis\n(T1 / T3)", "#d5e8d4")
    for a, b in zip(list(xs)[:-1], list(xs)[1:], strict=True):
        arrow(xs[a] + 0.73, top, xs[b] - 0.73, top)
    ax.text(0.1, top + 0.62, "materialized", fontsize=9, style="italic")

    box(
        5.1,
        bottom,
        "Monolithic recomputation\n(Bronze Parquet → analysis, in memory)",
        "#f6f6f6",
        w=3.3,
    )
    arrow(xs["bronze"], top - 0.42, 3.45, bottom + 0.2)
    ax.text(0.1, bottom + 0.55, "monolithic", fontsize=9, style="italic")

    # equivalence gate: 두 경로의 결과가 같아야 비교를 시작한다.
    gx, gy = 9.1, 2.25
    ax.add_patch(
        Polygon(
            [(gx, gy + 0.55), (gx + 0.75, gy), (gx, gy - 0.55), (gx - 0.75, gy)],
            closed=True,
            fc="#ffffff",
            ec="#c0392b",
            lw=1.3,
        )
    )
    ax.text(gx, gy, "equivalence\ngate", ha="center", va="center", fontsize=7.5, color="#c0392b")
    arrow(xs["analysis"] + 0.73, top - 0.1, gx - 0.35, gy + 0.3)
    arrow(6.75, bottom, gx - 0.4, gy - 0.3)

    # S1–S4: 무효화된 층부터 analysis까지가 materialized 경로의 재계산 범위다.
    spans = [
        ("S1 analysis-level", xs["analysis"]),
        ("S2 Gold-level", xs["gold"]),
        ("S3 Silver/contract-level", xs["silver"]),
        ("S4 source-level (post-Bronze)", xs["bronze"]),
    ]
    for i, (label, start) in enumerate(spans):
        y = 4.1 + i * 0.33
        ax.plot([start - 0.6, xs["analysis"] + 0.6], [y, y], color="#4a6fa5", lw=2.2)
        ax.text(start - 0.68, y, label, ha="right", va="center", fontsize=8, color="#4a6fa5")
    ax.text(
        xs["analysis"] + 0.7,
        4.1 + 1.5 * 0.33,
        "recomputed\nby materialized",
        va="center",
        fontsize=7.5,
        color="#4a6fa5",
    )

    ax.text(
        xs["silver"],
        top - 0.55,
        "RQ1: contract-driven\nstandardization",
        ha="center",
        va="top",
        fontsize=7.5,
        color="0.3",
    )
    ax.text(
        xs["silver"],
        0.25,
        "RQ3: rebuild determinism (R1) · source evolution (R2) · perturbation"
        " — at the Silver contract",
        ha="center",
        fontsize=7.5,
        color="0.3",
    )
    ax.text(
        gx,
        gy - 0.7,
        "RQ2: preparation code\nand recomputation cost",
        ha="center",
        va="top",
        fontsize=7.5,
    )
    return fig


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=FIGURES)
    args = parser.parse_args(argv)

    import matplotlib

    matplotlib.use("Agg")
    matplotlib.rcParams["svg.hashsalt"] = "kpubdata-paper"  # SVG id를 실행마다 같게
    matplotlib.rcParams["svg.fonttype"] = "none"
    args.out.mkdir(parents=True, exist_ok=True)

    for name, fig in [
        ("experimental_design", design_figure()),
        ("timing_paired_ratio", timing_figure(paired_ratios())),
    ]:
        fig.savefig(args.out / f"{name}.svg", metadata={"Date": None})
        fig.savefig(args.out / f"{name}.png", dpi=300, metadata={"Software": None})
        print(f"{name}: svg, png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
