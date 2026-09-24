"""Transformation step recording.

RQ2 records how many *transformation steps* a condition needs before analysis can
start, as a diagnostic beside the code metrics. Counting those by hand invites
bias, so a step is instead recorded by the preparation code as it runs::

    with ctx.step("parse_price"):
        df["price_krw"] = df["거래금액"].map(parse_price)

The recorder gives three things at once:

* an objective ``transformation_steps`` count for :mod:`kpx.metrics.code_metrics`,
* a per-step wall-clock breakdown, for locating where preparation spends time,
* a readable trace of what each condition actually had to do, which is the
  qualitative material for the Results section.

Steps may nest. Only top-level steps are counted as transformation steps; nested
ones are recorded as children so that a step like ``normalize_columns`` is one
step even when it internally brackets several sub-operations.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field


@dataclass
class Step:
    """One recorded transformation step."""

    name: str
    seconds: float
    depth: int
    children: list[Step] = field(default_factory=list)

    def flatten(self) -> Iterator[Step]:
        """Yield this step and every descendant, depth-first."""
        yield self
        for child in self.children:
            yield from child.flatten()


class StepRecorder:
    """Collects :class:`Step` records for a single preparation run."""

    def __init__(self) -> None:
        self._top: list[Step] = []
        self._stack: list[Step] = []

    @contextmanager
    def step(self, name: str) -> Iterator[None]:
        """Bracket a transformation step under ``name``."""
        if not name or not name.strip():
            raise ValueError("step name must be a non-empty string")
        started = time.perf_counter()
        record = Step(name=name, seconds=0.0, depth=len(self._stack))
        parent = self._stack[-1] if self._stack else None
        self._stack.append(record)
        try:
            yield
        finally:
            self._stack.pop()
            record.seconds = time.perf_counter() - started
            if parent is None:
                self._top.append(record)
            else:
                parent.children.append(record)

    @property
    def steps(self) -> list[Step]:
        """Top-level steps, in the order they completed."""
        if self._stack:
            raise RuntimeError("cannot read steps while a step is still open")
        return list(self._top)

    @property
    def step_count(self) -> int:
        """Number of top-level transformation steps.

        This is the value reported as ``transformation_steps`` in the result
        schema. Nested steps are excluded so that the count reflects logical
        transformations rather than implementation detail.
        """
        return len(self.steps)

    @property
    def total_seconds(self) -> float:
        """Wall-clock seconds spent inside top-level steps."""
        return sum(step.seconds for step in self.steps)

    def trace(self) -> list[tuple[str, int, float]]:
        """A flat ``(name, depth, seconds)`` trace including nested steps."""
        return [
            (step.name, step.depth, step.seconds) for top in self.steps for step in top.flatten()
        ]
