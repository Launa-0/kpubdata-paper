"""Driving one condition of one task, and recording what it cost (#13).

Every measurement this harness makes already existed — the runner contract, the
step recorder, code metrics, the runtime protocol, the result schema. What was
missing was the path that drives them in one order, so that a run is a single
call and every result row is produced the same way.

The order matters and is fixed here rather than per task:

1. ``prepare`` runs under the runtime protocol (warm-up, then measured runs),
   with a fresh step recorder each time so repeats do not accumulate steps.
2. The task's shared analysis runs on the prepared input, unchanged across
   conditions — that is what makes a difference in the result attributable to
   preparation (Internal Validity).
3. Code metrics are read from the runner's source, with the recorded step count
   from the final measured run.
4. One :class:`~kpx.results.ResultRow` is assembled, taking ``source_snapshot``
   and ``pipeline_version`` from the build the run read and everything else from
   the run itself (see :meth:`kpx.provenance.Provenance.run_fields`).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import ModuleType
from typing import Any

from kpx.contract import AnalysisInput, AnalysisOutput, Condition, DatasetResolver, RunContext
from kpx.metrics.code_metrics import measure_preparation
from kpx.metrics.runtime import MEASURED_RUNS, WARMUP_RUNS, measure
from kpx.results import ResultRow, output_digest
from kpx.steps import StepRecorder

#: Correctness metrics a task may report, mapped onto result schema fields.
#: A task that reports something else is not silently dropped — see ``_metrics``.
METRIC_FIELDS: tuple[str, ...] = (
    "mae",
    "rmse",
    "join_matching_rate",
    "missing_rate",
    "duplicate_rate",
    "schema_validity",
)


@dataclass(frozen=True)
class Task:
    """One analysis task and the conditions that prepare data for it.

    ``analyze`` is defined once and handed to every condition unchanged;
    ``runners`` differ only in how they reach :class:`AnalysisInput`.
    ``transforms`` is the task's shared helper module — calls into it count as
    transformations without their bodies being charged to any one condition.
    """

    name: str
    dataset: str
    analyze: Callable[[AnalysisInput], AnalysisOutput]
    runners: Mapping[Condition, Any]
    transforms: ModuleType | None = None
    params: Mapping[str, Any] = field(default_factory=dict)


def run_id_for(task: str, condition: Condition, seed: int) -> str:
    """The identity of a run: its task, its condition and its seed."""
    return f"{task}/{condition}/seed{seed}"


def run_condition(
    task: Task,
    condition: Condition,
    *,
    datasets: DatasetResolver,
    snapshot_id: str,
    pipeline_version: str,
    seed: int = 0,
    warmup: int = WARMUP_RUNS,
    repeat: int = MEASURED_RUNS,
) -> ResultRow:
    """Run one condition of ``task`` and return the row describing it.

    A run that fails is returned as ``status="failed"`` rather than raised:
    dropping failures would make the results file describe a more successful
    experiment than the one that was run. A condition the task does not define
    is a different thing — that is a mistake in the call, and it raises.
    """
    runner = task.runners[condition]
    run_id = run_id_for(task.name, condition, seed)

    recorders: list[StepRecorder] = []

    def once() -> tuple[AnalysisInput, AnalysisOutput]:
        recorder = StepRecorder()
        recorders.append(recorder)
        context = RunContext(
            task=task.name,
            condition=condition,
            run_id=run_id,
            snapshot_id=snapshot_id,
            pipeline_version=pipeline_version,
            datasets=datasets,
            seed=seed,
            params=task.params,
            recorder=recorder,
        )
        prepared = runner.prepare(context)
        return prepared, task.analyze(prepared)

    try:
        measurement = measure(once, warmup=warmup, repeat=repeat)
    except Exception:
        return ResultRow(
            run_id=run_id,
            task=task.name,
            dataset=task.dataset,
            condition=condition,
            source_snapshot=snapshot_id,
            pipeline_version=pipeline_version,
            seed=seed,
            status="failed",
        )

    prepared, output = measurement.result
    code = measure_preparation(
        runner,
        transforms=task.transforms,
        steps=recorders[-1].step_count if recorders else None,
    )

    return ResultRow(
        run_id=run_id,
        task=task.name,
        dataset=task.dataset,
        condition=condition,
        source_snapshot=snapshot_id,
        pipeline_version=pipeline_version,
        seed=seed,
        status="ok",
        rows=len(prepared.frame),
        runtime_seconds=measurement.median,
        peak_memory_mb=measurement.peak_memory_mb,
        preprocessing_loc=code.preprocessing_loc,
        function_count=code.function_count,
        transformation_steps=code.transformation_steps,
        output_hash=output_digest(output.result),
        **_metrics(output),
    )


def _metrics(output: AnalysisOutput) -> dict[str, float]:
    """The task's correctness numbers, keyed by result schema field.

    A metric the schema has no field for is left out rather than guessed at —
    the task reports it in its own notes instead.
    """
    return {name: value for name, value in output.metrics.items() if name in METRIC_FIELDS}
