"""Runtime and peak memory for RQ2/H2, plus the environment they were measured in.

A runtime number is only meaningful next to the protocol that produced it, so
the protocol is fixed here rather than chosen per task:

==============  ===========================================================
warm-up         1 run, discarded
measurement     5 runs, all kept
reported        median (into the result schema), with mean and stdev beside
                it for the methodology section
==============  ===========================================================

**Why a warm-up.** The first run pays for imports, lazily-built pandas
machinery, and a cold page cache on the artifact it reads. That cost is real but
it is paid once per session, not once per analysis, so charging it to the first
condition measured would rank conditions by the order they happened to run in.

**Why the median.** Five runs on a shared machine will contain the occasional
outlier from whatever else the OS decided to do. The median ignores it; the
mean and the standard deviation are reported alongside so a reader can see how
noisy the measurement was rather than having to trust that it was not.

**Why garbage is collected before each run, but collection stays enabled.**
Left alone, run *n* pays to collect run *n-1*'s garbage, which shifts cost
between runs that should be independent. Disabling the collector outright — what
``timeit`` does — would instead measure something no real run experiences. So
each run starts from a collected heap and is then timed with the collector on.

Peak memory
-----------

Measured by sampling the process's resident set size in a background thread and
reporting the high-water mark **above the baseline taken just before the run**,
because the absolute figure is dominated by the interpreter and its imports
rather than by the condition being measured.

Two honest caveats, both repeated in the paper:

* CPython does not reliably return freed memory to the OS, so a later run in the
  same process starts from a higher baseline and its delta *under*-reports.
  Peak memory is therefore a secondary figure, reported as the maximum over the
  measured runs, and not used to rank conditions on its own.
* A run shorter than the sampling interval may be missed entirely, so a reading
  is always taken once more when the run ends.
"""

from __future__ import annotations

import gc
import json
import os
import platform
import statistics
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from importlib import metadata
from pathlib import Path
from typing import Any

import psutil

#: The measurement protocol, fixed for every task.
WARMUP_RUNS = 1
MEASURED_RUNS = 5

#: How often the sampler reads RSS while an operation runs.
SAMPLE_INTERVAL_SECONDS = 0.005

BYTES_PER_MIB = 1024 * 1024

#: Libraries whose versions change results and therefore belong in Methodology.
REPORTED_PACKAGES: tuple[str, ...] = (
    "pandas",
    "numpy",
    "pyarrow",
    "scikit-learn",
    "scipy",
    "radon",
    "psutil",
)


@dataclass(frozen=True)
class RuntimeMeasurement:
    """What one operation cost, over the fixed protocol.

    ``result`` is whatever the last measured run returned, kept so that a caller
    which needs the prepared data does not have to run the operation a seventh
    time. It takes no part in equality or repr.
    """

    seconds: tuple[float, ...]
    warmup_seconds: tuple[float, ...] = ()
    peak_memory_mb: float | None = None
    result: Any = field(default=None, repr=False, compare=False)

    @property
    def median(self) -> float:
        """The figure recorded as ``runtime_seconds``."""
        return statistics.median(self.seconds)

    @property
    def mean(self) -> float:
        return statistics.fmean(self.seconds)

    @property
    def stdev(self) -> float | None:
        """``None`` for a single run, where spread is undefined rather than 0."""
        return statistics.stdev(self.seconds) if len(self.seconds) > 1 else None

    @property
    def runs(self) -> int:
        return len(self.seconds)

    def to_dict(self) -> dict[str, Any]:
        """The result-schema fields this measurement fills in."""
        return {"runtime_seconds": self.median, "peak_memory_mb": self.peak_memory_mb}

    def summary(self) -> str:
        """One line for a run log."""
        spread = f" ± {self.stdev:.3f}" if self.stdev is not None else ""
        memory = f", peak +{self.peak_memory_mb:.1f} MiB" if self.peak_memory_mb else ""
        return f"median {self.median:.3f}s{spread} over {self.runs} runs{memory}"


@dataclass(frozen=True)
class Environment:
    """The machine and library versions a measurement was taken on.

    Runtime is only comparable within one environment, so the Methodology
    section has to state this and the artifact has to ship it.
    """

    python_version: str
    implementation: str
    system: str
    release: str
    machine: str
    processor: str
    cpu_count: int | None
    total_memory_gb: float | None
    packages: dict[str, str] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    def to_markdown(self) -> str:
        """The environment block quoted in the Methodology section."""
        memory = f"{self.total_memory_gb:.1f} GB" if self.total_memory_gb else "unknown"
        versions = ", ".join(f"{name} {version}" for name, version in self.packages.items())
        cores = f"{self.cpu_count} logical cores" if self.cpu_count else "unknown core count"
        return (
            f"- OS: {self.system} {self.release} ({self.machine})\n"
            f"- CPU: {self.processor or self.machine}, {cores}\n"
            f"- RAM: {memory}\n"
            f"- Python: {self.python_version} ({self.implementation})\n"
            f"- Libraries: {versions}"
        )


def describe_environment(packages: tuple[str, ...] = REPORTED_PACKAGES) -> Environment:
    """Record the machine and library versions, for the Methodology section.

    A package that is not installed is omitted rather than recorded as unknown:
    the analysis extras are genuinely optional, and "scipy: not installed" in a
    paper's environment table says nothing a reader can use.
    """
    installed: dict[str, str] = {}
    for name in packages:
        try:
            installed[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            continue

    try:
        total_memory_gb: float | None = psutil.virtual_memory().total / 1e9
    except Exception:  # pragma: no cover - psutil cannot read the host
        total_memory_gb = None

    return Environment(
        python_version=platform.python_version(),
        implementation=platform.python_implementation(),
        system=platform.system(),
        release=platform.release(),
        machine=platform.machine(),
        processor=platform.processor(),
        cpu_count=os.cpu_count(),
        total_memory_gb=total_memory_gb,
        packages=installed,
    )


def measure(
    operation: Callable[[], Any],
    *,
    warmup: int = WARMUP_RUNS,
    repeat: int = MEASURED_RUNS,
    memory: bool = True,
) -> RuntimeMeasurement:
    """Run ``operation`` under the fixed protocol and report what it cost.

    Defaults are the protocol the paper states: one warm-up, five measured runs.
    They are parameters only so that tests need not run everything six times —
    a task must not quietly measure itself differently.
    """
    if repeat < 1:
        raise ValueError("at least one measured run is required")
    if warmup < 0:
        raise ValueError("warm-up count cannot be negative")

    warmups = tuple(_time_once(operation)[0] for _ in range(warmup))

    seconds: list[float] = []
    peaks: list[float] = []
    result: Any = None
    for _ in range(repeat):
        elapsed, result, peak = _time_once(operation, memory=memory)
        seconds.append(elapsed)
        if peak is not None:
            peaks.append(peak)

    return RuntimeMeasurement(
        seconds=tuple(seconds),
        warmup_seconds=warmups,
        peak_memory_mb=max(peaks) if peaks else None,
        result=result,
    )


def write_environment(path: Path | str) -> Environment:
    """Record the environment beside the results, as JSON."""
    environment = describe_environment()
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(environment.to_json(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return environment


# -- internals -------------------------------------------------------------


def _time_once(
    operation: Callable[[], Any], *, memory: bool = False
) -> tuple[float, Any, float | None]:
    """Time one run from a collected heap, optionally sampling peak RSS."""
    gc.collect()
    if not memory:
        started = time.perf_counter()
        result = operation()
        return time.perf_counter() - started, result, None

    with _PeakSampler() as sampler:
        started = time.perf_counter()
        result = operation()
        elapsed = time.perf_counter() - started
    return elapsed, result, sampler.peak_mib


class _PeakSampler:
    """Samples this process's RSS in a background thread.

    Reports the high-water mark above the baseline read at entry, so the figure
    is what the operation added rather than what the interpreter already held.
    """

    def __init__(self, interval: float = SAMPLE_INTERVAL_SECONDS) -> None:
        self.interval = interval
        self._process = psutil.Process()
        self._baseline = 0
        self._peak = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> _PeakSampler:
        self._baseline = self._rss()
        self._peak = self._baseline
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        # A run shorter than one interval may have produced no sample at all.
        self._peak = max(self._peak, self._rss())

    @property
    def peak_mib(self) -> float:
        return max(0.0, (self._peak - self._baseline) / BYTES_PER_MIB)

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            self._peak = max(self._peak, self._rss())

    def _rss(self) -> int:
        try:
            return int(self._process.memory_info().rss)
        except psutil.Error:  # pragma: no cover - the process always exists here
            return self._peak
