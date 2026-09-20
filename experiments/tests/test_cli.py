from __future__ import annotations

import pytest

from kpx.cli import main


def test_info_lists_conditions_and_layers(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["info"]) == 0
    out = capsys.readouterr().out
    assert "monolithic" in out
    assert "gold" in out


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert "kpx" in capsys.readouterr().out
