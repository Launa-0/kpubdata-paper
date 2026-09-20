"""Which code and which configuration produced a dataset artifact.

R1 claims that identical source, identical code and identical config produce
identical output. Two of those three are already pinned: the source by
:mod:`kpx.snapshot`, the output by its digest. This module pins the middle one
and stamps it on every built artifact, so that "identical code and config" is
something a reader can check rather than something the paper asserts.

R2 needs the same record for the opposite reason. It deliberately varies the
source across T1/T2/T3 and must show that *only* the source varied — which
requires every one of those builds to name the same pipeline version.

What the builder already records, and what this adds
----------------------------------------------------

``kpubdata-builder`` writes a ``BuildManifest`` carrying its own
``build_environment`` (Python, ``kpubdata`` and builder versions), per-source
provenance with checksums, and an inputs fingerprint. None of that is
reimplemented here: :meth:`PipelineVersion.from_build_manifest` reads it.

What the manifest does not have is a single identifier for *the thing R1 holds
fixed*. Code version and configuration are separate fields there, and a claim
that has to be reconstructed from several fields is a claim a reader will get
wrong. So:

.. code-block:: text

    pipeline_version = <builder_version>+<config_hash[:12]>
                       ^ the code            ^ the configuration

One string, changing if either half changes, quoted in the paper and stored in
every result row.

The configuration hash
----------------------

Hashed from canonical JSON: keys sorted, so a dict rebuilt in another order
hashes the same; ``Path`` values written POSIX-style, so a config naming a
directory does not hash differently on Windows — the same defect that made
snapshot ids platform-dependent (#31), reached by another route.

The harness never imports ``kpubdata_builder``. It consumes artifacts and their
manifests as data, which is what lets a reader verify a published artifact
without installing the builder at all.
"""

from __future__ import annotations

import hashlib
import json
import platform
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import datetime
from importlib import metadata
from pathlib import Path, PurePath
from typing import Any

from kpx.contract import LAYERS, Layer
from kpx.digest import digest_tree

METADATA_FILENAME = "artifact.json"
DATA_DIRNAME = "data"
SCHEMA_VERSION = 1

#: How much of the config hash goes into the citable identifier. Twelve hex
#: characters is the same width the snapshot id uses, for the same reason: long
#: enough that a collision is not a practical worry, short enough to read.
CONFIG_HASH_PREFIX = 12

UNKNOWN = "unknown"


class PipelineError(RuntimeError):
    """Raised when artifact provenance is missing, malformed, or inconsistent."""


def canonical_config(config: Mapping[str, Any]) -> str:
    """Serialize a transformation config so that equal configs serialize equally.

    Keys are sorted, so a config assembled in a different order hashes the same.
    ``Path`` values are written POSIX-style, because ``str(Path)`` yields
    backslashes on Windows and a config that names a directory would otherwise
    hash differently there — the defect that made snapshot ids
    platform-dependent, reached through a different door.

    ``NaN`` and infinities are rejected: they are not valid JSON, and a config
    holding one is a mistake worth surfacing at build time rather than a value
    worth hashing.
    """
    return json.dumps(
        _canonical(config),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )


def config_hash(config: Mapping[str, Any]) -> str:
    """SHA-256 of a transformation config's canonical form."""
    return hashlib.sha256(canonical_config(config).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PipelineVersion:
    """The code and configuration that produced an artifact.

    ``identifier`` is the single string the paper quotes and every result row
    stores. The component versions are kept beside it because a reader
    debugging a mismatch needs to know *which* half moved.
    """

    builder_version: str
    config_hash: str
    kpubdata_version: str = UNKNOWN
    python_version: str = UNKNOWN
    build_id: str | None = None

    @property
    def identifier(self) -> str:
        """``<builder_version>+<config_hash[:12]>`` — what R1 holds fixed."""
        return f"{self.builder_version}+{self.config_hash[:CONFIG_HASH_PREFIX]}"

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, payload: Mapping[str, Any]) -> PipelineVersion:
        return cls(**dict(payload))

    @classmethod
    def capture(
        cls,
        config: Mapping[str, Any],
        *,
        builder_version: str | None = None,
        build_id: str | None = None,
    ) -> PipelineVersion:
        """Record the versions installed here, plus this config's hash.

        Used when the harness drives the build itself. When the builder wrote a
        manifest, prefer :meth:`from_build_manifest`: the manifest states what
        actually ran, while this states what happens to be installed now.
        """
        return cls(
            builder_version=builder_version or _installed("kpubdata-builder"),
            config_hash=config_hash(config),
            kpubdata_version=_installed("kpubdata"),
            python_version=platform.python_version(),
            build_id=build_id,
        )

    @classmethod
    def from_build_manifest(
        cls, manifest: Mapping[str, Any], config: Mapping[str, Any]
    ) -> PipelineVersion:
        """Read the builder's own ``BuildManifest``, adding the config hash.

        The manifest is consumed as plain data — the harness does not import
        ``kpubdata_builder``, so a reader can verify a published artifact
        without installing it. Fields the manifest omits become ``unknown``
        rather than raising: a legacy manifest should still be readable, and
        ``unknown`` in a version column is honest where a guess would not be.
        """
        environment = manifest.get("build_environment") or {}
        if not isinstance(environment, Mapping):
            raise PipelineError("build_environment in the manifest is not an object")
        return cls(
            builder_version=str(environment.get("builder_version", UNKNOWN)),
            config_hash=config_hash(config),
            kpubdata_version=str(environment.get("kpubdata_version", UNKNOWN)),
            python_version=str(environment.get("python_version", UNKNOWN)),
            build_id=_optional_str(manifest.get("build_id")),
        )


@dataclass(frozen=True)
class DatasetArtifact:
    """One built layer of one dataset, and where it came from.

    The three things a result row needs to be replayable — which source, which
    code and config, which bytes — are all here, which is why the artifact
    record rather than the build log is what a run reads.
    """

    dataset: str
    layer: Layer
    snapshot_id: str
    pipeline: PipelineVersion
    row_count: int
    columns: tuple[str, ...]
    checksum: str
    size_bytes: int
    file_count: int
    built_at: datetime
    notes: str = ""
    metadata_schema_version: int = SCHEMA_VERSION

    @property
    def pipeline_version(self) -> str:
        return self.pipeline.identifier

    def run_fields(self) -> dict[str, str]:
        """The result-schema fields a run reading this artifact must record."""
        return {"source_snapshot": self.snapshot_id, "pipeline_version": self.pipeline_version}

    def citation(self) -> str:
        """The provenance block quoted in the paper."""
        return (
            f"Dataset: {self.dataset} ({self.layer})\n"
            f"Source snapshot: {self.snapshot_id}\n"
            f"Pipeline version: {self.pipeline_version}\n"
            f"Builder: {self.pipeline.builder_version}, "
            f"kpubdata: {self.pipeline.kpubdata_version}\n"
            f"Config SHA-256: {self.pipeline.config_hash}\n"
            f"Rows: {self.row_count:,}\n"
            f"SHA-256: {self.checksum}"
        )

    def to_json(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["built_at"] = self.built_at.isoformat()
        payload["columns"] = list(self.columns)
        payload["pipeline"] = self.pipeline.to_json()
        return payload

    @classmethod
    def from_json(cls, payload: Mapping[str, Any]) -> DatasetArtifact:
        version = int(payload.get("metadata_schema_version", SCHEMA_VERSION))
        if version > SCHEMA_VERSION:
            raise PipelineError(
                f"artifact metadata is version {version}, this harness understands "
                f"{SCHEMA_VERSION}; upgrade kpx rather than reading it partially"
            )
        data = dict(payload)
        data["built_at"] = datetime.fromisoformat(data["built_at"])
        data["columns"] = tuple(data["columns"])
        data["pipeline"] = PipelineVersion.from_json(data["pipeline"])
        return cls(**data)


def assert_same_pipeline(artifacts: Iterable[DatasetArtifact]) -> str:
    """Return the pipeline version shared by ``artifacts``, or raise.

    R2 varies the source across T1/T2/T3 and concludes that the pipeline is
    stable under that variation. The conclusion only follows if the pipeline
    itself did not move, so the check is run rather than assumed.
    """
    versions = {artifact.pipeline_version for artifact in artifacts}
    if not versions:
        raise PipelineError("no artifacts to compare")
    if len(versions) > 1:
        raise PipelineError(
            f"artifacts were built by different pipeline versions: "
            f"{', '.join(sorted(versions))}; a comparison across them would "
            f"attribute a pipeline change to the source"
        )
    return versions.pop()


class ArtifactStore:
    """Registers, reads and verifies built dataset artifacts.

    Laid out like the snapshot store, for the same reason: the record is small
    and committed, the data is large and republished.

    .. code-block:: text

        datasets/<dataset>/<layer>/
        ├── artifact.json   # the DatasetArtifact record; committed
        └── data/           # the built files; git-ignored
    """

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    # -- locations ---------------------------------------------------------

    def directory(self, dataset: str, layer: Layer) -> Path:
        if layer not in LAYERS:
            raise PipelineError(f"unknown layer: {layer!r}")
        return self.root / dataset / layer

    def data_path(self, dataset: str, layer: Layer) -> Path:
        """Where the built files for one layer live."""
        return self.directory(dataset, layer) / DATA_DIRNAME

    # -- writing -----------------------------------------------------------

    def register(
        self,
        source: Path | str,
        *,
        dataset: str,
        layer: Layer,
        snapshot_id: str,
        pipeline: PipelineVersion,
        row_count: int,
        columns: tuple[str, ...] | list[str],
        built_at: datetime | None = None,
        notes: str = "",
    ) -> DatasetArtifact:
        """Digest a freshly built layer and record what produced it.

        ``source`` is read in place rather than copied: unlike a snapshot, a
        built artifact can be rebuilt from its snapshot and pipeline version, so
        the store keeps the record authoritative and the bytes replaceable.
        """
        digest = digest_tree(Path(source))
        artifact = DatasetArtifact(
            dataset=dataset,
            layer=layer,
            snapshot_id=snapshot_id,
            pipeline=pipeline,
            row_count=row_count,
            columns=tuple(columns),
            checksum=digest.sha256,
            size_bytes=digest.size_bytes,
            file_count=digest.file_count,
            built_at=built_at or datetime.now().astimezone(),
            notes=notes,
        )
        self._write(artifact)
        return artifact

    def _write(self, artifact: DatasetArtifact) -> None:
        path = self.directory(artifact.dataset, artifact.layer) / METADATA_FILENAME
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(artifact.to_json(), indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    # -- reading -----------------------------------------------------------

    def load(self, dataset: str, layer: Layer) -> DatasetArtifact:
        path = self.directory(dataset, layer) / METADATA_FILENAME
        if not path.exists():
            raise PipelineError(
                f"no artifact registered for {dataset} ({layer}); a run cannot record "
                f"which pipeline version produced data it cannot identify"
            )
        return DatasetArtifact.from_json(json.loads(path.read_text(encoding="utf-8")))

    def list_artifacts(self, dataset: str | None = None) -> list[DatasetArtifact]:
        """Every registered artifact, by dataset then Medallion layer order."""
        pattern = f"{dataset}/*/{METADATA_FILENAME}" if dataset else f"*/*/{METADATA_FILENAME}"
        artifacts = [
            DatasetArtifact.from_json(json.loads(path.read_text(encoding="utf-8")))
            for path in self.root.glob(pattern)
        ]
        order = {layer: index for index, layer in enumerate(LAYERS)}
        return sorted(artifacts, key=lambda a: (a.dataset, order.get(a.layer, len(order))))

    def pipeline_version(self, dataset: str, layer: Layer) -> str:
        return self.load(dataset, layer).pipeline_version

    # -- verification ------------------------------------------------------

    def verify(self, dataset: str, layer: Layer) -> VerifyResult:
        """Re-digest the built bytes and compare against the recorded checksum."""
        artifact = self.load(dataset, layer)
        data = self.data_path(dataset, layer)
        if not data.exists():
            return VerifyResult(
                dataset=dataset,
                layer=layer,
                ok=False,
                expected=artifact.checksum,
                actual=None,
                reason=f"built data is not present at {data}",
            )
        actual = digest_tree(data)
        if actual.sha256 != artifact.checksum:
            return VerifyResult(
                dataset=dataset,
                layer=layer,
                ok=False,
                expected=artifact.checksum,
                actual=actual.sha256,
                reason="built bytes do not match the recorded checksum",
            )
        return VerifyResult(
            dataset=dataset, layer=layer, ok=True, expected=artifact.checksum, actual=actual.sha256
        )

    def verify_all(self, dataset: str | None = None) -> list[VerifyResult]:
        return [self.verify(a.dataset, a.layer) for a in self.list_artifacts(dataset)]


@dataclass(frozen=True)
class VerifyResult:
    """Outcome of re-digesting one artifact's built bytes."""

    dataset: str
    layer: Layer
    ok: bool
    expected: str
    actual: str | None
    reason: str = ""

    def raise_for_status(self) -> None:
        if not self.ok:
            raise PipelineError(f"{self.dataset} ({self.layer}) failed verification: {self.reason}")


def default_artifacts(root: Path | str | None = None) -> ArtifactStore:
    """The store at ``experiments/datasets`` unless told otherwise."""
    if root is not None:
        return ArtifactStore(root)
    return ArtifactStore(Path(__file__).resolve().parents[2] / "datasets")


# -- internals -------------------------------------------------------------


def _canonical(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _canonical(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_canonical(item) for item in value]
    if isinstance(value, PurePath):
        return value.as_posix()
    if isinstance(value, str | bool | int | float) or value is None:
        return value
    return str(value)


def _installed(package: str) -> str:
    try:
        return metadata.version(package)
    except metadata.PackageNotFoundError:
        return UNKNOWN


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)
