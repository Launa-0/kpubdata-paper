"""When materializing a layer pays for itself (#19, Discussion).

Gold's preparation cost is near zero, but that cost did not vanish — it moved
upstream into the build that produced Gold. Reporting the low number alone would
describe half a trade-off.

The question the trade-off actually poses is how often the artifact has to be
reused::

    N* = build cost / (per-analysis cost without it - per-analysis cost with it)

Below ``N*`` the materialization has not paid for itself; above it, it has. This
turns "Gold is faster" into "Gold is economical for workloads that revisit the
same aggregate more than ``N*`` times", which is a claim a reader can apply to
their own situation.

The comparison is between two conditions that start from the same Silver, so the
Silver build cost is common to both and cancels. What is being amortized is the
Gold build alone.

``None`` where a whole-number answer would be wrong: an artifact that saves
nothing per analysis never pays for itself, however cheap it was to build, and
printing a large number there would suggest it eventually does.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


class BreakEvenError(RuntimeError):
    """Raised when costs cannot describe an amortization."""


@dataclass(frozen=True)
class BreakEvenReport:
    build_cost: float
    baseline_per_analysis: float
    derived_per_analysis: float

    @property
    def saving_per_analysis(self) -> float:
        return self.baseline_per_analysis - self.derived_per_analysis

    @property
    def analyses_to_break_even(self) -> int | None:
        """How many analyses before the build has paid for itself.

        ``None`` when the derived layer saves nothing per analysis — then no
        number of reuses recovers the build.
        """
        if self.saving_per_analysis <= 0:
            return None
        return math.ceil(self.build_cost / self.saving_per_analysis)

    def baseline_total(self, analyses: int) -> float:
        return self.baseline_per_analysis * analyses

    def derived_total(self, analyses: int) -> float:
        return self.build_cost + self.derived_per_analysis * analyses

    def to_dict(self) -> dict[str, Any]:
        return {
            "build_cost": self.build_cost,
            "baseline_per_analysis": self.baseline_per_analysis,
            "derived_per_analysis": self.derived_per_analysis,
            "saving_per_analysis": self.saving_per_analysis,
            "analyses_to_break_even": self.analyses_to_break_even,
        }


def break_even(
    *, build_cost: float, baseline_per_analysis: float, derived_per_analysis: float
) -> BreakEvenReport:
    """Amortize one build across repeated analyses."""
    costs = {
        "build_cost": build_cost,
        "baseline_per_analysis": baseline_per_analysis,
        "derived_per_analysis": derived_per_analysis,
    }
    negative = sorted(name for name, value in costs.items() if value < 0)
    if negative:
        raise BreakEvenError(f"negative costs: {negative}")

    return BreakEvenReport(
        build_cost=build_cost,
        baseline_per_analysis=baseline_per_analysis,
        derived_per_analysis=derived_per_analysis,
    )
