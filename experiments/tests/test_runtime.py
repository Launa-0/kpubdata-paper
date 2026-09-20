from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from kpx.metrics.runtime import (
    MEASURED_RUNS,
    WARMUP_RUNS,
    RuntimeMeasurement,
    describe_environment,
    measure,
    write_environment,
)

MIB = 1024 * 1024


class Counter:
    """An operation that records how often it ran."""

    def __init__(self, returns: object = None) -> None:
        self.calls = 0
        self.returns = returns

    def __call__(self) -> object:
        self.calls += 1
        return self.returns


# -- the protocol ----------------------------------------------------------


def test_the_default_protocol_is_one_warmup_and_five_runs() -> None:
    """The paper states this protocol; a task must not quietly differ."""
    assert (WARMUP_RUNS, MEASURED_RUNS) == (1, 5)
    operation = Counter()
    measurement = measure(operation, memory=False)
    assert operation.calls == 6
    assert measurement.runs == 5


def test_the_warmup_is_recorded_but_not_measured() -> None:
    """Its cost is paid once per session, not once per analysis."""
    measurement = measure(Counter(), warmup=2, repeat=3, memory=False)
    assert len(measurement.warmup_seconds) == 2
    assert measurement.runs == 3


def test_the_last_result_is_kept() -> None:
    """So a caller needing the prepared data need not run a seventh time."""
    measurement = measure(Counter(returns="prepared"), repeat=2, memory=False)
    assert measurement.result == "prepared"


def test_at_least_one_measured_run_is_required() -> None:
    with pytest.raises(ValueError, match="at least one measured run"):
        measure(Counter(), repeat=0, memory=False)


def test_a_negative_warmup_is_refused() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        measure(Counter(), warmup=-1, memory=False)


def test_measurement_without_a_warmup_is_possible() -> None:
    operation = Counter()
    measure(operation, warmup=0, repeat=2, memory=False)
    assert operation.calls == 2


# -- what is reported ------------------------------------------------------


def test_the_median_is_what_the_schema_records() -> None:
    measurement = RuntimeMeasurement(seconds=(1.0, 2.0, 30.0))
    assert measurement.median == 2.0
    assert measurement.to_dict()["runtime_seconds"] == 2.0


def test_the_mean_and_spread_are_reported_beside_it() -> None:
    """A reader should see how noisy the measurement was."""
    measurement = RuntimeMeasurement(seconds=(1.0, 2.0, 3.0))
    assert measurement.mean == 2.0
    assert measurement.stdev == 1.0


def test_spread_over_a_single_run_is_undefined_not_zero() -> None:
    assert RuntimeMeasurement(seconds=(1.0,)).stdev is None


def test_to_dict_fills_only_result_schema_fields() -> None:
    measurement = RuntimeMeasurement(seconds=(1.0,), peak_memory_mb=12.5)
    assert measurement.to_dict() == {"runtime_seconds": 1.0, "peak_memory_mb": 12.5}


def test_summary_reads_as_a_run_log_line() -> None:
    measurement = RuntimeMeasurement(seconds=(1.0, 2.0, 3.0), peak_memory_mb=64.0)
    summary = measurement.summary()
    assert "median 2.000s" in summary
    assert "over 3 runs" in summary
    assert "64.0 MiB" in summary


def test_a_slower_operation_measures_slower() -> None:
    quick = measure(lambda: None, warmup=0, repeat=3, memory=False)
    slow = measure(lambda: time.sleep(0.01), warmup=0, repeat=3, memory=False)
    assert slow.median > quick.median


def test_the_result_carries_no_weight_in_equality() -> None:
    """Two measurements of the same cost are the same measurement."""
    assert RuntimeMeasurement(seconds=(1.0,), result="a") == RuntimeMeasurement(
        seconds=(1.0,), result="b"
    )


# -- peak memory -----------------------------------------------------------


def test_peak_memory_is_not_measured_when_not_asked_for() -> None:
    assert measure(Counter(), repeat=1, memory=False).peak_memory_mb is None


def test_peak_memory_sees_an_allocation_that_outlives_the_run() -> None:
    held: list[bytes] = []

    def allocate() -> None:
        held.append(b"x" * (32 * MIB))

    measurement = measure(allocate, warmup=0, repeat=1)
    assert measurement.peak_memory_mb is not None
    assert measurement.peak_memory_mb > 8


def test_peak_memory_sees_an_allocation_released_before_the_run_ends() -> None:
    """The point of sampling: the high-water mark, not the RSS at the end."""

    def allocate_and_release() -> None:
        transient = b"x" * (32 * MIB)
        time.sleep(0.05)
        del transient

    measurement = measure(allocate_and_release, warmup=0, repeat=1)
    assert measurement.peak_memory_mb is not None
    assert measurement.peak_memory_mb > 8


def test_peak_memory_of_a_trivial_operation_is_small_but_defined() -> None:
    measurement = measure(Counter(), warmup=0, repeat=1)
    assert measurement.peak_memory_mb is not None
    assert measurement.peak_memory_mb >= 0.0


# -- the environment -------------------------------------------------------


def test_the_environment_records_the_interpreter_and_host() -> None:
    environment = describe_environment()
    assert environment.python_version.startswith("3.")
    assert environment.system
    assert environment.cpu_count is None or environment.cpu_count >= 1


def test_the_environment_records_library_versions() -> None:
    """Methodology has to say which pandas produced the numbers."""
    environment = describe_environment()
    assert "pandas" in environment.packages
    assert environment.packages["pandas"]


def test_a_package_that_is_not_installed_is_omitted() -> None:
    """ "not installed" in an environment table tells a reader nothing."""
    environment = describe_environment(packages=("pandas", "definitely-not-installed"))
    assert set(environment.packages) == {"pandas"}


def test_the_environment_renders_the_methodology_block() -> None:
    rendered = describe_environment().to_markdown()
    assert "- OS:" in rendered
    assert "- Python:" in rendered
    assert "pandas" in rendered


def test_the_environment_is_written_beside_the_results(tmp_path: Path) -> None:
    target = tmp_path / "results" / "environment.json"
    written = write_environment(target)
    stored = json.loads(target.read_text(encoding="utf-8"))
    assert stored["python_version"] == written.python_version
    assert stored["packages"]["pandas"]
