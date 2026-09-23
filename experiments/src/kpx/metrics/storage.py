"""Storage overhead for the Medallion trade-off.

The paper does not claim that a layered pipeline is always the better choice, so
the cost side has to be measured rather than conceded in a sentence. Keeping
Bronze, Silver and Gold means storing the same facts several times over::

    amplification factor = (Bronze + Silver + Gold) / final-only

The denominator is what a monolithic pipeline leaves on disk. It persists no
intermediate, so its footprint is its final output — and because the baseline is
required to reach the same analysis input as the full Medallion path
(``docs/monolithic-baseline.md``), that footprint is the Gold artifact's. The
comparison is therefore between *the same data stored once* and *the same data
stored at three levels of refinement*, which is the cost that RQ2's savings are
weighed against.

Sizes come from the build records rather than from the filesystem. A reader who
never restores the artifacts still has the numbers, and a size measured at
analysis time could not be attributed to any particular build.

What this could get wrong, and what stops each
----------------------------------------------

**Summing layers built by different pipelines.** A Bronze from one pipeline
version added to a Silver from another attributes a configuration change to
layering. :func:`measure_storage` requires every layer to name the same dataset,
the same ``snapshot_id`` and the same ``pipeline_version``, and refuses
otherwise.

**Comparing across storage formats.** An amplification factor is meaningless if
Bronze is JSON and Gold is compressed Parquet — it would be measuring the codec.
Format is fixed by the build configuration and is not visible in a provenance
record, so it cannot be checked here. Instead ``bytes_per_row`` is reported per
layer, where a format difference shows up as a ratio nothing else explains, and
the Methodology section states the format explicitly.

**Counting a failed build's bytes.** A build that broke did not produce a stored
dataset. Only ``status == "ok"`` builds are summed, and the rest are counted in
``skipped`` so their absence is visible rather than silent.

**Hiding Gold proliferation.** One dataset can carry several task-oriented Gold
artifacts, and their maintenance is one of the costs the Discussion weighs. They
all count toward Medallion storage, but only one of them is the baseline — so
when there is more than one, the caller has to say which, rather than have this
module quietly pick the first and halve the amplification factor.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

import pandas as pd

from kpx.contract import LAYERS, Layer
from kpx.provenance import Provenance, ProvenanceStore

#: The layer whose footprint a monolithic pipeline's final output corresponds to.
BASELINE_LAYER: Layer = "gold"


class StorageError(ValueError):
    """Raised when a storage comparison cannot be made as specified."""


@dataclass(frozen=True)
class LayerStorage:
    """What one layer of one dataset costs to keep."""

    layer: Layer
    builds: int
    bytes: int
    files: int
    rows: int

    @property
    def bytes_per_row(self) -> float | None:
        """Bytes per stored row, or ``None`` for an empty layer.

        Reported so that a format or compression difference between layers is
        visible: it shows up here as a ratio nothing else explains.
        """
        return self.bytes / self.rows if self.rows else None


@dataclass(frozen=True)
class StorageProfile:
    """The storage trade-off for one dataset at one snapshot."""

    dataset: str
    snapshot_id: str
    pipeline_version: str
    layers: tuple[LayerStorage, ...]
    baseline_bytes: int
    baseline_build_id: str
    skipped: int = 0

    @property
    def total_bytes(self) -> int:
        """Bronze + Silver + Gold — everything the Medallion path keeps."""
        return sum(layer.bytes for layer in self.layers)

    @property
    def amplification_factor(self) -> float:
        """Medallion storage over final-only storage."""
        if self.baseline_bytes == 0:
            raise StorageError(
                f"{self.dataset}: the baseline build stores no bytes, so an "
                f"amplification factor would divide by zero"
            )
        return self.total_bytes / self.baseline_bytes

    @property
    def overhead_bytes(self) -> int:
        """What layering costs over storing the final dataset alone."""
        return self.total_bytes - self.baseline_bytes

    def layer(self, layer: Layer) -> LayerStorage | None:
        return next((item for item in self.layers if item.layer == layer), None)

    def row(self) -> dict[str, Any]:
        """One row of the storage table the paper prints."""
        row: dict[str, Any] = {
            "dataset": self.dataset,
            "snapshot_id": self.snapshot_id,
            "pipeline_version": self.pipeline_version,
        }
        for name in LAYERS:
            found = self.layer(name)
            row[f"{name}_bytes"] = None if found is None else found.bytes
            row[f"{name}_bytes_per_row"] = None if found is None else found.bytes_per_row
        row["total_bytes"] = self.total_bytes
        row["baseline_bytes"] = self.baseline_bytes
        row["overhead_bytes"] = self.overhead_bytes
        row["amplification_factor"] = self.amplification_factor
        return row


def measure_storage(
    store: ProvenanceStore,
    dataset: str,
    *,
    snapshot_id: str | None = None,
    baseline_build_id: str | None = None,
) -> StorageProfile:
    """Measure what keeping every layer of ``dataset`` costs.

    ``snapshot_id`` selects which run of the dataset to measure; with one
    snapshot recorded it can be left out. ``baseline_build_id`` names the Gold
    artifact the monolithic baseline reproduces, and is required only when the
    dataset has more than one.
    """
    builds = [
        build
        for build in store.list_builds(dataset)
        if snapshot_id is None or build.inputs.snapshot_id == snapshot_id
    ]
    if not builds:
        raise StorageError(f"no builds recorded for {dataset}")

    usable = [build for build in builds if build.status == "ok"]
    if not usable:
        raise StorageError(f"{dataset}: every recorded build failed; nothing is stored")

    _require_one_pipeline(dataset, usable)

    missing = [name for name in LAYERS if not any(b.inputs.layer == name for b in usable)]
    if missing:
        raise StorageError(
            f"{dataset}: no successful build for {', '.join(missing)}; an amplification "
            f"factor over an incomplete set would understate what layering costs"
        )

    baseline = _baseline_build(dataset, usable, baseline_build_id)
    return StorageProfile(
        dataset=dataset,
        snapshot_id=usable[0].inputs.snapshot_id,
        pipeline_version=usable[0].inputs.pipeline_version,
        layers=tuple(_layer_storage(name, usable) for name in LAYERS),
        baseline_bytes=baseline.output_size_bytes,
        baseline_build_id=baseline.build_id,
        skipped=len(builds) - len(usable),
    )


def storage_table(profiles: Iterable[StorageProfile]) -> pd.DataFrame:
    """The storage trade-off table, one row per dataset."""
    rows = [profile.row() for profile in profiles]
    if not rows:
        return pd.DataFrame(columns=["dataset", "total_bytes", "amplification_factor"])
    return pd.DataFrame(rows)


# -- internals -------------------------------------------------------------


def _require_one_pipeline(dataset: str, builds: Sequence[Provenance]) -> None:
    """Summing layers from different runs would measure the difference between them."""
    for field in ("snapshot_id", "pipeline_version"):
        values = {str(getattr(build.inputs, field)) for build in builds}
        if len(values) > 1:
            raise StorageError(
                f"{dataset}: layers were built from different {field}s "
                f"({', '.join(sorted(values))}); pass snapshot_id to pick one run"
            )


def _baseline_build(
    dataset: str, builds: Sequence[Provenance], baseline_build_id: str | None
) -> Provenance:
    golds = [build for build in builds if build.inputs.layer == BASELINE_LAYER]
    if baseline_build_id is not None:
        found = next((build for build in golds if build.build_id == baseline_build_id), None)
        if found is None:
            raise StorageError(f"{dataset}: no {BASELINE_LAYER} build {baseline_build_id}")
        return found
    if len(golds) > 1:
        raise StorageError(
            f"{dataset}: {len(golds)} {BASELINE_LAYER} artifacts exist, so the monolithic "
            f"baseline's footprint is ambiguous; name one with baseline_build_id "
            f"({', '.join(sorted(build.build_id for build in golds))})"
        )
    return golds[0]


def _layer_storage(layer: Layer, builds: Sequence[Provenance]) -> LayerStorage:
    """Every artifact kept at one layer, sibling Golds included."""
    of_layer = [build for build in builds if build.inputs.layer == layer]
    return LayerStorage(
        layer=layer,
        builds=len(of_layer),
        bytes=sum(build.output_size_bytes for build in of_layer),
        files=sum(build.output_file_count for build in of_layer),
        rows=sum(build.row_count for build in of_layer),
    )
