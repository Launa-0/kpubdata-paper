"""Build provenance: which recipe produced which artifact.

RQ4 needs a precise version of a loose claim. "Deterministic build" is made
testable here by separating two things that are easy to conflate:

* the **recipe** — snapshot, pipeline version, transformation config, upstream
  layer. Its hash is the ``build_id``.
* the **result** — the bytes the recipe produced. Its hash is the
  ``output_checksum``.

R1 then reads: *same build_id must give the same output_checksum*. R2 holds
everything in the recipe constant except ``snapshot_id`` and asks whether the
pipeline's contract survives; a different ``output_checksum`` there is expected,
a broken schema is not.

The captured :class:`Environment` deliberately does **not** feed the build_id.
If it did, every machine would compute a different build_id and R1 could never
compare a rebuild across machines — which is exactly the comparison a reader
reproducing the paper makes. The environment is recorded so that a cross-machine
difference in ``output_checksum`` can be *explained* rather than prevented from
being observed.

The config half of the recipe is hashed by :func:`kpx.pipeline.config_hash`,
re-exported here so that recipe construction reads from one place.

Provenance also carries lineage. Silver names the Bronze build it came from and
Gold names the Silver build, so a schema breakage found in R2 can be traced to
the layer that introduced it.
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from importlib import metadata
from pathlib import Path
from typing import Any

from kpx.contract import LAYERS, Layer
from kpx.digest import digest_tree
from kpx.pipeline import config_hash

PROVENANCE_FILENAME = "provenance.json"
SCHEMA_VERSION = 1

#: Libraries whose version can change a numeric result and so must be reported
#: in the paper's methodology section.
TRACKED_PACKAGES = ("pandas", "pyarrow", "numpy", "scikit-learn", "scipy", "kpubdata-builder")


class ProvenanceError(RuntimeError):
    """Raised when provenance is missing, malformed, or internally inconsistent."""


@dataclass(frozen=True)
class Environment:
    """Where a build ran. Recorded, never hashed into the build_id."""

    python_version: str
    platform: str
    packages: dict[str, str]

    @classmethod
    def capture(cls, packages: tuple[str, ...] = TRACKED_PACKAGES) -> Environment:
        found: dict[str, str] = {}
        for name in packages:
            try:
                found[name] = metadata.version(name)
            except metadata.PackageNotFoundError:
                continue
        return cls(
            python_version=".".join(str(part) for part in sys.version_info[:3]),
            platform=platform.platform(),
            packages=found,
        )

    def differences(self, other: Environment) -> dict[str, tuple[str, str]]:
        """Fields that differ from ``other``.

        Used when a rebuild produces a different checksum: the first question is
        always whether the environment moved.
        """
        diff: dict[str, tuple[str, str]] = {}
        if self.python_version != other.python_version:
            diff["python_version"] = (self.python_version, other.python_version)
        if self.platform != other.platform:
            diff["platform"] = (self.platform, other.platform)
        for name in sorted(set(self.packages) | set(other.packages)):
            mine = self.packages.get(name, "—")
            theirs = other.packages.get(name, "—")
            if mine != theirs:
                diff[f"packages.{name}"] = (mine, theirs)
        return diff


@dataclass(frozen=True)
class BuildInputs:
    """The recipe for one layer artifact.

    Everything here changes what the build should produce. Nothing else does —
    that is the claim R1 tests.
    """

    dataset: str
    layer: Layer
    snapshot_id: str
    pipeline_version: str
    config_hash: str
    upstream_build_id: str | None = None

    def __post_init__(self) -> None:
        if self.layer not in LAYERS:
            raise ProvenanceError(f"unknown layer: {self.layer!r}")
        if self.layer == "bronze" and self.upstream_build_id is not None:
            raise ProvenanceError("bronze is built from a snapshot, not from an upstream build")
        if self.layer != "bronze" and self.upstream_build_id is None:
            raise ProvenanceError(f"{self.layer} must name the build it was derived from")

    @property
    def build_id(self) -> str:
        """Deterministic hash of the recipe, 16 hex characters."""
        material = "\n".join(
            [
                self.dataset,
                self.layer,
                self.snapshot_id,
                self.pipeline_version,
                self.config_hash,
                self.upstream_build_id or "",
            ]
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class Provenance:
    """A completed build: its recipe, its result, and where it ran.

    This record, not ``experiment_results.parquet``, is where builds are
    counted. R1 (same snapshot rebuilt) and R2 (pipeline held constant across
    snapshots) both measure builds, and everything they measure is already a
    field here: ``status`` for build success rate, ``output_checksum`` for
    SHA-256 equality, ``row_count`` for row loss, ``columns`` for schema
    compatibility, ``output_size_bytes`` for storage amplification, and
    :meth:`ProvenanceStore.lineage` to attribute a breakage to the layer that
    introduced it.

    ``status`` is therefore a build outcome and keeps a wider vocabulary than
    the result schema's three run outcomes — R2 reports *which* kind of
    breakage occurred, so collapsing ``schema_breakage`` into ``failed`` here
    would throw away its finding. The two never have to be reconciled because
    ``status`` does not cross into the result schema; see :attr:`run_fields`.
    """

    build_id: str
    inputs: BuildInputs
    environment: Environment
    built_at: datetime
    row_count: int
    columns: tuple[str, ...]
    output_checksum: str
    output_size_bytes: int
    output_file_count: int
    kpx_version: str
    status: str = "ok"
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.build_id != self.inputs.build_id:
            raise ProvenanceError(
                f"build_id {self.build_id} does not match its inputs "
                f"(expected {self.inputs.build_id}); the record has been edited"
            )

    @property
    def run_fields(self) -> dict[str, Any]:
        """What a task run inherits from the build it read.

        Only the two fields that identify the build. Everything else a build
        knows about itself stays here, because a build is not a run: R1 and R2
        repeat *builds*, which have no task, no condition and no seed, and those
        are identity fields in the result schema. Counting builds in
        ``experiment_results.parquet`` would mean inventing values for all three.

        Three fields deliberately do **not** cross this boundary:

        ``row_count``
            the rows in this layer. The result schema's ``rows`` is the rows in
            the *prepared analysis input*, which is smaller and differs by
            condition — filtering is part of what preparation costs. Passing the
            layer's count would erase exactly the difference Table 4 reports.
        ``output_checksum``
            the digest of these layer bytes, which is build determinism. The
            result schema's ``output_hash`` is the digest of the analytical
            result, which is analysis determinism; ``results.output_digest``
            computes it.
        ``status``
            how the *build* ended, in a wider vocabulary than a run's
            (see the class docstring). R2 needs to tell one kind of breakage
            from another; the result schema needs to know whether a run
            produced numbers.
        """
        return {
            "source_snapshot": self.inputs.snapshot_id,
            "pipeline_version": self.inputs.pipeline_version,
        }

    def to_json(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["built_at"] = self.built_at.isoformat()
        payload["columns"] = list(self.columns)
        return payload

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> Provenance:
        version = payload.get("schema_version", SCHEMA_VERSION)
        if version > SCHEMA_VERSION:
            raise ProvenanceError(
                f"provenance is version {version}, this harness understands {SCHEMA_VERSION}; "
                "upgrade kpx rather than reading it partially"
            )
        data = dict(payload)
        data["inputs"] = BuildInputs(**data["inputs"])
        data["environment"] = Environment(**data["environment"])
        data["built_at"] = datetime.fromisoformat(data["built_at"])
        data["columns"] = tuple(data["columns"])
        return cls(**data)


def record_build(
    artifact: Path | str,
    *,
    inputs: BuildInputs,
    row_count: int,
    columns: tuple[str, ...] | list[str],
    built_at: datetime | None = None,
    status: str = "ok",
    environment: Environment | None = None,
) -> Provenance:
    """Digest a freshly built artifact and describe the build that made it.

    ``artifact`` is the build's ``data/`` directory — the bytes alone, without
    the ``provenance.json`` that is written beside it. ``provenance.json`` stays
    excluded from the digest anyway, so that a store laid out some other way
    still cannot hash a build's own record into its ``output_checksum``.
    """
    from kpx import __version__

    digest = digest_tree(Path(artifact), exclude=frozenset({PROVENANCE_FILENAME, ".DS_Store"}))
    return Provenance(
        build_id=inputs.build_id,
        inputs=inputs,
        environment=environment or Environment.capture(),
        built_at=built_at or datetime.now().astimezone(),
        row_count=row_count,
        columns=tuple(columns),
        output_checksum=digest.sha256,
        output_size_bytes=digest.size_bytes,
        output_file_count=digest.file_count,
        kpx_version=__version__,
        status=status,
    )


class ProvenanceStore:
    """Reads and writes ``provenance.json`` beside built layer artifacts.

    Layout::

        datasets/<dataset>/<layer>/<build_id>/
        ├── provenance.json     # the record; committed
        └── data/               # the artifact bytes; git-ignored

    The split mirrors the snapshot layout (``metadata.json`` + ``source/``) and
    exists for the same reason: the bytes are large and are republished
    separately, but the record has to survive in the repository. A reader who
    never reruns the pipeline still needs the ``build_id`` and
    ``output_checksum`` that R1 compares, and the lineage chain R2 walks.

    Keying the directory by ``build_id`` means two builds of the same recipe
    land in the same place, which is what makes an R1 repeat a comparison
    against the previous result rather than an accumulation of directories.
    """

    DATA_DIRNAME = "data"

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def directory(self, dataset: str, layer: Layer, build_id: str) -> Path:
        return self.root / dataset / layer / build_id

    def directory_for(self, provenance: Provenance) -> Path:
        return self.directory(
            provenance.inputs.dataset, provenance.inputs.layer, provenance.build_id
        )

    def data_directory(self, dataset: str, layer: Layer, build_id: str) -> Path:
        """Where a build writes its artifact bytes.

        Separate from the build directory so that ``.gitignore`` can exclude the
        bytes without excluding the record beside them — a directory git ignores
        cannot have individual files rescued back out of it.
        """
        return self.directory(dataset, layer, build_id) / self.DATA_DIRNAME

    def data_directory_for(self, provenance: Provenance) -> Path:
        return self.data_directory(
            provenance.inputs.dataset, provenance.inputs.layer, provenance.build_id
        )

    def write(self, provenance: Provenance) -> Path:
        path = self.directory_for(provenance) / PROVENANCE_FILENAME
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(provenance.to_json(), indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return path

    def load(self, dataset: str, layer: Layer, build_id: str) -> Provenance:
        path = self.directory(dataset, layer, build_id) / PROVENANCE_FILENAME
        if not path.exists():
            raise ProvenanceError(f"no build recorded at {dataset}/{layer}/{build_id}")
        return Provenance.from_json(json.loads(path.read_text(encoding="utf-8")))

    def find(self, build_id: str) -> Provenance:
        """Locate a build by id alone, for walking lineage across layers."""
        for path in self.root.glob(f"*/*/{build_id}/{PROVENANCE_FILENAME}"):
            return Provenance.from_json(json.loads(path.read_text(encoding="utf-8")))
        raise ProvenanceError(f"no build recorded with id {build_id}")

    def list_builds(
        self, dataset: str | None = None, layer: Layer | None = None
    ) -> list[Provenance]:
        """Recorded builds, oldest first."""
        pattern = f"{dataset or '*'}/{layer or '*'}/*/{PROVENANCE_FILENAME}"
        builds = [
            Provenance.from_json(json.loads(path.read_text(encoding="utf-8")))
            for path in self.root.glob(pattern)
        ]
        return sorted(builds, key=lambda p: p.built_at)

    def lineage(self, build_id: str) -> list[Provenance]:
        """The chain that produced ``build_id``, Bronze first.

        R2 reports where a schema broke; without the chain, a Gold-level failure
        cannot be attributed to the layer that introduced it.
        """
        chain: list[Provenance] = []
        seen: set[str] = set()
        current: str | None = build_id
        while current is not None:
            if current in seen:
                raise ProvenanceError(f"lineage of {build_id} contains a cycle at {current}")
            seen.add(current)
            provenance = self.find(current)
            chain.append(provenance)
            current = provenance.inputs.upstream_build_id
        return list(reversed(chain))


__all__ = [
    "BuildInputs",
    "Environment",
    "PROVENANCE_FILENAME",
    "Provenance",
    "ProvenanceError",
    "ProvenanceStore",
    "TRACKED_PACKAGES",
    "config_hash",
    "record_build",
]
