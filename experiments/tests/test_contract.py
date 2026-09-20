from __future__ import annotations

import pandas as pd
import pytest

from kpx.contract import (
    CONDITIONS,
    AnalysisInput,
    ConditionRunner,
    DatasetResolver,
    RunContext,
    condition_layer,
)
from kpx.steps import StepRecorder


class FakeResolver:
    def __init__(self, frames: dict[tuple[str, str], pd.DataFrame]) -> None:
        self.frames = frames
        self.calls: list[tuple[str, str]] = []

    def load(self, dataset: str, layer: str) -> pd.DataFrame:
        self.calls.append((dataset, layer))
        return self.frames[(dataset, layer)]

    def path(self, dataset: str, layer: str) -> str:
        return f"/fake/{layer}/{dataset}.parquet"


def make_ctx(condition: str = "silver", **kwargs: object) -> RunContext:
    frames = {
        (name, layer): pd.DataFrame({"a": [1]})
        for name in ("trades",)
        for layer in ("bronze", "silver", "gold")
    }
    defaults: dict[str, object] = {
        "task": "task01",
        "condition": condition,
        "run_id": "r1",
        "snapshot_id": "s1",
        "pipeline_version": "0.1.0",
        "datasets": FakeResolver(frames),
    }
    defaults.update(kwargs)
    return RunContext(**defaults)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("condition", "expected"),
    [("bronze", "bronze"), ("silver", "silver"), ("gold", "gold"), ("monolithic", "bronze")],
)
def test_condition_layer(condition: str, expected: str) -> None:
    assert condition_layer(condition) == expected  # type: ignore[arg-type]


def test_condition_layer_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="unknown condition"):
        condition_layer("platinum")  # type: ignore[arg-type]


def test_monolithic_reads_bronze() -> None:
    """The baseline must start from the same minimally parsed source."""
    ctx = make_ctx("monolithic")
    ctx.load("trades")
    assert ctx.datasets.calls == [("trades", "bronze")]  # type: ignore[attr-defined]


def test_every_condition_resolves_to_a_layer() -> None:
    assert {condition_layer(c) for c in CONDITIONS} == {"bronze", "silver", "gold"}


def test_step_is_a_noop_without_a_recorder() -> None:
    """Preparation code must be unit-testable without building a whole run."""
    ctx = make_ctx()
    with ctx.step("parse_price"):
        pass


def test_step_records_through_the_context() -> None:
    recorder = StepRecorder()
    ctx = make_ctx(recorder=recorder)
    with ctx.step("parse_price"):
        pass
    with ctx.step("normalize_district"):
        pass
    assert [s.name for s in recorder.steps] == ["parse_price", "normalize_district"]


def test_require_columns_reports_every_missing_column() -> None:
    prepared = AnalysisInput(frame=pd.DataFrame({"district_code": ["11110"]}))
    with pytest.raises(ValueError, match="price_krw, deal_date"):
        prepared.require_columns("district_code", "price_krw", "deal_date")


def test_require_columns_accepts_a_complete_frame() -> None:
    prepared = AnalysisInput(frame=pd.DataFrame({"district_code": [], "price_krw": []}))
    prepared.require_columns("district_code", "price_krw")


def test_runner_protocol_is_structural() -> None:
    class Silver:
        TASK = "task01"
        CONDITION = "silver"

        def prepare(self, ctx: RunContext) -> AnalysisInput:
            return AnalysisInput(frame=ctx.load("trades"))

    assert isinstance(Silver(), ConditionRunner)


def test_resolver_protocol_is_structural() -> None:
    assert isinstance(FakeResolver({}), DatasetResolver)
