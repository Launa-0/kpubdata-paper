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
``errors``, ``row_counts``, ``schema_summaries`` and a ``build_environment``
naming the builder, ``kpubdata`` and Python versions that ran.

:meth:`PipelineVersion.from_build_manifest` reads those rather than the versions
installed wherever the manifest is being read. The distinction matters: builds
run in the builder environment and are recorded from the harness environment,
so reading the local interpreter would describe the wrong machine. What the
manifest does not say is left ``unknown`` rather than guessed — an ``unknown``
in a version column is honest, and a guess silently weakens every R1 and R2
claim resting on it.

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
    from kpx.provenance import Environment, Provenance, ProvenanceStore
    from kpx.snapshot import Snapshot

#: How much of the config hash goes into the citable identifier. Twelve hex
#: characters is the width the snapshot id uses, for the same reason: long
#: enough that a collision is not a practical worry, short enough to read.
CONFIG_HASH_PREFIX = 12

UNKNOWN = "unknown"

#: Keys dropped before a declared BuildSpec is hashed into ``config_hash``.
#:
#: A deny list, not an allow list. An allow list is how ``derived`` came to be
#: left out of the identifier: a rule was added to the spec, nobody remembered
#: to add it here, and the recipe changed while ``pipeline_version`` stood
#: still. With a deny list a new spec field is part of the identity by default
#: and someone has to name it in writing to take it out.
#:
#: What is named here changes no bytes. ``upload_id`` is a new row in the upload
#: store on every run; ``description`` is the sentence the calling script passed;
#: ``output_path`` is where the parquet lands, not what is in it. Hashing those
#: would make R1's repeated builds and R2's T1/T2/T3 look like different
#: pipelines, which is the opposite failure.
RUN_SCOPED_KEYS = frozenset(
    {"upload_id", "title", "description", "metadata", "publish", "output_path"}
)


class PipelineError(RuntimeError):
    """Raised when pipeline identity is missing, malformed, or inconsistent."""


def transformation_recipe(spec: Mapping[str, Any]) -> dict[str, Any]:
    """The part of a declared BuildSpec that decides what the output contains.

    One place, so that no script assembles its own idea of what the recipe is.
    Every rule the spec declares — ``read_as``, ``rename``, ``casts``,
    ``required``, ``derived``, ``null_tokens``, ``dtypes``, the export kind —
    is in the hash unless :data:`RUN_SCOPED_KEYS` names it out.
    """
    return dict(_without_run_scoped(spec))


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
        ``kpubdata_builder``. Versions come from the arguments, else from the
        manifest's ``build_environment``, else ``unknown``. Nothing falls back
        to the versions installed here: this is read in the harness environment
        and the build ran in the builder's.
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

    def build_environment(self) -> Environment:
        """Where the build ran, as :mod:`kpx.provenance` records environments.

        ``platform`` stays ``unknown``: the manifest does not say which machine
        built the artifact, and filling in the machine reading the manifest
        would put the harness host on a record describing a builder run. That
        matters beyond tidiness — :meth:`Environment.differences` exists to
        answer "did the environment move?" when a rebuild's checksum differs,
        and it can only answer honestly if it was never quietly invented.
        """
        from kpx.provenance import Environment

        packages = {
            "kpubdata-builder": self.builder_version,
            "kpubdata": self.kpubdata_version,
        }
        return Environment(
            python_version=self.python_version,
            platform=UNKNOWN,
            packages={name: version for name, version in packages.items() if version != UNKNOWN},
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


def _without_run_scoped(value: Any) -> Any:
    """Drop :data:`RUN_SCOPED_KEYS` wherever they appear, at any depth.

    Nested because the keys are: ``upload_id`` sits inside a source and
    ``output_path`` inside an export, not at the top of the spec.
    """
    if isinstance(value, Mapping):
        return {
            str(key): _without_run_scoped(item)
            for key, item in value.items()
            if key not in RUN_SCOPED_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [_without_run_scoped(item) for item in value]
    return value


def _layer_columns(manifest: Mapping[str, Any], alias: str) -> tuple[str, ...]:
    """Column names the builder reported for ``alias``, or empty if it did not.

    Empty is honest. Inventing names here would make schema comparisons in R2
    compare something the builder never said.
    """
    summaries = manifest.get("schema_summaries") or {}
    fields = (summaries.get(alias) or {}).get("fields") or []
    names = [field.get("name") for field in fields if isinstance(field, Mapping)]
    return tuple(name for name in names if isinstance(name, str))


def _bronze_shape(artifact: Path, snapshot: Snapshot) -> tuple[int, tuple[str, ...]]:
    """What Bronze actually holds — not what Silver holds.

    The manifest describes the *canonical* output: ``row_counts`` is the rows
    that survived to Silver and ``schema_summaries`` names Silver's renamed,
    cast, derived columns. Applying either to Bronze made the Bronze record
    claim ``apt_name``/``build_year``, columns that exist nowhere in the frozen
    source, and made row loss between the layers invisible by construction.

    Bronze answers for itself: the builder's own Bronze ``metadata.json`` for
    the row count, the frozen snapshot for the columns. Both are records of the
    raw pull rather than of the contract applied to it.
    """
    records = sorted(artifact.rglob("metadata.json"))
    if not records:
        raise PipelineError(f"the bronze artifact at {artifact} carries no metadata.json")
    payload = json.loads(records[0].read_text(encoding="utf-8"))
    if "record_count" not in payload:
        raise PipelineError(f"{records[0]} does not report a record_count")
    return int(payload["record_count"]), snapshot.columns


def record_layer_chain(
    run_dir: Path | str,
    *,
    snapshot: Snapshot,
    config: Mapping[str, Any],
    alias: str,
    store: ProvenanceStore,
    dataset: str | None = None,
    layers: Sequence[Layer] = ("bronze", "silver"),
) -> dict[Layer, Provenance]:
    """Record one builder run as a chain of layer builds.

    The builder writes its layers under ``<run_dir>/<layer>/<alias>/`` and a
    ``manifest.json`` beside them. This turns that into the provenance chain R1
    and R2 rest on: each layer names the build it was derived from, so
    :meth:`ProvenanceStore.lineage` can walk a Gold build back to the snapshot
    it came from.

    Takes the :class:`~kpx.snapshot.Snapshot` rather than its id, because Bronze
    is described by the frozen pull and not by the manifest — see
    :func:`_bronze_shape`. Passing the record instead of the string also means a
    build cannot be recorded against a snapshot nobody registered.

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
    environment = version.build_environment()
    status = str(manifest.get("status", "unknown"))
    canonical_rows = int((manifest.get("row_counts") or {}).get(alias, 0))
    canonical_columns = _layer_columns(manifest, alias)

    recorded: dict[Layer, Provenance] = {}
    upstream: str | None = None
    for layer in layers:
        artifact = run_dir / layer / alias
        if not artifact.is_dir():
            raise ProvenanceError(f"the build left no {layer} artifact at {artifact}")

        if layer == "bronze":
            row_count, columns = _bronze_shape(artifact, snapshot)
        else:
            row_count, columns = canonical_rows, canonical_columns

        provenance = record_build(
            artifact,
            inputs=BuildInputs(
                dataset=dataset or snapshot.dataset,
                layer=layer,
                snapshot_id=snapshot.snapshot_id,
                pipeline_version=version.identifier,
                config_hash=version.config_hash,
                upstream_build_id=upstream,
            ),
            row_count=row_count,
            columns=columns,
            status=status,
            environment=environment,
        )
        store.write(provenance)
        recorded[layer] = provenance
        upstream = provenance.build_id

    return recorded


def derived_config_hash(upstream: Provenance, recipe: str) -> str:
    """The upstream recipe and the transformation applied on top of it.

    A layer the harness derives has two halves to its identity: the build it
    read and the code that turned it into something else. Inheriting only the
    first — which is what happened before — meant Task 1's Gold kept the same
    ``build_id`` after its aggregation changed, so a record could describe bytes
    it had never seen.

    ``recipe`` is the source of the transformation, not a description of it. A
    hand-written summary of what the code does is a copy that drifts from the
    code, and a copy that drifts is exactly the failure this is fixing. The cost
    is that reformatting the function moves the hash; a build id that moves when
    nothing semantic changed is a nuisance, one that stays put when the
    aggregation changed is a wrong record.
    """
    material = f"{upstream.inputs.config_hash}\n{recipe}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def record_derived_layer(
    artifact: Path | str,
    *,
    layer: Layer,
    upstream: Provenance,
    recipe: str,
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
    letting a caller say otherwise would let the chain lie. ``config_hash`` is
    the one field that is not inherited whole — see :func:`derived_config_hash`.

    Which means the paper cannot say ``pipeline_version`` identifies a derived
    layer's whole recipe. It identifies the upstream pipeline; the derived layer
    is identified by that version together with its own ``config_hash``.
    """
    from kpx.provenance import BuildInputs, record_build

    provenance = record_build(
        artifact,
        inputs=BuildInputs(
            dataset=upstream.inputs.dataset,
            layer=layer,
            snapshot_id=upstream.inputs.snapshot_id,
            pipeline_version=upstream.inputs.pipeline_version,
            config_hash=derived_config_hash(upstream, recipe),
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
