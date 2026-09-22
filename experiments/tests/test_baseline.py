from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import numpy as np
import pandas as pd
import pytest

from kpx.baseline import (
    BaselineBiasError,
    EquivalenceReport,
    assert_reuses_transforms,
    check_baseline_equivalence,
    compare_frames,
    redefined_transforms,
)
from kpx.contract import AnalysisInput, RunContext


class FakeResolver:
    def __init__(self, frames: dict[tuple[str, str], pd.DataFrame]) -> None:
        self.frames = frames

    def load(self, dataset: str, layer: str) -> pd.DataFrame:
        return self.frames[(dataset, layer)].copy()

    def path(self, dataset: str, layer: str) -> str:
        return f"/fake/{layer}/{dataset}.parquet"


BRONZE = pd.DataFrame(
    {
        "시군구": ["서울특별시 종로구", "서울특별시 중구"],
        "거래금액": ["120,000", "95,500"],
    }
)

GOLD = pd.DataFrame(
    {"district_name": ["종로구", "중구"], "price_krw": [1_200_000_000, 955_000_000]}
)


def make_ctx(**kwargs: object) -> RunContext:
    frames = {("trades", "bronze"): BRONZE, ("trades", "gold"): GOLD}
    defaults: dict[str, object] = {
        "task": "task01",
        "condition": "gold",
        "run_id": "r1",
        "snapshot_id": "s1",
        "pipeline_version": "0.1.0",
        "datasets": FakeResolver(frames),
    }
    defaults.update(kwargs)
    return RunContext(**defaults)  # type: ignore[arg-type]


class GoldRunner:
    TASK = "task01"
    CONDITION = "gold"

    def prepare(self, ctx: RunContext) -> AnalysisInput:
        return AnalysisInput(frame=ctx.load("trades"))


class MonolithicRunner:
    """Reaches the same analysis input from Bronze in one pass."""

    TASK = "task01"
    CONDITION = "monolithic"

    def prepare(self, ctx: RunContext) -> AnalysisInput:
        df = ctx.load("trades")
        frame = pd.DataFrame(
            {
                "district_name": df["시군구"].str.split().str[-1],
                "price_krw": df["거래금액"].str.replace(",", "").astype("int64") * 10_000,
            }
        )
        return AnalysisInput(frame=frame)


def module_from_source(tmp_path: Path, name: str, source: str) -> ModuleType:
    """Import ``source`` as a real module, so ``inspect.getsource`` can read it."""
    path = tmp_path / f"{name}.py"
    path.write_text(source, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# -- compare_frames --------------------------------------------------------


def test_identical_frames_are_equivalent() -> None:
    assert compare_frames(GOLD, GOLD.copy()) == []


def test_row_and_column_order_are_not_differences() -> None:
    """The analysis reads columns by name; neither ordering is semantic."""
    shuffled = GOLD.iloc[::-1][["price_krw", "district_name"]]
    assert compare_frames(GOLD, shuffled) == []


def test_missing_column_is_reported() -> None:
    (difference,) = compare_frames(GOLD, GOLD.drop(columns=["price_krw"]))
    assert difference.kind == "columns"
    assert "missing price_krw" in difference.detail


def test_extra_column_is_reported() -> None:
    baseline = GOLD.assign(surprise=[1, 2])
    kinds = [(d.kind, d.detail) for d in compare_frames(GOLD, baseline)]
    assert ("columns", "baseline adds surprise") in kinds


def test_row_count_difference_short_circuits() -> None:
    """Rows cannot be aligned, so per-column diffs would be noise."""
    (difference,) = compare_frames(GOLD, GOLD.head(1))
    assert difference.kind == "row_count"
    assert "1 rows, reference has 2" in difference.detail


def test_value_difference_reports_count_and_sample() -> None:
    baseline = GOLD.copy()
    baseline.loc[0, "price_krw"] = 1
    (difference,) = compare_frames(GOLD, baseline, key=["district_name"])
    assert difference.kind == "values"
    assert difference.column == "price_krw"
    assert "1 of 2 differ" in difference.detail
    assert "1200000000" in difference.detail


def test_int_and_float_storage_of_equal_values_agree() -> None:
    assert compare_frames(GOLD, GOLD.astype({"price_krw": "float64"})) == []


def test_string_and_object_storage_of_equal_values_agree() -> None:
    """Which of the two a column gets depends on pandas, not on the pipeline."""
    reference = pd.DataFrame({"district_name": pd.Series(["종로구"], dtype="str")})
    baseline = pd.DataFrame({"district_name": pd.Series(["종로구"], dtype="object")})
    assert compare_frames(reference, baseline) == []


def test_boolean_against_numeric_is_a_difference() -> None:
    reference = pd.DataFrame({"k": ["a"], "matched": [True]})
    baseline = pd.DataFrame({"k": ["a"], "matched": [1]})
    (difference,) = compare_frames(reference, baseline, key=["k"])
    assert difference.kind == "dtype"
    assert difference.column == "matched"


def test_dtype_difference_is_reported_for_non_numeric() -> None:
    reference = pd.DataFrame({"deal_date": pd.to_datetime(["2024-01-02"])})
    baseline = pd.DataFrame({"deal_date": ["2024-01-02"]})
    (difference,) = compare_frames(reference, baseline)
    assert difference.kind == "dtype"
    assert difference.column == "deal_date"


def test_missing_values_in_the_same_place_are_equal() -> None:
    frame = pd.DataFrame({"k": ["a", "b"], "v": [1.0, np.nan], "s": ["x", None]})
    assert compare_frames(frame, frame.copy(), key=["k"]) == []


def test_missing_value_against_a_value_is_a_difference() -> None:
    reference = pd.DataFrame({"k": ["a"], "v": [np.nan]})
    baseline = pd.DataFrame({"k": ["a"], "v": [0.0]})
    (difference,) = compare_frames(reference, baseline, key=["k"])
    assert difference.column == "v"


def test_tolerance_is_exact_by_default_and_can_be_relaxed() -> None:
    reference = pd.DataFrame({"k": ["a"], "v": [1.0]})
    baseline = pd.DataFrame({"k": ["a"], "v": [1.0 + 1e-12]})
    assert compare_frames(reference, baseline, key=["k"])
    assert compare_frames(reference, baseline, key=["k"], rtol=1e-9) == []


def test_duplicate_keys_are_reported_rather_than_aligned() -> None:
    reference = pd.DataFrame({"k": ["a", "a"], "v": [1, 2]})
    baseline = pd.DataFrame({"k": ["a", "a"], "v": [2, 1]})
    (difference,) = compare_frames(reference, baseline, key=["k"])
    assert difference.kind == "ordering"
    assert "1 duplicate key" in difference.detail


def test_key_column_absent_from_both_frames_is_reported() -> None:
    (difference,) = compare_frames(GOLD, GOLD.copy(), key=["year_month"])
    assert difference.kind == "columns"
    assert "year_month" in difference.detail


# -- check_baseline_equivalence -------------------------------------------


def test_baseline_matching_the_medallion_path_passes() -> None:
    report = check_baseline_equivalence(
        GoldRunner(), MonolithicRunner(), make_ctx(), key=["district_name"]
    )
    assert report.ok
    report.raise_for_status()
    assert "equivalent" in str(report)


def test_each_runner_reads_its_own_layer() -> None:
    """Gold reads Gold, monolithic reads Bronze — from the same context."""
    ctx = make_ctx(condition="bronze")
    report = check_baseline_equivalence(
        GoldRunner(), MonolithicRunner(), ctx, key=["district_name"]
    )
    assert report.reference == "gold"
    assert report.baseline == "monolithic"
    assert report.ok


def test_a_baseline_that_drops_rows_fails() -> None:
    class Truncating(MonolithicRunner):
        def prepare(self, ctx: RunContext) -> AnalysisInput:
            prepared = super().prepare(ctx)
            return AnalysisInput(frame=prepared.frame.head(1))

    report = check_baseline_equivalence(GoldRunner(), Truncating(), make_ctx())
    assert not report.ok
    with pytest.raises(BaselineBiasError, match="row_count"):
        report.raise_for_status()


def test_a_baseline_that_transforms_differently_fails() -> None:
    """A divergent parse is what the check exists to catch."""

    class WrongUnit(MonolithicRunner):
        def prepare(self, ctx: RunContext) -> AnalysisInput:
            prepared = super().prepare(ctx)
            prepared.frame["price_krw"] = prepared.frame["price_krw"] // 10_000
            return prepared

    report = check_baseline_equivalence(
        GoldRunner(), WrongUnit(), make_ctx(), key=["district_name"]
    )
    assert [d.column for d in report.differences] == ["price_krw"]


def test_comparing_runners_from_different_tasks_is_refused() -> None:
    class OtherTask(MonolithicRunner):
        TASK = "task03"

    with pytest.raises(ValueError, match="different tasks"):
        check_baseline_equivalence(GoldRunner(), OtherTask(), make_ctx())


def test_report_renders_every_difference() -> None:
    report = EquivalenceReport(
        task="task01",
        reference="gold",
        baseline="monolithic",
        reference_rows=2,
        baseline_rows=2,
        differences=compare_frames(GOLD, GOLD.drop(columns=["price_krw"])),
    )
    rendered = str(report)
    assert "1 difference(s)" in rendered
    assert "missing price_krw" in rendered


# -- shared transformation helpers ----------------------------------------


TRANSFORMS = """
import re


def parse_price(value):
    return int(value.replace(",", "")) * 10_000


def normalize_district(value):
    return value.split()[-1]


CANONICAL_COLUMNS = ("district_name", "price_krw")


def _private(value):
    return value
"""


def test_a_baseline_that_imports_the_helpers_passes(tmp_path: Path) -> None:
    transforms = module_from_source(tmp_path, "t_transforms_ok", TRANSFORMS)
    baseline = module_from_source(
        tmp_path,
        "t_monolithic_ok",
        "from t_transforms_ok import normalize_district, parse_price\n"
        "\n"
        "def prepare(ctx):\n"
        "    return _rows(ctx)\n"
        "\n"
        "def _rows(ctx):\n"
        "    return [normalize_district(x) for x in ctx]\n",
    )
    assert redefined_transforms(baseline, transforms) == ()
    assert_reuses_transforms(baseline, transforms)


def test_a_baseline_that_reimplements_a_helper_fails(tmp_path: Path) -> None:
    transforms = module_from_source(tmp_path, "t_transforms_bad", TRANSFORMS)
    baseline = module_from_source(
        tmp_path,
        "t_monolithic_bad",
        "def parse_price(value):\n"
        "    return int(float(value.replace(',', '')))\n"
        "\n"
        "def prepare(ctx):\n"
        "    return ctx\n",
    )
    assert redefined_transforms(baseline, transforms) == ("parse_price",)
    with pytest.raises(BaselineBiasError, match="redefines parse_price"):
        assert_reuses_transforms(baseline, transforms)


def test_orchestration_helpers_are_allowed(tmp_path: Path) -> None:
    """The baseline's own plumbing is its preparation cost, and RQ2 counts it."""
    transforms = module_from_source(tmp_path, "t_transforms_orch", TRANSFORMS)
    baseline = module_from_source(
        tmp_path,
        "t_monolithic_orch",
        "def _join_and_aggregate(left, right):\n"
        "    return left\n"
        "\n"
        "def prepare(ctx):\n"
        "    return _join_and_aggregate(ctx, ctx)\n",
    )
    assert_reuses_transforms(baseline, transforms)


def test_imported_names_are_not_counted_as_redefinitions(tmp_path: Path) -> None:
    """`re` is imported by transforms.py but defined elsewhere."""
    transforms = module_from_source(tmp_path, "t_transforms_imp", TRANSFORMS)
    baseline = module_from_source(tmp_path, "t_monolithic_imp", "import re\n")
    assert redefined_transforms(baseline, transforms) == ()
