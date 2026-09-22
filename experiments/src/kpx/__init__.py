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
from kpx.digest import FileEntry, TreeDigest, digest_tree, file_sha256
from kpx.provenance import (
    BuildInputs,
    Environment,
    Provenance,
    ProvenanceError,
    ProvenanceStore,
    config_hash,
    record_build,
)
from kpx.snapshot import Snapshot, SnapshotError, SnapshotStore, VerifyResult, default_store
from kpx.steps import Step, StepRecorder

__all__ = [
    "CONDITIONS",
    "LAYERS",
    "AnalysisInput",
    "AnalysisOutput",
    "BuildInputs",
    "Condition",
    "ConditionRunner",
    "DatasetResolver",
    "Environment",
    "FileEntry",
    "Layer",
    "Provenance",
    "ProvenanceError",
    "ProvenanceStore",
    "RunContext",
    "Snapshot",
    "SnapshotError",
    "SnapshotStore",
    "Step",
    "StepRecorder",
    "TreeDigest",
    "VerifyResult",
    "condition_layer",
    "config_hash",
    "default_store",
    "digest_tree",
    "file_sha256",
    "record_build",
]

__version__ = "0.1.0"
