from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from kpx.metrics.code_metrics import (
    CodeMetrics,
    CodeMetricsError,
    effective_loc,
    measure_preparation,
    preparation_code_table,
)

TRANSFORMS = '''
"""Shared transformation helpers for the fixture task."""


def parse_price(value):
    return int(value.replace(",", "")) * 10_000


def parse_deal_date(year_month, day):
    return f"{year_month}-{day}"


def normalize_district(value):
    return value.split()[-1]
'''

SILVER = '''
"""The silver condition of the fixture task."""

from t_transforms import parse_price


class Runner:
    TASK = "task01"
    CONDITION = "silver"

    def prepare(self, ctx):
        """Silver is already typed; only the price needs parsing."""
        df = ctx.load("trades")
        # the column is canonical here
        df["price_krw"] = df["price"].map(parse_price)
        return df
'''

BRONZE = '''
"""The bronze condition of the fixture task."""

from t_transforms import normalize_district, parse_deal_date, parse_price


class Runner:
    TASK = "task01"
    CONDITION = "bronze"

    def prepare(self, ctx):
        """Bronze needs every column shaped before analysis can start."""
        df = ctx.load("trades")
        df = self._rename(df)
        df["price_krw"] = df["거래금액"].map(parse_price)
        df["deal_date"] = parse_deal_date(df["계약년월"], df["계약일"])
        df["district"] = df["시군구"].map(normalize_district)
        return _drop_cancelled(df)

    def _rename(self, df):
        """Private helper: counted."""
        return df.rename(columns={"단지명": "apt_name"})


def _drop_cancelled(df):
    if "해제여부" in df.columns:
        return df[df["해제여부"] != "O"]
    return df


def unrelated_public_helper(df):
    """Not reachable from prepare, so not counted."""
    return df.head()
'''


def module_from_source(tmp_path: Path, name: str, source: str) -> ModuleType:
    path = tmp_path / f"{name}.py"
    path.write_text(source, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def transforms(tmp_path: Path) -> ModuleType:
    return module_from_source(tmp_path, "t_transforms", TRANSFORMS)


@pytest.fixture
def silver(tmp_path: Path, transforms: ModuleType) -> ModuleType:
    return module_from_source(tmp_path, "t_silver", SILVER)


@pytest.fixture
def bronze(tmp_path: Path, transforms: ModuleType) -> ModuleType:
    return module_from_source(tmp_path, "t_bronze", BRONZE)


# -- LOC counting rules ----------------------------------------------------


def test_blank_lines_and_comments_do_not_count() -> None:
    source = "def f():\n\n    # a comment\n    return 1\n"
    assert effective_loc(source) == 2


def test_a_docstring_does_not_count() -> None:
    source = 'def f():\n    """Why f exists.\n\n    At length.\n    """\n    return 1\n'
    assert effective_loc(source) == 2


def test_a_statement_spanning_lines_counts_each_line() -> None:
    source = "def f():\n    return dict(\n        a=1,\n        b=2,\n    )\n"
    assert effective_loc(source) == 5


def test_the_def_line_counts() -> None:
    assert effective_loc("def f():\n    return 1\n") == 2


def test_a_string_that_is_not_a_docstring_counts() -> None:
    """Only the leading docstring is exempt."""
    source = 'def f():\n    x = """not a docstring"""\n    return x\n'
    assert effective_loc(source) == 3


# -- what gets measured ----------------------------------------------------


def test_prepare_and_its_private_helpers_are_measured(
    bronze: ModuleType, transforms: ModuleType
) -> None:
    metrics = measure_preparation(bronze.Runner(), transforms=transforms)
    assert metrics.measured == ("prepare", "_drop_cancelled", "_rename")


def test_an_unreachable_public_helper_is_not_measured(
    bronze: ModuleType, transforms: ModuleType
) -> None:
    metrics = measure_preparation(bronze.Runner(), transforms=transforms)
    assert "unrelated_public_helper" not in metrics.measured


def test_shared_transformations_are_counted_but_not_charged(
    bronze: ModuleType, transforms: ModuleType
) -> None:
    """Every condition draws on the same helpers; charging them compresses the RQ2 comparison."""
    metrics = measure_preparation(bronze.Runner(), transforms=transforms)
    assert metrics.transformations == ("normalize_district", "parse_deal_date", "parse_price")
    # the three helper bodies are 6 effective lines that are not in the total
    assert metrics.preprocessing_loc < 20


def test_library_access_is_not_counted(silver: ModuleType, transforms: ModuleType) -> None:
    """ctx.load and .map are not code the condition had to write."""
    metrics = measure_preparation(silver.Runner(), transforms=transforms)
    assert metrics.measured == ("prepare",)


def test_a_transformation_passed_to_a_library_call_is_counted(
    silver: ModuleType, transforms: ModuleType
) -> None:
    """`.map(parse_price)` never calls parse_price — and it is the usual idiom."""
    metrics = measure_preparation(silver.Runner(), transforms=transforms)
    assert metrics.transformations == ("parse_price",)


def test_function_count_covers_helpers_and_transformations(
    bronze: ModuleType, transforms: ModuleType
) -> None:
    metrics = measure_preparation(bronze.Runner(), transforms=transforms)
    assert metrics.function_count == 5  # 2 private helpers + 3 transformations


def test_bronze_costs_more_than_silver(
    bronze: ModuleType, silver: ModuleType, transforms: ModuleType
) -> None:
    """The direction the RQ2 comparison expects, on fixtures written to be honest about it."""
    cheap = measure_preparation(silver.Runner(), transforms=transforms)
    dear = measure_preparation(bronze.Runner(), transforms=transforms)
    assert dear.preprocessing_loc > cheap.preprocessing_loc
    assert dear.function_count > cheap.function_count


def test_a_class_may_be_measured_instead_of_an_instance(
    silver: ModuleType, transforms: ModuleType
) -> None:
    assert measure_preparation(silver.Runner) == measure_preparation(silver.Runner())


def test_transforms_are_optional(silver: ModuleType) -> None:
    """Without the helper module, only private helpers can be attributed."""
    metrics = measure_preparation(silver.Runner())
    assert metrics.transformations == ()
    assert metrics.function_count == 0


def test_recorded_steps_are_carried_through(silver: ModuleType, transforms: ModuleType) -> None:
    metrics = measure_preparation(silver.Runner(), transforms=transforms, steps=4)
    assert metrics.transformation_steps == 4
    assert metrics.to_dict()["transformation_steps"] == 4


def test_to_dict_fills_only_result_schema_fields(
    silver: ModuleType, transforms: ModuleType
) -> None:
    metrics = measure_preparation(silver.Runner(), transforms=transforms)
    assert set(metrics.to_dict()) == {
        "preprocessing_loc",
        "function_count",
        "transformation_steps",
    }


# -- failure modes ---------------------------------------------------------


def test_a_runner_without_prepare_is_refused(tmp_path: Path) -> None:
    module = module_from_source(
        tmp_path, "t_broken", "class Runner:\n    TASK = 'task01'\n    CONDITION = 'gold'\n"
    )
    with pytest.raises(CodeMetricsError, match="does not define prepare"):
        measure_preparation(module.Runner())


def test_a_runner_defined_outside_a_module_is_refused() -> None:
    class Runner:
        TASK = "task01"
        CONDITION = "gold"

        def prepare(self, ctx: object) -> object:
            return ctx

    with pytest.raises(CodeMetricsError, match="not defined at module level"):
        measure_preparation(Runner())


# -- preparation code table -----------------------------------------------


def test_the_table_orders_conditions_in_medallion_order() -> None:
    measurement = CodeMetrics(preprocessing_loc=1, function_count=1)
    table = preparation_code_table(
        {
            ("task01", "monolithic"): measurement,
            ("task01", "gold"): measurement,
            ("task01", "bronze"): measurement,
            ("task01", "silver"): measurement,
        }
    )
    assert list(table["condition"]) == ["bronze", "silver", "gold", "monolithic"]


def test_the_table_carries_every_code_metric() -> None:
    table = preparation_code_table(
        {
            ("task01", "silver"): CodeMetrics(
                preprocessing_loc=18,
                function_count=3,
                transformation_steps=4,
            )
        }
    )
    row = table.iloc[0]
    assert row["preprocessing_loc"] == 18
    assert row["function_count"] == 3
    assert row["transformation_steps"] == 4


def test_the_table_of_nothing_is_empty_but_shaped() -> None:
    table = preparation_code_table({})
    assert table.empty
    assert "preprocessing_loc" in table.columns
