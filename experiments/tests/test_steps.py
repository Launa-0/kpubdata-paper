from __future__ import annotations

import pytest

from kpx.steps import StepRecorder


def test_counts_top_level_steps() -> None:
    recorder = StepRecorder()
    for name in ("parse_price", "parse_date", "normalize_district"):
        with recorder.step(name):
            pass
    assert recorder.step_count == 3


def test_nested_steps_do_not_inflate_the_count() -> None:
    """A logical transformation stays one step however it is implemented."""
    recorder = StepRecorder()
    with recorder.step("normalize_columns"):
        with recorder.step("rename"):
            pass
        with recorder.step("retype"):
            pass
    assert recorder.step_count == 1
    assert [s.name for s in recorder.steps[0].children] == ["rename", "retype"]


def test_trace_includes_nested_steps_with_depth() -> None:
    recorder = StepRecorder()
    with recorder.step("outer"), recorder.step("inner"):
        pass
    assert [(name, depth) for name, depth, _ in recorder.trace()] == [("outer", 0), ("inner", 1)]


def test_step_records_duration() -> None:
    recorder = StepRecorder()
    with recorder.step("work"):
        sum(range(100_000))
    assert recorder.steps[0].seconds > 0
    assert recorder.total_seconds == pytest.approx(recorder.steps[0].seconds)


def test_step_is_recorded_even_when_it_raises() -> None:
    """A failed condition must still report how far it got."""
    recorder = StepRecorder()
    with pytest.raises(RuntimeError), recorder.step("parse_price"):
        raise RuntimeError("unparseable amount")
    assert recorder.step_count == 1


def test_reading_steps_mid_step_is_refused() -> None:
    recorder = StepRecorder()
    with recorder.step("outer"), pytest.raises(RuntimeError, match="still open"):
        _ = recorder.steps


def test_step_name_must_be_meaningful() -> None:
    recorder = StepRecorder()
    with pytest.raises(ValueError, match="non-empty"), recorder.step("  "):
        pass
