"""kpx — experiment harness for the Medallion pipeline evaluation.

``kpx`` ("KPubData eXperiments") holds every piece of code that produces a number
in the paper: the condition-runner contract, the measurement modules, the four
downstream tasks, and the reproducibility experiments.

The package deliberately contains **no** transformation logic of its own. Bronze,
Silver and Gold artifacts are produced by ``kpubdata-builder``; ``kpx`` only
consumes them, measures the cost of consuming them, and records the result.
"""

from kpx.contract import (
    CONDITIONS,
    LAYERS,
    AnalysisInput,
    AnalysisOutput,
    Condition,
    ConditionRunner,
    DatasetResolver,
    Layer,
    RunContext,
    condition_layer,
)
from kpx.steps import Step, StepRecorder

__all__ = [
    "CONDITIONS",
    "LAYERS",
    "AnalysisInput",
    "AnalysisOutput",
    "Condition",
    "ConditionRunner",
    "DatasetResolver",
    "Layer",
    "RunContext",
    "Step",
    "StepRecorder",
    "condition_layer",
]

__version__ = "0.1.0"
