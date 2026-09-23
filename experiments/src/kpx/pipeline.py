"""Which code and which configuration produced an artifact.

R1 claims that identical source, identical code and identical config produce
identical output. Two of the three are already pinned — the source by
:mod:`kpx.snapshot`, the output by its digest in :mod:`kpx.provenance`. This
module pins the middle one.

:class:`~kpx.provenance.BuildInputs` already carries ``pipeline_version`` as a
plain string. This module is what produces that string::

    pipeline_version = <builder_version>+<config_hash[:12]>
                       ^ the code           ^ the configuration

One identifier, which moves if either half moves, quoted in the paper and stored
in every result row. The component versions are kept beside it, because a reader
debugging a mismatch needs to know *which* half moved.

R2 needs the same record for the opposite reason: it deliberately varies the
source across T1/T2/T3 and concludes the pipeline is stable under that
variation. The conclusion only follows if the pipeline itself did not move, so
:func:`assert_same_pipeline` checks it rather than assuming it.

What the builder records today
------------------------------

``kpubdata-builder`` writes a ``BuildManifest`` with ``build_id``,
``started_at``/``finished_at``, ``inputs``, ``outputs``, ``warnings``,
``errors`` and ``row_counts``. It does **not** record which version of itself or
of ``kpubdata`` ran — the package defines ``__version__`` but never writes it
into the manifest.

So :meth:`PipelineVersion.from_build_manifest` reads what the manifest has and
takes the versions from the caller or from the installed distributions, marking
anything it cannot establish ``unknown`` rather than guessing. A version column
reading ``unknown`` is honest; a guessed one silently weakens every R1 and R2
claim built on it. Teaching the builder to stamp its own version belongs with
the Bronze export work (issue #2); until then ``capture`` — which reads the
installed distributions — is the accurate path, and it is accurate only when the
build ran in the environment now doing the reading.

The harness never imports ``kpubdata_builder``. Manifests are consumed as plain
data, which is what lets a reader verify a published artifact without installing
the builder at all.
"""

from __future__ import annotations

import hashlib
import json
import platform
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from importlib import metadata
from pathlib import Path, PurePath
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from kpx.contract import Layer
    from kpx.provenance import Provenance, ProvenanceStore

#: How much of the config hash goes into the citable identifier. Twelve hex
#: characters is the width the snapshot id uses, for the same reason: long
#: enough that a collision is not a practical worry, short enough to read.
CONFIG_HASH_PREFIX = 12

UNKNOWN = "unknown"


class PipelineError(RuntimeError):
    """Raised when pipeline identity is missing, malformed, or inconsistent."""


def canonical_config(config: Mapping[str, Any]) -> str:
    """Serialize a transformation config so that equal configs serialize equally.

    Keys are sorted, so a config assembled in another order hashes the same.
    ``Path`` values are written POSIX-style, because ``str(Path)`` yields
    backslashes on Windows and a config naming a directory would otherwise hash
    differently there — the defect that made snapshot ids platform-dependent,
    reached through a different door.

    ``NaN`` and infinities are rejected. They are not valid JSON, and a config
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
    """The code and configuration that produced an artifact."""

    builder_version: str
    config_hash: str
    kpubdata_version: str = UNKNOWN
    python_version: str = UNKNOWN
    builder_build_id: str | None = None

    @property
    def identifier(self) -> str:
        """``<builder_version>+<config_hash[:12]>`` — what R1 holds fixed."""
        return f"{self.builder_version}+{self.config_hash[:CONFIG_HASH_PREFIX]}"

    @property
    def is_complete(self) -> bool:
        """Whether every component version could actually be established.

        A run whose pipeline version is incomplete is still recorded, but the
        gap belongs in the methodology section rather than in a footnote nobody
        writes later.
        """
        return UNKNOWN not in (self.builder_version, self.kpubdata_version, self.python_version)

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
        builder_build_id: str | None = None,
    ) -> PipelineVersion:
        """Record the versions installed here, plus this config's hash.

        Accurate only when the build ran in the environment now doing the
        reading — which is the case when the harness drives the build itself.
        """
        return cls(
            builder_version=builder_version or _installed("kpubdata-builder"),
            config_hash=config_hash(config),
            kpubdata_version=_installed("kpubdata"),
            python_version=platform.python_version(),
            builder_build_id=builder_build_id,
        )

    @classmethod
    def from_build_manifest(
        cls,
        manifest: Mapping[str, Any],
        config: Mapping[str, Any],
        *,
        builder_version: str | None = None,
        kpubdata_version: str | None = None,
        python_version: str | None = None,
    ) -> PipelineVersion:
        """Read a builder ``BuildManifest``, adding the config hash.

        The manifest is consumed as plain data; the harness does not import
        ``kpubdata_builder``. Today's manifest carries no version fields at all,
        so they are taken from the arguments, else from a ``build_environment``
        object if a future manifest grows one, else left ``unknown``. Nothing is
        guessed: an ``unknown`` in a version column is honest, and a guess would
        silently weaken every claim resting on it.
        """
        environment = manifest.get("build_environment") or {}
        if not isinstance(environment, Mapping):
            raise PipelineError("build_environment in the manifest is not an object")

        def pick(explicit: str | None, key: str) -> str:
            return str(explicit if explicit is not None else environment.get(key, UNKNOWN))

        return cls(
            builder_version=pick(builder_version, "builder_version"),
            config_hash=config_hash(config),
            kpubdata_version=pick(kpubdata_version, "kpubdata_version"),
            python_version=pick(python_version, "python_version"),
            builder_build_id=_optional_str(manifest.get("build_id")),
        )


def assert_same_pipeline(builds: Iterable[Provenance]) -> str:
    """Return the pipeline version shared by ``builds``, or raise.

    R2's precondition. It varies the source across T1/T2/T3 and concludes the
    pipeline is stable under that variation; comparing builds made by different
    pipeline versions would attribute a pipeline change to the source.
    """
    versions = {build.inputs.pipeline_version for build in builds}
    if not versions:
        raise PipelineError("no builds to compare")
    if len(versions) > 1:
        raise PipelineError(
            f"builds were made by different pipeline versions: {', '.join(sorted(versions))}; "
            f"a comparison across them would attribute a pipeline change to the source"
        )
    return versions.pop()


# -- internals -------------------------------------------------------------


def _canonical(value: Any) -> Any:
    """Rewrite a config into JSON-serializable, platform-independent values."""
    if isinstance(value, PurePath):
        return value.as_posix()
    if isinstance(value, Mapping):
        return {str(key): _canonical(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _installed(distribution: str) -> str:
    try:
        return metadata.version(distribution)
    except metadata.PackageNotFoundError:
        return UNKNOWN


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _layer_columns(manifest: Mapping[str, Any], alias: str) -> tuple[str, ...]:
    """Column names the builder reported for ``alias``, or empty if it did not.

    Empty is honest. Inventing names here would make schema comparisons in R2
    compare something the builder never said.
    """
    summaries = manifest.get("schema_summaries") or {}
    fields = (summaries.get(alias) or {}).get("fields") or []
    names = [field.get("name") for field in fields if isinstance(field, Mapping)]
    return tuple(name for name in names if isinstance(name, str))


def record_layer_chain(
    run_dir: Path | str,
    *,
    dataset: str,
    snapshot_id: str,
    config: Mapping[str, Any],
    alias: str,
    store: ProvenanceStore,
    layers: Sequence[Layer] = ("bronze", "silver"),
) -> dict[Layer, Provenance]:
    """Record one builder run as a chain of layer builds.

    The builder writes its layers under ``<run_dir>/<layer>/<alias>/`` and a
    ``manifest.json`` beside them. This turns that into the provenance chain R1
    and R2 rest on: each layer names the build it was derived from, so
    :meth:`ProvenanceStore.lineage` can walk a Gold build back to the snapshot
    it came from.

    The bytes are **not** copied into the store. They already exist in the build
    directory, and a second copy of a 140 MiB Bronze artifact per build buys
    nothing — ``output_checksum`` identifies them, and that is what the
    committed record needs to carry.

    The harness reads the manifest as plain data; it never imports
    ``kpubdata_builder``, which is installed in a different environment.
    """
    # provenance가 이 모듈의 config_hash를 쓰므로 반대 방향은 여기서 찾는다.
    from kpx.provenance import BuildInputs, ProvenanceError, record_build

    run_dir = Path(run_dir)
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        raise ProvenanceError(f"no build manifest at {manifest_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    version = PipelineVersion.from_build_manifest(manifest, config)
    status = str(manifest.get("status", "unknown"))
    row_count = int((manifest.get("row_counts") or {}).get(alias, 0))
    columns = _layer_columns(manifest, alias)

    recorded: dict[Layer, Provenance] = {}
    upstream: str | None = None
    for layer in layers:
        artifact = run_dir / layer / alias
        if not artifact.is_dir():
            raise ProvenanceError(f"the build left no {layer} artifact at {artifact}")

        provenance = record_build(
            artifact,
            inputs=BuildInputs(
                dataset=dataset,
                layer=layer,
                snapshot_id=snapshot_id,
                pipeline_version=version.identifier,
                config_hash=version.config_hash,
                upstream_build_id=upstream,
            ),
            row_count=row_count,
            columns=columns,
            status=status,
        )
        store.write(provenance)
        recorded[layer] = provenance
        upstream = provenance.build_id

    return recorded


def record_derived_layer(
    artifact: Path | str,
    *,
    layer: Layer,
    upstream: Provenance,
    row_count: int,
    columns: tuple[str, ...] | list[str],
    store: ProvenanceStore,
    status: str = "ok",
) -> Provenance:
    """Record a layer the harness derived from an upstream build.

    Task 1's Gold is built here rather than by the builder, whose Gold stage does
    packaging and not aggregation. That deviation is recorded in Threats; what
    must not also happen is the artifact escaping the provenance chain, because
    then nothing ties the analysis back to the snapshot it read.

    Snapshot and pipeline version are inherited from ``upstream`` rather than
    passed in. A Gold built from a Silver *is* from that Silver's snapshot, and
    letting a caller say otherwise would let the chain lie.
    """
    from kpx.provenance import BuildInputs, record_build

    provenance = record_build(
        artifact,
        inputs=BuildInputs(
            dataset=upstream.inputs.dataset,
            layer=layer,
            snapshot_id=upstream.inputs.snapshot_id,
            pipeline_version=upstream.inputs.pipeline_version,
            config_hash=upstream.inputs.config_hash,
            upstream_build_id=upstream.build_id,
        ),
        row_count=row_count,
        columns=columns,
        status=status,
    )
    store.write(provenance)
    return provenance


def assert_same_inputs(builds: Iterable[Provenance]) -> None:
    """Refuse a set of builds that did not read the same source or code.

    A measurement assembled from artifacts of different snapshots, or built by
    different pipeline versions, cannot say which input produced its numbers.
    Failing here is cheaper than discovering it in the results.

    R2 is the deliberate exception on one axis: it varies the snapshot on
    purpose, so it checks :func:`assert_same_pipeline` alone.
    """
    from kpx.provenance import ProvenanceError

    builds = list(builds)
    if not builds:
        raise ProvenanceError("no builds to compare")

    snapshots = {build.inputs.snapshot_id for build in builds}
    if len(snapshots) > 1:
        raise ProvenanceError(f"builds read different snapshots: {sorted(snapshots)}")

    versions = {build.inputs.pipeline_version for build in builds}
    if len(versions) > 1:
        raise ProvenanceError(f"builds used different pipeline versions: {sorted(versions)}")
