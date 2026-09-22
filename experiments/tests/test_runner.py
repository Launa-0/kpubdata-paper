"""Running one condition of one task end to end (#13).

The harness had every measurement piece — the contract, the step recorder, code
metrics, the runtime protocol, the result store — and no path that drove them.
These tests fix that path: what a run measures, what it records, and what it
does when preparation fails.
"""

from __future__ import annotations

from types import ModuleType

import pandas as pd
import pytest

from kpx.contract import AnalysisInput, AnalysisOutput, RunContext
from kpx.runner import Task, run_condition


class _Resolver:
    """A dataset resolver backed by frames held in memory."""

    def __init__(self, frames: dict[str, pd.DataFrame]) -> None:
        self._frames = frames

    def load(self, dataset: str, layer: str) -> pd.DataFrame:
        return self._frames[layer].copy()

    def path(self, dataset: str, layer: str) -> str:
        return f"memory://{dataset}/{layer}"


class _SilverRunner:
    TASK = "task00"
    CONDITION = "silver"

    def prepare(self, ctx: RunContext) -> AnalysisInput:
        frame = ctx.load("demo")
        with ctx.step("drop_invalid"):
            frame = frame[frame["price"] > 0]
        return AnalysisInput(frame=frame)


def _analyze(prepared: AnalysisInput) -> AnalysisOutput:
    prepared.require_columns("district", "price")
    result = prepared.frame.groupby("district", as_index=False)["price"].mean()
    return AnalysisOutput(result=result, metrics={})


def _task(runner: object = None, transforms: ModuleType | None = None) -> Task:
    return Task(
        name="task00",
        dataset="demo",
        analyze=_analyze,
        runners={"silver": runner or _SilverRunner()},
        transforms=transforms,
    )


def _resolver() -> _Resolver:
    frame = pd.DataFrame({"district": ["11110", "11110", "11140"], "price": [100.0, 200.0, -1.0]})
    return _Resolver({"silver": frame})


class TestRunCondition:
    def test_records_identity_and_measured_fields(self) -> None:
        row = run_condition(
            _task(),
            "silver",
            datasets=_resolver(),
            snapshot_id="demo/20260101-abc123",
            pipeline_version="0.1.0",
            repeat=1,
            warmup=0,
        )

        assert row.task == "task00"
        assert row.condition == "silver"
        assert row.dataset == "demo"
        assert row.source_snapshot == "demo/20260101-abc123"
        assert row.pipeline_version == "0.1.0"
        assert row.status == "ok"

        # measured: every field the schema requires when status == "ok"
        assert row.rows == 2  # the negative price was dropped in preparation
        assert row.runtime_seconds is not None and row.runtime_seconds >= 0
        assert row.transformation_steps == 1
        assert row.preprocessing_loc is not None and row.preprocessing_loc > 0
        assert row.function_count is not None
        assert row.output_hash

    def test_rows_counts_the_prepared_input_not_the_layer(self) -> None:
        # Table 4 reports what preparation cost; filtering is part of that cost.
        # A row count taken from the layer would erase the difference between
        # conditions that filter and conditions that do not.
        row = run_condition(
            _task(),
            "silver",
            datasets=_resolver(),
            snapshot_id="demo/20260101-abc123",
            pipeline_version="0.1.0",
            repeat=1,
            warmup=0,
        )

        assert row.rows == 2

    def test_run_id_identifies_task_condition_and_seed(self) -> None:
        row = run_condition(
            _task(),
            "silver",
            datasets=_resolver(),
            snapshot_id="demo/20260101-abc123",
            pipeline_version="0.1.0",
            seed=3,
            repeat=1,
            warmup=0,
        )

        assert row.seed == 3
        assert row.run_id == "task00/silver/seed3"


class TestFailedRun:
    def test_a_failing_preparation_is_recorded_not_raised(self) -> None:
        # Dropping failures would make the results file describe a more
        # successful experiment than the one that was run.
        class _Broken:
            TASK = "task00"
            CONDITION = "silver"

            def prepare(self, ctx: RunContext) -> AnalysisInput:
                raise ValueError("district code did not normalize")

        row = run_condition(
            _task(runner=_Broken()),
            "silver",
            datasets=_resolver(),
            snapshot_id="demo/20260101-abc123",
            pipeline_version="0.1.0",
            repeat=1,
            warmup=0,
        )

        assert row.status == "failed"
        assert row.rows is None
        assert row.output_hash is None


class TestUnknownCondition:
    def test_asking_for_a_condition_the_task_does_not_define_is_an_error(self) -> None:
        with pytest.raises(KeyError):
            run_condition(
                _task(),
                "gold",
                datasets=_resolver(),
                snapshot_id="demo/20260101-abc123",
                pipeline_version="0.1.0",
                repeat=1,
                warmup=0,
            )
