from __future__ import annotations

import pytest

from kpx.metrics.reproducibility import (
    BuildOutcome,
    ReproducibilityError,
    measure_reproducibility,
    reproducibility_table,
)


def ok(
    digest: str = "a" * 64, rows: int = 233_596, schema: tuple[str, ...] = ("a", "b")
) -> BuildOutcome:
    return BuildOutcome(status="ok", output_digest=digest, row_count=rows, schema=schema)


def failed() -> BuildOutcome:
    return BuildOutcome(status="failed", output_digest=None, row_count=None, schema=None)


class TestBuildSuccessRate:
    def test_all_successful(self) -> None:
        assert measure_reproducibility([ok()] * 10).build_success_rate == 1.0

    def test_counts_failures(self) -> None:
        assert measure_reproducibility([ok()] * 8 + [failed()] * 2).build_success_rate == 0.8

    def test_no_builds_is_an_error(self) -> None:
        with pytest.raises(ReproducibilityError, match="no builds"):
            measure_reproducibility([])


class TestEquality:
    def test_identical_builds_are_equal_on_every_axis(self) -> None:
        report = measure_reproducibility([ok()] * 10)

        assert report.digest_equality is True
        assert report.row_count_equality is True
        assert report.schema_equality is True
        assert report.distinct_digests == 1

    def test_a_differing_digest_breaks_equality_and_is_counted(self) -> None:
        report = measure_reproducibility([ok()] * 9 + [ok(digest="b" * 64)])

        assert report.digest_equality is False
        assert report.distinct_digests == 2

    def test_row_count_and_schema_are_separate_axes(self) -> None:
        report = measure_reproducibility([ok(), ok(rows=233_595)])

        assert report.row_count_equality is False
        assert report.schema_equality is True


class TestFailedBuildsDoNotManufactureEquality:
    """실패한 빌드는 산출물이 없다. 그걸 "같다"로 세면 안 된다.

    9회 실패하고 1회 성공한 실행은 digest가 1종이지만, 그건 결정적이라는 증거가
    아니라 비교할 것이 없다는 뜻이다.
    """

    def test_failed_builds_are_excluded_from_the_comparison(self) -> None:
        report = measure_reproducibility([ok(), ok(), failed()])

        assert report.digest_equality is True
        assert report.successes == 2

    def test_a_single_success_yields_no_equality_verdict(self) -> None:
        report = measure_reproducibility([ok()] + [failed()] * 9)

        assert report.digest_equality is None
        assert report.build_success_rate == 0.1

    def test_no_successes_yields_no_equality_verdict(self) -> None:
        assert measure_reproducibility([failed()] * 3).digest_equality is None


class TestTable5:
    def test_one_row_per_condition_with_success_rate_beside_equality(self) -> None:
        frame = reproducibility_table(
            {
                "medallion": measure_reproducibility([ok()] * 10),
                "monolithic": measure_reproducibility([ok()] * 9 + [failed()]),
            }
        )

        assert list(frame["Condition"]) == ["medallion", "monolithic"]
        assert list(frame.columns) == [
            "Condition",
            "Builds",
            "Success rate",
            "Distinct digests",
            "SHA-256 equal",
            "Rows equal",
            "Schema equal",
        ]

    def test_a_condition_with_no_verdict_prints_a_dash_not_false(self) -> None:
        frame = reproducibility_table({"monolithic": measure_reproducibility([failed()] * 3)})

        assert frame.loc[0, "SHA-256 equal"] == "—"
