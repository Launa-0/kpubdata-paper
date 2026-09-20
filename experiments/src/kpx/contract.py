"""The condition-runner contract.

Every measurement in the paper compares four *conditions* of the same task:

==============  =====================================================
``bronze``      minimally parsed source records
``silver``      canonical, normalized dataset
``gold``        task-oriented reusable dataset
``monolithic``  single-pass transformation, no persisted intermediate
==============  =====================================================

The contract exists to make two threats to validity structural rather than
procedural:

**Construct validity (RQ2).** ``preprocessing_loc`` must cover data preparation
and nothing else. Instead of deciding after the fact which lines were
"preparation", a condition implements :meth:`ConditionRunner.prepare` and the
code-metrics module measures exactly that method and its private helpers. The
boundary is enforced by the interface.

**Internal validity (RQ3).** If each condition were free to analyse differently,
the comparison would be of analyses, not of data preparation. So ``analyze`` is
*not* per condition: a task defines one analysis function that every condition
is handed, unchanged. Conditions differ only in how they reach
:class:`AnalysisInput`.

That is also why ``monolithic`` is not a special case in the code. It is an
ordinary runner whose ``prepare`` happens to do everything in one pass without
persisting an intermediate dataset; it reuses the same transformation helpers as
the Medallion path, which is the control condition required by the Baseline
Bias discussion.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

import pandas as pd

Condition = Literal["bronze", "silver", "gold", "monolithic"]
Layer = Literal["bronze", "silver", "gold"]

CONDITIONS: tuple[Condition, ...] = ("bronze", "silver", "gold", "monolithic")
LAYERS: tuple[Layer, ...] = ("bronze", "silver", "gold")


def condition_layer(condition: Condition) -> Layer:
    """Return the Medallion layer a condition reads from.

    ``monolithic`` reads Bronze — it is the baseline that must reproduce the
    whole pipeline itself, so its input is the same minimally parsed source the
    Medallion path starts from.
    """
    if condition not in CONDITIONS:
        raise ValueError(f"unknown condition: {condition!r}")
    return "bronze" if condition == "monolithic" else condition  # type: ignore[return-value]


@runtime_checkable
class DatasetResolver(Protocol):
    """Locates dataset artifacts for a snapshot and layer.

    Implemented by the dataset layer (issue #7). The contract keeps it abstract
    so that task code never hard-codes a path and so that tests can substitute
    fixtures for real snapshots.
    """

    def load(self, dataset: str, layer: Layer) -> pd.DataFrame:
        """Load ``dataset`` at ``layer`` for the resolver's snapshot."""
        ...

    def path(self, dataset: str, layer: Layer) -> str:
        """Filesystem path of the artifact backing :meth:`load`."""
        ...


@dataclass(frozen=True)
class RunContext:
    """Everything a condition runner is allowed to depend on.

    A runner must take its inputs from the context rather than from module-level
    state, so that a run is fully described by ``(task, condition, snapshot_id,
    pipeline_version, seed)`` and can be replayed.
    """

    task: str
    condition: Condition
    run_id: str
    snapshot_id: str
    pipeline_version: str
    datasets: DatasetResolver
    seed: int = 0
    params: Mapping[str, Any] = field(default_factory=dict)
    recorder: Any = None  # kpx.steps.StepRecorder; Any avoids a circular import

    @property
    def layer(self) -> Layer:
        """The Medallion layer this condition reads from."""
        return condition_layer(self.condition)

    def load(self, dataset: str) -> pd.DataFrame:
        """Load ``dataset`` at the layer implied by this condition."""
        return self.datasets.load(dataset, self.layer)

    @contextmanager
    def step(self, name: str) -> Iterator[None]:
        """Record a transformation step (see :mod:`kpx.steps`).

        Usable without a recorder attached, so preparation code can be exercised
        in a plain unit test without building a whole run.
        """
        if self.recorder is None:
            yield
            return
        with self.recorder.step(name):
            yield


@dataclass
class AnalysisInput:
    """The hand-off point between preparation and analysis.

    Every condition of a task must produce the *same shape* here — same columns,
    same semantics, same units. That is what makes the downstream analysis
    identical across conditions and what makes any remaining difference in the
    result attributable to preparation rather than to analysis.

    ``frame`` is the prepared table. ``notes`` carries condition-specific
    observations (rows dropped, keys that failed to normalize) that the Results
    section reports but the analysis itself must not read.
    """

    frame: pd.DataFrame
    notes: dict[str, Any] = field(default_factory=dict)

    def require_columns(self, *columns: str) -> None:
        """Raise if the prepared frame is missing any required column.

        Called by a task's analysis entry point so that a condition which
        prepares the wrong shape fails loudly instead of silently producing a
        different number.
        """
        missing = [c for c in columns if c not in self.frame.columns]
        if missing:
            raise ValueError(f"prepared frame is missing required column(s): {', '.join(missing)}")


@dataclass
class AnalysisOutput:
    """The analytical result of a task, plus whatever it should be judged on.

    ``result`` is the table the analysis produced (per-district trends, a set of
    predictions, a jeonse-ratio series). ``metrics`` holds the task's correctness
    numbers — RMSE, join matching rate, aggregate deviation — keyed by the names
    used in the result schema.
    """

    result: pd.DataFrame
    metrics: dict[str, float] = field(default_factory=dict)


@runtime_checkable
class ConditionRunner(Protocol):
    """One condition of one task.

    Implementations live in ``kpx/tasks/taskNN_*/{bronze,silver,gold,monolithic}.py``
    and implement ``prepare`` only. The task's analysis is shared.
    """

    TASK: str
    CONDITION: Condition

    def prepare(self, ctx: RunContext) -> AnalysisInput:
        """Turn the condition's input layer into the task's analysis input.

        Everything this method and its helpers do counts as data preparation and
        is what RQ2 measures. It must not compute any part of the analytical
        result.
        """
        ...
