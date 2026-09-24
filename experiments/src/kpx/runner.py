"""Driving one condition of one task, and recording what it produced (#13).

The runner contract, the step recorder, code metrics and the result schema each
exist on their own. This is the path that drives them in one order, so that a
run is a single call and every result row is produced the same way.

The order matters and is fixed here rather than per task:

1. ``prepare`` runs once with a step recorder.
2. The task's shared analysis runs on the prepared input, unchanged across
   conditions — that is what makes a difference in the result attributable to
   preparation (Internal Validity).
3. Code metrics are read from the runner's source, with the recorded step count.
4. One :class:`~kpx.results.ResultRow` is assembled, taking ``source_snapshot``
   and ``pipeline_version`` from the build the run read and everything else from
   the run itself (see :meth:`kpx.provenance.Provenance.run_fields`).

Execution time is not measured here. A task-run condition reads layers stored
in different formats, so its wall time would compare formats rather than
strategies; the timing protocol lives in ``scripts/_timing.py``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import ModuleType
from typing import Any

from kpx.contract import AnalysisInput, AnalysisOutput, Condition, DatasetResolver, RunContext
from kpx.metrics.code_metrics import measure_preparation
from kpx.results import ResultRow, output_digest
from kpx.steps import StepRecorder

#: Task diagnostics a task may report, mapped onto result schema fields.
#: A task that reports something else is not silently dropped — see ``_metrics``.
METRIC_FIELDS: tuple[str, ...] = ("join_matching_rate",)


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
) -> ResultRow:
    """Run one condition of ``task`` and return the row describing it.

    A run that fails is returned as ``status="failed"`` rather than raised:
    dropping failures would make the results file describe a more successful
    experiment than the one that was run. A condition the task does not define
    is a different thing — that is a mistake in the call, and it raises.
    """
    runner = task.runners[condition]
    run_id = run_id_for(task.name, condition, seed)

    recorder = StepRecorder()
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
    try:
        prepared = runner.prepare(context)
        output = task.analyze(prepared)
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

    code = measure_preparation(runner, transforms=task.transforms, steps=recorder.step_count)

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
        preprocessing_loc=code.preprocessing_loc,
        function_count=code.function_count,
        transformation_steps=code.transformation_steps,
        output_hash=output_digest(output.result),
        **_metrics(prepared, output),
    )


def _metrics(prepared: AnalysisInput, output: AnalysisOutput) -> dict[str, float]:
    """The run's task diagnostics, keyed by result schema field.

    Two sources, because two different things are being measured.

    Some diagnostics are properties of *preparation* rather than of the
    analysis — Task 3's ``join_matching_rate`` is the clearest case: how many
    sale keys found a jeonse counterpart is decided before the analysis runs.
    Those arrive in ``AnalysisInput.notes``. The analysis must not read notes
    (that is what keeps it identical across conditions), but the result row is
    not the analysis, so the runner reads them on the way out.

    ``output.metrics`` wins on a collision: a number the analysis computed is
    about the analysis, and preparation should not be able to overwrite it.

    A metric the schema has no field for is left out rather than guessed at —
    the task keeps it in its notes.
    """
    from_preparation = {
        name: float(value)
        for name, value in prepared.notes.items()
        if name in METRIC_FIELDS and isinstance(value, (int, float))
    }
    from_analysis = {name: value for name, value in output.metrics.items() if name in METRIC_FIELDS}
    return {**from_preparation, **from_analysis}
